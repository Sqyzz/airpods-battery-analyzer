import unittest
from datetime import datetime, timedelta

from airpods.compress import compress_samples
from airpods.parser import Sample

BASE = datetime(2026, 10, 19, 10, 0, 0)


def at(minutes, l=100, r=100, lc=False):
    return Sample(
        ts=BASE + timedelta(minutes=minutes),
        address="CC:4B:04:2C:FE:08",
        l=l,
        r=r,
        c=None,
        l_charging=lc,
        r_charging=lc,
        c_charging=False,
        cnx=True,
    )


class CompressSamplesTests(unittest.TestCase):
    def test_keeps_state_changes_and_heartbeat(self):
        samples = [at(minute) for minute in range(7)]

        kept = compress_samples(samples, heartbeat_seconds=300)

        self.assertEqual(
            [int((sample.ts - BASE).total_seconds() // 60) for sample in kept],
            [0, 5],
        )

    def test_state_change_resets_heartbeat(self):
        samples = [
            at(0, l=100),
            at(1, l=100),
            at(2, l=90),
            at(3, l=90),
            at(5, l=90),
            at(7, l=90),
        ]

        kept = compress_samples(samples, heartbeat_seconds=300)

        self.assertEqual(
            [int((sample.ts - BASE).total_seconds() // 60) for sample in kept],
            [0, 2, 7],
        )

    def test_charging_state_change_is_kept(self):
        samples = [at(0, lc=False), at(1, lc=False), at(2, lc=True), at(3, lc=True)]

        kept = compress_samples(samples, heartbeat_seconds=300)

        self.assertEqual(len(kept), 2)
        self.assertFalse(kept[0].l_charging)
        self.assertTrue(kept[1].l_charging)

    def test_empty_input(self):
        self.assertEqual(compress_samples([]), [])


if __name__ == "__main__":
    unittest.main()
