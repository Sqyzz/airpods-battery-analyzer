import unittest
from datetime import datetime, timedelta

from airpods.cache import Cache
from airpods.parser import Sample

BASE = datetime(2026, 10, 19, 10, 0, 0)
ADDR = "CC:4B:04:2C:FE:08"


def at(minutes, **kwargs):
    return Sample(
        ts=BASE + timedelta(minutes=minutes),
        address=ADDR,
        l=kwargs.get("l", 100),
        r=kwargs.get("r", 100),
        c=kwargs.get("c"),
        l_charging=kwargs.get("lc", False),
        r_charging=kwargs.get("rc", False),
        c_charging=None,
        cnx=kwargs.get("cnx", True),
    )


class CacheSampleTests(unittest.TestCase):
    def setUp(self):
        self.cache = Cache(":memory:")

    def tearDown(self):
        self.cache.close()

    def test_round_trips_samples_in_time_order(self):
        self.cache.insert_samples([at(10, l=95, r=94, c=60), at(0, l=100, r=100)])

        samples = self.cache.get_samples(ADDR, BASE, BASE + timedelta(hours=1))

        self.assertEqual([s.ts for s in samples], [BASE, BASE + timedelta(minutes=10)])
        self.assertEqual((samples[0].l, samples[1].r, samples[1].c), (100, 94, 60))

    def test_duplicate_timestamp_is_replaced_not_duplicated(self):
        self.cache.insert_samples([at(0, l=100, r=100)])
        self.cache.insert_samples([at(0, l=99, r=98)])

        samples = self.cache.get_samples(ADDR, BASE, BASE + timedelta(hours=1))

        self.assertEqual(len(samples), 1)
        self.assertEqual((samples[0].l, samples[0].r), (99, 98))

    def test_get_samples_respects_time_window(self):
        self.cache.insert_samples([at(0), at(10), at(20)])

        samples = self.cache.get_samples(
            ADDR, BASE + timedelta(minutes=5), BASE + timedelta(minutes=15)
        )

        self.assertEqual([s.ts for s in samples], [BASE + timedelta(minutes=10)])

    def test_compresses_identical_consecutive_samples(self):
        self.cache.insert_samples([at(0), at(1), at(2), at(6)])

        samples = self.cache.get_samples(ADDR, BASE, BASE + timedelta(hours=1))

        self.assertEqual(
            [s.ts for s in samples],
            [BASE, BASE + timedelta(minutes=6)],
        )


class CacheRangeTests(unittest.TestCase):
    def setUp(self):
        self.cache = Cache(":memory:")

    def tearDown(self):
        self.cache.close()

    def test_reports_uncovered_ranges(self):
        self.cache.add_range(ADDR, BASE, BASE + timedelta(hours=1))

        missing = self.cache.missing_ranges(
            ADDR, BASE - timedelta(hours=1), BASE + timedelta(hours=2)
        )

        self.assertEqual(
            missing,
            [
                (BASE - timedelta(hours=1), BASE),
                (BASE + timedelta(hours=1), BASE + timedelta(hours=2)),
            ],
        )

    def test_merges_overlapping_and_adjacent_ranges(self):
        self.cache.add_range(ADDR, BASE, BASE + timedelta(hours=1))
        self.cache.add_range(ADDR, BASE + timedelta(hours=2), BASE + timedelta(hours=3))
        self.cache.add_range(ADDR, BASE + timedelta(hours=1), BASE + timedelta(hours=2))

        self.assertEqual(
            self.cache.get_ranges(ADDR),
            [(BASE, BASE + timedelta(hours=3))],
        )

    def test_no_missing_when_fully_covered(self):
        self.cache.add_range(ADDR, BASE, BASE + timedelta(hours=3))

        self.assertEqual(
            self.cache.missing_ranges(ADDR, BASE + timedelta(hours=1), BASE + timedelta(hours=2)),
            [],
        )

    def test_treats_tiny_trailing_gap_as_covered(self):
        self.cache.add_range(ADDR, BASE, BASE + timedelta(hours=1))

        missing = self.cache.missing_ranges(
            ADDR,
            BASE,
            BASE + timedelta(hours=1, seconds=30),
            tolerance_seconds=60,
        )

        self.assertEqual(missing, [])

    def test_ignores_small_gaps_between_cached_ranges(self):
        self.cache.add_range(ADDR, BASE, BASE + timedelta(hours=1))
        self.cache.add_range(ADDR, BASE + timedelta(hours=1, seconds=30), BASE + timedelta(hours=2))

        missing = self.cache.missing_ranges(
            ADDR, BASE, BASE + timedelta(hours=2), tolerance_seconds=60
        )

        self.assertEqual(missing, [])

    def test_ranges_are_per_address(self):
        other = "AA:BB:CC:DD:EE:FF"
        self.cache.add_range(ADDR, BASE, BASE + timedelta(hours=1))

        self.assertEqual(
            self.cache.missing_ranges(other, BASE, BASE + timedelta(hours=1)),
            [(BASE, BASE + timedelta(hours=1))],
        )


class CacheDeviceTests(unittest.TestCase):
    def setUp(self):
        self.cache = Cache(":memory:")

    def tearDown(self):
        self.cache.close()

    def test_upserts_and_lists_devices_with_sample_count(self):
        self.cache.upsert_device(ADDR, "Sqy's Pods", BASE)
        self.cache.insert_samples([at(0), at(1, l=99, r=99)])

        devices = self.cache.list_devices()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].address, ADDR)
        self.assertEqual(devices[0].name, "Sqy's Pods")
        self.assertEqual(devices[0].last_seen, BASE)
        self.assertEqual(devices[0].sample_count, 2)

    def test_empty_name_does_not_overwrite_existing_name(self):
        self.cache.upsert_device(ADDR, "Sqy's Pods", BASE)
        self.cache.upsert_device(ADDR, "", BASE + timedelta(minutes=5))

        devices = self.cache.list_devices()

        self.assertEqual(devices[0].name, "Sqy's Pods")
        self.assertEqual(devices[0].last_seen, BASE + timedelta(minutes=5))


if __name__ == "__main__":
    unittest.main()
