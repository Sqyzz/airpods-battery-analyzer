import threading
import time
import unittest
from datetime import datetime, timedelta

from airpods.cache import Cache
from airpods.jobs import JobBusyError, JobManager
from airpods.logfetch import FetchResult
from airpods.parser import Sample

BASE = datetime(2026, 10, 19, 10, 0, 0)
ADDR = "CC:4B:04:2C:FE:08"


def at(minutes, l=100, r=100):
    return Sample(
        ts=BASE + timedelta(minutes=minutes),
        address=ADDR,
        l=l,
        r=r,
        c=None,
        l_charging=False,
        r_charging=False,
        c_charging=False,
        cnx=True,
    )


class FakeFetcher:
    def __init__(self, samples=None, error=None, block_event=None):
        self.samples = samples or []
        self.error = error
        self.block_event = block_event
        self.started = threading.Event()
        self.calls = []

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
        self.calls.append((start, end))
        self.started.set()
        if self.block_event is not None:
            self.block_event.wait(5)
        if self.error is not None:
            raise self.error
        for sample in self.samples:
            if on_line is not None:
                on_line()
            on_sample(sample)
        return FetchResult(
            line_count=len(self.samples),
            sample_count=len(self.samples),
            cancelled=False,
        )


class JobManagerTests(unittest.TestCase):
    def setUp(self):
        self.cache = Cache(":memory:")
        self.manager = JobManager(self.cache)

    def tearDown(self):
        self.manager.shutdown()
        self.cache.close()

    def test_fetches_missing_range_and_persists_samples(self):
        fetcher = FakeFetcher([at(0), at(10)])
        manager = JobManager(self.cache, fetcher=fetcher)

        job = manager.start_fetch(ADDR, BASE, BASE + timedelta(hours=1))
        job.wait(5)

        self.assertEqual(job.status, "done")
        self.assertEqual(job.lines, 2)
        self.assertEqual(job.samples, 2)
        stored = self.cache.get_samples(ADDR, BASE, BASE + timedelta(hours=1))
        self.assertEqual(len(stored), 2)
        self.assertEqual(len(fetcher.calls), 1)
        self.assertEqual(
            self.cache.missing_ranges(ADDR, BASE, BASE + timedelta(hours=1)), []
        )
        manager.shutdown()

    def test_uses_cache_and_skips_fetch_when_covered(self):
        self.cache.add_range(ADDR, BASE, BASE + timedelta(hours=1))
        fetcher = FakeFetcher([at(0)])
        manager = JobManager(self.cache, fetcher=fetcher)

        job = manager.start_fetch(ADDR, BASE, BASE + timedelta(hours=1))
        job.wait(5)

        self.assertEqual(job.status, "done")
        self.assertEqual(fetcher.calls, [])
        manager.shutdown()

    def test_reports_fetcher_errors(self):
        fetcher = FakeFetcher(error=RuntimeError("boom"))
        manager = JobManager(self.cache, fetcher=fetcher)

        job = manager.start_fetch(ADDR, BASE, BASE + timedelta(hours=1))
        job.wait(5)

        self.assertEqual(job.status, "error")
        self.assertIn("boom", job.error)
        manager.shutdown()

    def test_cancel_marks_job_cancelled(self):
        def blocking_fetcher(
            address, start, end, on_sample, on_line=None, cancel_event=None, **kwargs
        ):
            while not cancel_event.is_set():
                time.sleep(0.01)
            return FetchResult(0, 0, True)

        manager = JobManager(self.cache, fetcher=blocking_fetcher)
        job = manager.start_fetch(ADDR, BASE, BASE + timedelta(hours=1))
        time.sleep(0.05)

        self.assertTrue(manager.cancel(job.id))
        job.wait(5)

        self.assertEqual(job.status, "cancelled")
        manager.shutdown()

    def test_only_one_active_job(self):
        gate = threading.Event()
        fetcher = FakeFetcher([at(0)], block_event=gate)
        manager = JobManager(self.cache, fetcher=fetcher)
        job = manager.start_fetch(ADDR, BASE, BASE + timedelta(hours=1))
        fetcher.started.wait(2)

        with self.assertRaises(JobBusyError):
            manager.start_fetch(ADDR, BASE, BASE + timedelta(hours=2))

        gate.set()
        job.wait(5)
        manager.shutdown()

    def test_rejects_invalid_address(self):
        with self.assertRaises(ValueError):
            self.manager.start_fetch("not-an-address", BASE, BASE + timedelta(hours=1))

    def test_job_dict_contains_progress_fields(self):
        fetcher = FakeFetcher([at(0)])
        manager = JobManager(self.cache, fetcher=fetcher)

        job = manager.start_fetch(ADDR, BASE, BASE + timedelta(hours=1))
        job.wait(5)
        payload = job.to_dict()

        self.assertEqual(payload["address"], ADDR)
        self.assertEqual(payload["status"], "done")
        self.assertIn("elapsed_seconds", payload)
        self.assertIn("stage", payload)
        manager.shutdown()


if __name__ == "__main__":
    unittest.main()
