import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from airpods.cache import Cache
from airpods.logfetch import FetchResult
from airpods.parser import DeviceInfo, Sample
from airpods.server import AnalysisService, create_server, parse_datetime

BASE = datetime(2026, 10, 19, 10, 0, 0)
ADDR = "CC:4B:04:2C:FE:08"


def at(minutes, l=100, r=100, lc=False, rc=False, c=None):
    return Sample(
        ts=BASE + timedelta(minutes=minutes),
        address=ADDR,
        l=l,
        r=r,
        c=c,
        l_charging=lc,
        r_charging=rc,
        c_charging=False,
        cnx=True,
    )


class ParseDatetimeTests(unittest.TestCase):
    def test_date_only_end_of_day_includes_fractional_seconds(self):
        self.assertEqual(
            parse_datetime("2026-10-19", end_of_day=True),
            datetime(2026, 10, 19, 23, 59, 59, 999999),
        )

    def test_date_only_start_is_midnight(self):
        self.assertEqual(
            parse_datetime("2026-10-19", end_of_day=False),
            datetime(2026, 10, 19),
        )


class AnalysisServiceTests(unittest.TestCase):
    def setUp(self):
        self.cache = Cache(":memory:")
        self.service = AnalysisService(self.cache)

    def tearDown(self):
        self.cache.close()

    def test_returns_json_serializable_payload(self):
        self.cache.insert_samples([at(0, c=60), at(30, 90, 88, c=60), at(60, 80, 76, c=59)])
        self.cache.add_range(ADDR, BASE, BASE + timedelta(hours=2))

        payload = self.service.analysis(ADDR, BASE, BASE + timedelta(hours=2))
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertIn("sessions", encoded)
        self.assertEqual(payload["stats"]["session_count"], 1)
        self.assertEqual(len(payload["samples"]), 3)
        self.assertEqual(payload["samples"][0]["l"], 100)
        self.assertIn("ts", payload["samples"][0])

    def test_serializes_session_details(self):
        self.cache.insert_samples([at(0), at(4, 99, 99), at(10, 95, 94)])

        payload = self.service.analysis(ADDR, BASE, BASE + timedelta(hours=1))
        session = payload["sessions"][0]

        self.assertEqual(session["duration_min"], 10)
        self.assertEqual(session["l_start"], 100)
        self.assertEqual(session["l_end"], 95)
        self.assertEqual(session["l_drop"], 5)
        self.assertAlmostEqual(session["l_rate"], 30.0)
        self.assertEqual(session["l_first_drop"]["seconds"], 240)
        self.assertFalse(session["l_first_drop"]["skipped"])
        self.assertIn("start_ms", session)

    def test_reports_missing_coverage(self):
        payload = self.service.analysis(ADDR, BASE, BASE + timedelta(hours=1))

        self.assertEqual(
            payload["coverage"]["missing"],
            [{"start": "2026-10-19 10:00:00", "end": "2026-10-19 11:00:00"}],
        )
        self.assertIsNone(payload["coverage"]["first_sample"])

    def test_empty_samples_have_zero_stats(self):
        payload = self.service.analysis(ADDR, BASE, BASE + timedelta(hours=1))

        self.assertEqual(payload["samples"], [])
        self.assertEqual(payload["stats"]["session_count"], 0)
        self.assertIsNone(payload["stats"]["avg_rate_l"])

    def test_uses_cached_device_name(self):
        self.cache.upsert_device(ADDR, "Sqy's Pods", BASE)

        payload = self.service.analysis(ADDR, BASE, BASE + timedelta(hours=1))

        self.assertEqual(payload["device"]["name"], "Sqy's Pods")

    def test_includes_charging_sessions(self):
        self.cache.insert_samples(
            [
                at(0, 20, 30, lc=True, rc=True, c=90),
                at(30, 50, 60, lc=True, rc=True, c=85),
                at(60, 100, 100, lc=True, rc=True, c=80),
                at(70, 100, 100, lc=False, rc=False, c=78),
            ]
        )

        payload = self.service.analysis(ADDR, BASE, BASE + timedelta(hours=2))

        self.assertEqual(payload["stats"]["charging_session_count"], 1)
        self.assertEqual(len(payload["charging_sessions"]), 1)
        session = payload["charging_sessions"][0]
        self.assertAlmostEqual(session["l_rate"], 80.0)
        self.assertAlmostEqual(session["r_rate"], 70.0)
        self.assertEqual(session["c_drain"], 10)
        self.assertAlmostEqual(session["c_rate"], 10.0)
        self.assertTrue(session["full"])

        self.assertEqual(len(payload["charging_intervals"]), 1)
        self.assertEqual(
            payload["charging_intervals"][0]["start"], int(BASE.timestamp() * 1000)
        )
        self.assertEqual(
            payload["charging_intervals"][0]["end"],
            int((BASE + timedelta(minutes=60)).timestamp() * 1000),
        )

    def test_downsamples_chart_series_without_changing_stats(self):
        service = AnalysisService(self.cache, max_chart_points=4)
        self.cache.insert_samples(
            [at(minute, 100 - minute, 100 - minute) for minute in range(20)]
        )

        payload = service.analysis(ADDR, BASE, BASE + timedelta(hours=1))

        self.assertTrue(payload["chart"]["applied"])
        self.assertLessEqual(len(payload["samples"]), 4)
        self.assertEqual(payload["coverage"]["sample_count"], 20)
        self.assertEqual(payload["stats"]["sample_count"], 20)


class FakeFetcher:
    def __init__(self, samples):
        self.samples = samples
        self.calls = 0

    def __call__(
        self,
        address,
        start,
        end,
        on_sample,
        on_line=None,
        cancel_event=None,
        **kwargs,
    ):
        self.calls += 1
        for sample in self.samples:
            if not (start <= sample.ts <= end):
                continue
            if on_line is not None:
                on_line()
            on_sample(sample)
        return FetchResult(line_count=len(self.samples), sample_count=len(self.samples), cancelled=False)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.web_dir = Path(self.tempdir.name) / "web"
        self.web_dir.mkdir()
        (self.web_dir / "index.html").write_text("<html>analyzer</html>", encoding="utf-8")

        self.cache = Cache(":memory:")
        self.fetcher = FakeFetcher(
            [at(0, c=60), at(30, 90, 88, c=60), at(60, 80, 76, c=59)]
        )
        self.scanner_calls = []

        def scanner(days):
            self.scanner_calls.append(days)
            return [DeviceInfo(ADDR, "Sqy's Pods", BASE, 0)]

        self.server = create_server(
            cache=self.cache,
            web_dir=self.web_dir,
            host="127.0.0.1",
            port=0,
            fetcher=self.fetcher,
            scanner=scanner,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.jobs.shutdown()
        self.cache.close()
        self.tempdir.cleanup()

    def request(self, path, method="GET", payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_health(self):
        status, payload = self.request("/api/health")

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_serves_index(self):
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/", timeout=5
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("analyzer", response.read().decode("utf-8"))

    def test_device_discovery_caches_results(self):
        status, payload = self.request("/api/devices?scan=1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["devices"][0]["name"], "Sqy's Pods")
        self.assertEqual(self.scanner_calls, [1])

        status, payload = self.request("/api/devices")

        self.assertEqual(payload["devices"][0]["address"], ADDR)
        self.assertEqual(self.scanner_calls, [1])

    def test_fetch_then_analysis(self):
        status, job = self.request(
            "/api/fetch",
            method="POST",
            payload={
                "address": ADDR,
                "start": "2026-10-19",
                "end": "2026-10-19",
            },
        )
        self.assertEqual(status, 200)

        for _ in range(100):
            status, job = self.request(f"/api/jobs/{job['id']}")
            if job["status"] in ("done", "error", "cancelled"):
                break
            time.sleep(0.02)

        self.assertEqual(job["status"], "done")
        self.assertEqual(job["samples"], 3)
        self.assertEqual(self.fetcher.calls, 1)

        query = urllib.parse.urlencode(
            {"address": ADDR, "start": "2026-10-19", "end": "2026-10-19"}
        )
        status, analysis = self.request(f"/api/analysis?{query}")

        self.assertEqual(status, 200)
        self.assertEqual(analysis["stats"]["session_count"], 1)
        self.assertEqual(len(analysis["sessions"]), 1)
        self.assertEqual(analysis["coverage"]["missing"], [])
        self.assertEqual(analysis["samples"][0]["ts"], int(BASE.timestamp() * 1000))

    def test_invalid_address_is_rejected(self):
        status, payload = self.request(
            "/api/fetch",
            method="POST",
            payload={"address": "bad", "start": "2026-10-19", "end": "2026-10-19"},
        )

        self.assertEqual(status, 400)
        self.assertIn("地址", payload["error"])

    def test_analysis_without_data_reports_missing_range(self):
        query = urllib.parse.urlencode(
            {"address": ADDR, "start": "2026-10-19", "end": "2026-10-19"}
        )

        status, payload = self.request(f"/api/analysis?{query}")

        self.assertEqual(status, 200)
        self.assertEqual(payload["samples"], [])
        self.assertTrue(payload["coverage"]["missing"])

    def test_unknown_static_path_returns_404(self):
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/../secret", timeout=5
            )
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 404)
        else:
            self.fail("expected HTTP 404")


if __name__ == "__main__":
    unittest.main()
