import unittest
from datetime import datetime, timedelta

from airpods.charging import build_charging_sessions
from airpods.parser import Sample

BASE = datetime(2026, 10, 19, 13, 0, 0)
ADDR = "CC:4B:04:2C:FE:08"


def at(minutes, l=None, r=None, c=None, lc=True, rc=True):
    return Sample(
        ts=BASE + timedelta(minutes=minutes),
        address=ADDR,
        l=l,
        r=r,
        c=c,
        l_charging=lc,
        r_charging=rc,
        c_charging=None,
        cnx=True,
    )


class BuildChargingSessionsTests(unittest.TestCase):
    def test_computes_ear_charge_rates_and_case_drain(self):
        samples = [
            at(0, 20, 30, 90),
            at(30, 50, 60, 85),
            at(60, 80, 90, 80),
            at(70, 100, 100, 78),
            at(80, 100, 100, 78, lc=False, rc=False),
        ]

        sessions = build_charging_sessions(samples)

        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session.start, BASE)
        self.assertEqual(session.end, BASE + timedelta(minutes=70))
        self.assertAlmostEqual(session.duration_min, 70)
        self.assertEqual((session.l_start, session.l_end), (20, 100))
        self.assertAlmostEqual(session.l_rate, 80 / (70 / 60), places=3)
        self.assertAlmostEqual(session.l_full_min, 70)
        self.assertEqual((session.r_start, session.r_end), (30, 100))
        self.assertAlmostEqual(session.r_rate, 70 / (70 / 60), places=3)
        self.assertEqual((session.c_start, session.c_end, session.c_drain), (90, 78, 12))
        self.assertAlmostEqual(session.c_rate, 12 / (70 / 60), places=3)
        self.assertTrue(session.full)
        self.assertEqual(session.sample_count, 4)

    def test_already_full_reports_zero_charge_rate(self):
        samples = [
            at(0, 100, 100, 60),
            at(10, 100, 100, 59),
            at(20, 100, 100, 58),
            at(30, 100, 100, 58, lc=False, rc=False),
        ]

        session = build_charging_sessions(samples)[0]

        self.assertEqual(session.l_rate, 0.0)
        self.assertEqual(session.r_rate, 0.0)
        self.assertEqual(session.l_full_min, 0.0)
        self.assertTrue(session.full)
        self.assertEqual(session.c_drain, 2)
        self.assertAlmostEqual(session.c_rate, 6.0)

    def test_one_ear_charging_only(self):
        samples = [
            at(0, 50, None, 80, lc=True, rc=False),
            at(30, 80, None, 75, lc=True, rc=False),
            at(40, None, None, None, lc=False, rc=False),
        ]

        session = build_charging_sessions(samples)[0]

        self.assertEqual((session.l_start, session.l_end), (50, 80))
        self.assertAlmostEqual(session.l_rate, 60.0)
        self.assertIsNone(session.r_start)
        self.assertIsNone(session.r_rate)
        self.assertIsNone(session.l_full_min)
        self.assertFalse(session.full)
        self.assertEqual(session.c_drain, 5)
        self.assertAlmostEqual(session.c_rate, 10.0)

    def test_unknown_charging_flags_do_not_split_a_session(self):
        unknown = Sample(
            ts=BASE + timedelta(minutes=10),
            address=ADDR,
            l=60,
            r=60,
            c=89,
            l_charging=None,
            r_charging=None,
            c_charging=None,
            cnx=True,
        )
        samples = [
            at(0, 50, 50, 90),
            unknown,
            at(30, 80, 80, 85),
            at(40, 80, 80, 85, lc=False, rc=False),
        ]

        sessions = build_charging_sessions(samples)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].sample_count, 2)
        self.assertAlmostEqual(sessions[0].duration_min, 30)

    def test_gap_longer_than_threshold_splits_sessions(self):
        samples = [
            at(0, 20, 20, 90),
            at(10, 40, 40, 88),
            at(80, 60, 60, 80),
            at(90, 80, 80, 78),
            at(100, 90, 90, 78, lc=False, rc=False),
        ]

        sessions = build_charging_sessions(samples, gap_minutes=60)

        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].end, BASE + timedelta(minutes=10))
        self.assertEqual(sessions[1].start, BASE + timedelta(minutes=80))

    def test_requires_at_least_two_charging_samples(self):
        samples = [at(0, 20, 20, 90), at(10, 20, 20, 90, lc=False, rc=False)]

        self.assertEqual(build_charging_sessions(samples), [])

    def test_negative_case_rate_means_case_is_charging(self):
        samples = [
            at(0, 20, 20, 50),
            at(30, 50, 50, 60),
            at(40, 50, 50, 60, lc=False, rc=False),
        ]

        session = build_charging_sessions(samples)[0]

        self.assertEqual(session.c_drain, -10)
        self.assertAlmostEqual(session.c_rate, -20.0)


if __name__ == "__main__":
    unittest.main()
