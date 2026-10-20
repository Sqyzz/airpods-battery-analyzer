import unittest
from datetime import datetime, timedelta

from airpods.parser import Sample
from airpods.sessions import build_sessions

BASE = datetime(2026, 10, 19, 13, 0, 0)


def sample(minutes, l=None, r=None, c=None, lc=False, rc=False, cnx=True):
    return Sample(
        ts=BASE + timedelta(minutes=minutes),
        address="CC:4B:04:2C:FE:08",
        l=l,
        r=r,
        c=c,
        l_charging=lc,
        r_charging=rc,
        c_charging=False,
        cnx=cnx,
    )


class BuildSessionsTests(unittest.TestCase):
    def test_builds_one_session_with_drop_and_rate(self):
        samples = [
            sample(0, 100, 100, c=65),
            sample(10, 99, 98),
            sample(20, 97, 96, c=65),
            sample(25, 57, 57, lc=True, rc=True),
        ]

        sessions = build_sessions(samples)

        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session.start, BASE)
        self.assertEqual(session.end, BASE + timedelta(minutes=20))
        self.assertEqual(session.duration_min, 20)
        self.assertEqual((session.l_start, session.l_end, session.l_drop), (100, 97, 3))
        self.assertEqual((session.r_start, session.r_end, session.r_drop), (100, 96, 4))
        self.assertAlmostEqual(session.l_rate, 9.0)
        self.assertAlmostEqual(session.r_rate, 12.0)
        self.assertEqual((session.c_start, session.c_end), (65, 65))
        self.assertEqual(session.sample_count, 3)

    def test_charging_ends_session_and_next_use_is_new_session(self):
        samples = [
            sample(0, 100, 100),
            sample(10, 90, 90),
            sample(11, 89, 89, lc=True, rc=True),
            sample(30, 100, 100),
            sample(40, 95, 95),
        ]

        sessions = build_sessions(samples)

        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].start, BASE)
        self.assertEqual(sessions[0].end, BASE + timedelta(minutes=10))
        self.assertEqual(sessions[1].start, BASE + timedelta(minutes=30))
        self.assertEqual(sessions[1].end, BASE + timedelta(minutes=40))

    def test_gap_longer_than_threshold_splits_sessions(self):
        samples = [
            sample(0, 100, 100),
            sample(10, 90, 90),
            sample(71, 80, 80),
            sample(80, 70, 70),
        ]

        sessions = build_sessions(samples, gap_minutes=60)

        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].end, BASE + timedelta(minutes=10))
        self.assertEqual(sessions[1].start, BASE + timedelta(minutes=71))

    def test_ignores_disconnected_samples(self):
        samples = [
            sample(0, 100, 100, cnx=False),
            sample(5, 100, 100),
            sample(15, 90, 90),
        ]

        sessions = build_sessions(samples)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].start, BASE + timedelta(minutes=5))
        self.assertEqual(sessions[0].sample_count, 2)

    def test_skips_samples_missing_an_ear(self):
        samples = [
            sample(0, 100, 100),
            sample(10, 99, None),
            sample(20, 97, 97),
        ]

        sessions = build_sessions(samples)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].sample_count, 2)
        self.assertEqual(sessions[0].l_end, 97)
        self.assertEqual(sessions[0].r_end, 97)

    def test_requires_at_least_two_samples(self):
        sessions = build_sessions([sample(0, 100, 100)])

        self.assertEqual(sessions, [])

    def test_tracks_first_drop_below_100(self):
        samples = [
            sample(0, 100, 100),
            sample(4, 99, 100),
            sample(5, 99, 99),
            sample(10, 97, 97),
        ]

        session = build_sessions(samples)[0]

        self.assertEqual(session.l_first_drop.seconds, 240)
        self.assertEqual(session.l_first_drop.to_level, 99)
        self.assertFalse(session.l_first_drop.skipped)
        self.assertEqual(session.r_first_drop.seconds, 300)
        self.assertEqual(session.r_first_drop.to_level, 99)
        self.assertFalse(session.r_first_drop.skipped)

    def test_marks_first_drop_as_skipped_when_99_was_not_broadcast(self):
        samples = [
            sample(0, 100, 100),
            sample(13, 96, 91),
            sample(20, 90, 85),
        ]

        session = build_sessions(samples)[0]

        self.assertEqual(session.l_first_drop.to_level, 96)
        self.assertTrue(session.l_first_drop.skipped)
        self.assertEqual(session.l_first_drop.seconds, 13 * 60)

    def test_no_first_drop_when_session_starts_below_100(self):
        samples = [
            sample(0, 83, 84),
            sample(5, 80, 81),
        ]

        session = build_sessions(samples)[0]

        self.assertIsNone(session.l_first_drop)
        self.assertIsNone(session.r_first_drop)

    def test_tracks_maximum_sample_gap(self):
        samples = [
            sample(0, 100, 100),
            sample(2, 99, 99),
            sample(12, 90, 90),
        ]

        session = build_sessions(samples)[0]

        self.assertEqual(session.max_gap_min, 10)


if __name__ == "__main__":
    unittest.main()
