import json
import mimetypes
import os
import sys
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .analysis import build_analysis
from .cache import Cache
from .downsample import downsample_samples
from .jobs import JobBusyError, JobManager
from .logfetch import discover_devices, validate_address

DEFAULT_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def default_db_path() -> str:
    override = os.environ.get("AIRPODS_ANALYZER_DB")
    if override:
        return override
    return os.path.expanduser("~/.airpods-analyzer/cache.sqlite3")


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _round(value, digits=1):
    return round(value, digits) if isinstance(value, float) else value


def _device_to_dict(device) -> dict:
    return {
        "address": device.address,
        "name": device.name,
        "last_seen": _iso(device.last_seen) if device.last_seen else None,
        "sample_count": device.sample_count,
    }


def _sample_to_dict(sample) -> dict:
    return {
        "ts": _ms(sample.ts),
        "l": sample.l,
        "r": sample.r,
        "c": sample.c,
        "lc": sample.l_charging,
        "rc": sample.r_charging,
        "cnx": sample.cnx,
    }


def _first_drop_to_dict(drop):
    if drop is None:
        return None
    return {
        "seconds": round(drop.seconds, 1),
        "to_level": drop.to_level,
        "skipped": drop.skipped,
    }


def _session_to_dict(session) -> dict:
    return {
        "start": _iso(session.start),
        "end": _iso(session.end),
        "start_ms": _ms(session.start),
        "end_ms": _ms(session.end),
        "duration_min": _round(session.duration_min),
        "l_start": session.l_start,
        "l_end": session.l_end,
        "l_drop": session.l_drop,
        "l_rate": _round(session.l_rate),
        "r_start": session.r_start,
        "r_end": session.r_end,
        "r_drop": session.r_drop,
        "r_rate": _round(session.r_rate),
        "c_start": session.c_start,
        "c_end": session.c_end,
        "sample_count": session.sample_count,
        "max_gap_min": _round(session.max_gap_min),
        "l_first_drop": _first_drop_to_dict(session.l_first_drop),
        "r_first_drop": _first_drop_to_dict(session.r_first_drop),
    }


def _charging_session_to_dict(session) -> dict:
    return {
        "start": _iso(session.start),
        "end": _iso(session.end),
        "start_ms": _ms(session.start),
        "end_ms": _ms(session.end),
        "duration_min": _round(session.duration_min),
        "l_start": session.l_start,
        "l_end": session.l_end,
        "l_rate": _round(session.l_rate),
        "l_full_min": _round(session.l_full_min),
        "r_start": session.r_start,
        "r_end": session.r_end,
        "r_rate": _round(session.r_rate),
        "r_full_min": _round(session.r_full_min),
        "c_start": session.c_start,
        "c_end": session.c_end,
        "c_drain": session.c_drain,
        "c_rate": _round(session.c_rate),
        "full": session.full,
        "full_min": _round(session.full_min),
        "sample_count": session.sample_count,
        "max_gap_min": _round(session.max_gap_min),
    }


def parse_datetime(value, end_of_day: bool = False) -> datetime:
    if value is None or str(value).strip() == "":
        raise ValueError("缺少时间参数")
    text = str(value).strip().replace("T", " ")
    if len(text) == 10:
        parsed = datetime.strptime(text, "%Y-%m-%d")
        if end_of_day:
            parsed = parsed.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
        return parsed
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(text)


class AnalysisService:
    def __init__(self, cache, scanner=None, max_chart_points: int = 2000):
        self.cache = cache
        self.scanner = scanner or discover_devices
        self.max_chart_points = max_chart_points

    def cached_devices(self) -> list[dict]:
        return [_device_to_dict(device) for device in self.cache.list_devices()]

    def scan_devices(self, days: int) -> list[dict]:
        for device in self.scanner(days):
            self.cache.upsert_device(device.address, device.name, device.last_seen)
        return self.cached_devices()

    def analysis(self, address: str, start: datetime, end: datetime, gap_minutes: float = 60) -> dict:
        address = validate_address(address)
        samples = self.cache.get_samples(address, start, end)
        result = build_analysis(samples, gap_minutes=gap_minutes)

        missing = self.cache.missing_ranges(
            address, start, end, tolerance_seconds=60
        )
        cached_ranges = self.cache.get_ranges(address)
        devices = self.cache.list_devices()
        device = next((item for item in devices if item.address == address), None)

        first_sample = samples[0].ts if samples else None
        last_sample = samples[-1].ts if samples else None
        chart = downsample_samples(samples, max_points=self.max_chart_points)

        charging_intervals = [
            (session.start, session.end)
            for session in result["charging_sessions"]
        ] or result["charging_intervals"]

        return {
            "device": (
                _device_to_dict(device)
                if device
                else {"address": address, "name": "", "last_seen": None, "sample_count": 0}
            ),
            "range": {"start": _iso(start), "end": _iso(end)},
            "samples": [_sample_to_dict(sample) for sample in chart.samples],
            "chart": {
                "applied": chart.applied,
                "original_points": chart.original_points,
                "returned_points": chart.returned_points,
                "bucket_seconds": _round(chart.bucket_seconds),
            },
            "sessions": [_session_to_dict(session) for session in result["sessions"]],
            "charging_sessions": [
                _charging_session_to_dict(session)
                for session in result["charging_sessions"]
            ],
            "charging_intervals": [
                {"start": _ms(start_time), "end": _ms(end_time)}
                for start_time, end_time in charging_intervals
            ],
            "stats": {
                key: _round(value) for key, value in result["stats"].items()
            },
            "coverage": {
                "requested": {"start": _iso(start), "end": _iso(end)},
                "cached": [
                    {"start": _iso(range_start), "end": _iso(range_end)}
                    for range_start, range_end in cached_ranges
                ],
                "missing": [
                    {"start": _iso(range_start), "end": _iso(range_end)}
                    for range_start, range_end in missing
                ],
                "first_sample": _iso(first_sample) if first_sample else None,
                "last_sample": _iso(last_sample) if last_sample else None,
                "sample_count": len(samples),
            },
        }


class AnalyzerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, *, cache, service, jobs, web_dir):
        self.cache = cache
        self.service = service
        self.jobs = jobs
        self.web_dir = Path(web_dir)
        super().__init__(server_address, handler_class)


class Handler(BaseHTTPRequestHandler):
    server_version = "AirPodsBatteryAnalyzer/1.0"

    def log_message(self, fmt, *args):  # keep the console quiet
        return

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 1_000_000:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("请求体不是合法 JSON") from error

    def _handle_error(self, error: Exception) -> None:
        if isinstance(error, JobBusyError):
            self._send_json(409, {"error": str(error)})
        elif isinstance(error, ValueError):
            self._send_json(400, {"error": str(error)})
        else:
            traceback.print_exc(file=sys.stderr)
            self._send_json(500, {"error": str(error)})

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._send_json(200, {"ok": True})
            elif parsed.path == "/api/devices":
                self._devices(parsed)
            elif parsed.path.startswith("/api/jobs/"):
                parts = parsed.path.strip("/").split("/")
                if len(parts) != 3:
                    self._send_json(404, {"error": "任务不存在"})
                    return
                job = self.server.jobs.get(parts[2])
                if job is None:
                    self._send_json(404, {"error": "任务不存在"})
                else:
                    self._send_json(200, job.to_dict())
            elif parsed.path == "/api/analysis":
                self._analysis(parsed)
            else:
                self._static(parsed.path)
        except Exception as error:  # noqa: BLE001 - converted into an HTTP error
            self._handle_error(error)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/fetch":
                start = parse_datetime(payload.get("start"), end_of_day=False)
                end = parse_datetime(payload.get("end"), end_of_day=True)
                job = self.server.jobs.start_fetch(
                    payload.get("address", ""), start, end
                )
                self._send_json(200, job.to_dict())
            elif parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/cancel"):
                parts = parsed.path.strip("/").split("/")
                if len(parts) != 4:
                    self._send_json(404, {"error": "任务不存在"})
                    return
                cancelled = self.server.jobs.cancel(parts[2])
                self._send_json(200, {"cancelled": cancelled})
            else:
                self._send_json(404, {"error": "接口不存在"})
        except Exception as error:  # noqa: BLE001 - converted into an HTTP error
            self._handle_error(error)

    def _devices(self, parsed) -> None:
        query = parse_qs(parsed.query)
        scan = query.get("scan", [None])[0]
        if scan:
            days = int(str(scan).rstrip("dD"))
            devices = self.server.service.scan_devices(days)
        else:
            devices = self.server.service.cached_devices()
        self._send_json(200, {"devices": devices})

    def _analysis(self, parsed) -> None:
        query = parse_qs(parsed.query)
        address = query.get("address", [""])[0]
        start = parse_datetime(query.get("start", [""])[0], end_of_day=False)
        end = parse_datetime(query.get("end", [""])[0], end_of_day=True)
        gap = float(query.get("gap", ["60"])[0])
        payload = self.server.service.analysis(address, start, end, gap_minutes=gap)
        self._send_json(200, payload)

    def _static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"

        web_dir = self.server.web_dir.resolve()
        target = (web_dir / path.lstrip("/")).resolve()

        if target != web_dir and not target.is_relative_to(web_dir):
            self._text(404, "not found")
            return
        if not target.is_file():
            self._text(404, "not found")
            return

        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
            "application/javascript",
            "application/json",
        ):
            content_type += "; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, status: int, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_server(
    cache=None,
    web_dir=None,
    host: str = "127.0.0.1",
    port: int = 8765,
    fetcher=None,
    scanner=None,
    max_chart_points: int = 2000,
):
    if cache is None:
        cache = Cache(default_db_path())
    if web_dir is None:
        web_dir = DEFAULT_WEB_DIR

    service = AnalysisService(
        cache, scanner=scanner, max_chart_points=max_chart_points
    )
    jobs = JobManager(cache, fetcher=fetcher)
    return AnalyzerServer(
        (host, port),
        Handler,
        cache=cache,
        service=service,
        jobs=jobs,
        web_dir=Path(web_dir),
    )
