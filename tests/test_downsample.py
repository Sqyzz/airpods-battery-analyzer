import unittest
from datetime import datetime, timedelta

from airpods.downsample import downsample_samples
from airpods.parser import Sample

BASE = datetime(2026, 10, 19, 10, 0, 0)


def at(minutes, l=100):
    return Sample(
        ts=BASE + timedelta(minutes=minutes),
        address="CC:4B:04:2C:FE:08",
        l=l,
        r=l,
        c=None,
        l_charging=False,
        r_charging=False,
        c_charging=False,
        cnx=True,
    )


class DownsampleTests(unittest.TestCase):
    def test_returns_all_points_when_below_limit(self):
        samples = [at(0), at(10), at(20)]

        result = downsample_samples(samples, max_points=10)

        self.assertEqual(result.samples, samples)
        self.assertFalse(result.applied)
        self.assertEqual(result.original_points, 3)
        self.assertEqual(result.returned_points, 3)
        self.assertIsNone(result.bucket_seconds)

    def test_reduces_points_while_keeping_time_order_and_endpoints(self):
        samples = [at(minute, l=100 - minute // 10) for minute in range(100)]

        result = downsample_samples(samples, max_points=10)

        self.assertTrue(result.applied)
        self.assertLessEqual(result.returned_points, 10)
        self.assertEqual(result.samples[0].ts, BASE)
        self.assertEqual(result.samples[-1].ts, BASE + timedelta(minutes=99))
        timestamps = [sample.ts for sample in result.samples]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertEqual(len(timestamps), len(set(timestamps)))
        self.assertIsNotNone(result.bucket_seconds)
        self.assertGreater(result.bucket_seconds, 0)

    def test_reports_original_and_returned_counts(self):
        samples = [at(minute) for minute in range(50)]

        result = downsample_samples(samples, max_points=5)

        self.assertEqual(result.original_points, 50)
        self.assertEqual(result.returned_points, len(result.samples))
        self.assertLessEqual(result.returned_points, 5)

    def test_single_sample_is_returned_unchanged(self):
        result = downsample_samples([at(0)], max_points=5)

        self.assertEqual(len(result.samples), 1)
        self.assertFalse(result.applied)

    def test_identical_timestamps_do_not_crash(self):
        samples = [at(0), at(0), at(0), at(0)]

        result = downsample_samples(samples, max_points=2)

        self.assertGreaterEqual(len(result.samples), 1)
        self.assertLessEqual(len(result.samples), 2)


if __name__ == "__main__":
    unittest.main()
