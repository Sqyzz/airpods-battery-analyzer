import unittest
from datetime import datetime, timedelta

from airpods.analysis import build_analysis, build_charging_intervals
from airpods.parser import Sample

BASE = datetime(2026, 10, 19, 13, 0, 0)


def sample(minutes, l=100, r=100, c=None, lc=False, rc=False, cc=False, cnx=True):
    return Sample(
        ts=BASE + timedelta(minutes=minutes),
        address="CC:4B:04:2C:FE:08",
        l=l,
        r=r,
        c=c,
        l_charging=lc,
        r_charging=rc,
        c_charging=cc,
        cnx=cnx,
    )


class BuildAnalysisTests(unittest.TestCase):
    def test_summarizes_sessions_and_overall_rates(self):
        samples = [
            sample(0),
            sample(30, 90, 88),
            sample(60, 80, 76),
            sample(65, 80, 76, lc=True, rc=True),
            sample(100, 100, 100),
            sample(130, 95, 90),
        ]

        analysis = build_analysis(samples)

        self.assertEqual(analysis["stats"]["session_count"], 2)
        self.assertAlmostEqual(analysis["stats"]["total_minutes"], 90)
        self.assertEqual(analysis["stats"]["total_l_drop"], 25)
        self.assertEqual(analysis["stats"]["total_r_drop"], 34)
        self.assertAlmostEqual(analysis["stats"]["avg_rate_l"], 25 / 1.5, places=4)
        self.assertAlmostEqual(analysis["stats"]["avg_rate_r"], 34 / 1.5, places=4)
        self.assertEqual(len(analysis["sessions"]), 2)

    def test_empty_samples_return_zero_stats(self):
        analysis = build_analysis([])

        self.assertEqual(analysis["sessions"], [])
        self.assertEqual(analysis["stats"]["session_count"], 0)
        self.assertEqual(analysis["stats"]["total_minutes"], 0)
        self.assertIsNone(analysis["stats"]["avg_rate_l"])
        self.assertIsNone(analysis["stats"]["avg_rate_r"])

    def test_includes_charging_sessions_and_aggregate_stats(self):
        samples = [
            sample(0, 20, 20, c=90, lc=True, rc=True),
            sample(30, 50, 50, c=85, lc=True, rc=True),
            sample(60, 100, 100, c=80, lc=True, rc=True),
            sample(70, 100, 100, c=78, lc=False, rc=False),
        ]

        analysis = build_analysis(samples)

        self.assertEqual(len(analysis["charging_sessions"]), 1)
        self.assertEqual(analysis["stats"]["charging_session_count"], 1)
        self.assertEqual(analysis["stats"]["total_charge_minutes"], 60)
        self.assertEqual(analysis["stats"]["total_case_drain"], 10)
        self.assertAlmostEqual(analysis["stats"]["avg_case_rate"], 10.0)


class ChargingIntervalTests(unittest.TestCase):
    def test_merges_consecutive_charging_samples(self):
        samples = [
            sample(0),
            sample(10, lc=True, rc=True),
            sample(15, lc=True, rc=True),
            sample(20, lc=True, rc=True),
            sample(25),
        ]

        intervals = build_charging_intervals(samples, merge_gap_seconds=300)

        self.assertEqual(intervals, [(BASE + timedelta(minutes=10), BASE + timedelta(minutes=20))])

    def test_splits_when_gap_exceeds_threshold(self):
        samples = [
            sample(0, lc=True, rc=True),
            sample(1, lc=True, rc=True),
            sample(20, lc=True, rc=True),
        ]

        intervals = build_charging_intervals(samples, merge_gap_seconds=300)

        self.assertEqual(
            intervals,
            [
                (BASE, BASE + timedelta(minutes=1)),
                (BASE + timedelta(minutes=20), BASE + timedelta(minutes=20)),
            ],
        )

    def test_single_ear_charging_counts(self):
        samples = [sample(0, lc=True, rc=False), sample(1, lc=True, rc=False)]

        intervals = build_charging_intervals(samples)

        self.assertEqual(intervals, [(BASE, BASE + timedelta(minutes=1))])

    def test_case_only_charging_counts(self):
        samples = [
            sample(0, c=40, cc=True),
            sample(1, c=41, cc=True),
            sample(2, c=42, cc=False),
        ]

        intervals = build_charging_intervals(samples)

        self.assertEqual(intervals, [(BASE, BASE + timedelta(minutes=1))])


if __name__ == "__main__":
    unittest.main()
