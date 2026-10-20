import unittest
from datetime import datetime
from pathlib import Path

from airpods.parser import (
    parse_any_sample,
    parse_battery_info,
    parse_sample,
    scan_devices,
)

FIXTURE = Path(__file__).parent / "fixtures" / "device_lines.log"

LINE_NEARBY_CASE = (
    "2026-10-20 14:45:32.134 Df audioaccessoryd[70399:bfc7cb] [x] "
    "AANearbyDevice updated: AANearbyDevice identifier: "
    "C7E4DCBE-36A4-9958-7B74-43CDEF7B94B6, Bt addr 'C3:0F:22:5F:EC:E0', "
    "Md 'Device1,8213', Nm 'Sqy’s Pods Pro', paired, Case, "
    "Prim Id '9B702B90-EBC9-FB3F-6CA3-F82464097544', "
    "Prim Bt addr 'A4:C6:F0:CD:1D:2F'. AAProximityPairingAccessoryStatusPayload, "
    "PT: 7, PID 8213, ST: 6, lid open count: 0, lid closed: yes, need conn: no, "
    "connected: no, C Batt: -34%, L Batt: +100%, R Batt: +100%"
)

LINE_COMPONENT_BATTERY = (
    "2026-10-19 13:59:08.462 Df bluetoothd[616:b1ae6f] "
    "[com.apple.bluetooth:Server.Core] Component battery changed: "
    "device CC:4B:04:2C:FE:08, S 0%, L 100%, R 100%, Cs 65%, Cm 0%"
)

LINE_NEARBY_CASE_ONLY = (
    "2026-10-19 11:53:01.271 Df audioaccessoryd[70399:af0ff1] [x] "
    "AANearbyDevice identifier: A0BCA928-7770-0199-82BF-EDCE53786CA2, "
    "Bt addr 'CC:4B:04:2C:FE:08', Md 'Device1,8219', Nm 'Sqy‘s Pods', "
    "paired. AAProximityPairingStatusPayloadB188B288, My Batt: +100, "
    "Oth Batt: +100, C Batt: -63, lst conn hst: be2c63"
)

LINE_CASE_FIRST = (
    "2026-10-19 13:59:07.254 Df sharingd[1008:1c99] "
    "[com.apple.sharing:BLEAdv] BLE Prox changed SFBLEDevice ID "
    "bb00bca6-9567-1000-8000-001ff3fb80df, BDA CC:4B:04:2C:FE:08, "
    "RSSI -48 (0)t~U, Ch 37, AdvD <4c00>, ST Status, Nm 'BBoEoNvD', "
    "Md 'BBhlwYXd', Paired yes, Cnx no, ST=uC?rPbo1?s, CC=0, OBC=Off, "
    "Batt C -65%; R +100%; L +100%"
)

LINE_LR_CONNECTED = (
    "2026-10-19 14:00:09.579 Df sharingd[1008:1c99] "
    "[com.apple.sharing:BLEAdv] BLE Prox changed SFBLEDevice ID "
    "bb00bca6-9567-1000-8000-001ff3fb80df, BDA CC:4B:04:2C:FE:08, "
    "RSSI -48 (0)t~U, Ch 38, AdvD <4c00>, ST Status, Nm 'BBoEoNvD', "
    "Md 'BBhlwYXd', Paired yes, Cnx yes, ST=UEELPbo0?s, CC=0, OBC=Off, "
    "Batt L -100%; R -99%"
)

LINE_NO_MILLIS = (
    "2026-10-16 10:01:01 Df sharingd[1008:1c99] "
    "[com.apple.sharing:BLEAdv] BLE Prox found, BDA CC:4B:04:2C:FE:08, "
    "Cnx yes, Batt R -76%; L -75%"
)

LINE_NAME_ONLY = (
    "2026-10-19 15:28:13.679 Df audioaccessoryd[70399:b3eb22] "
    "[com.apple.bluetooth:BTSmartRoutingDaemon] _wxDeviceFound, "
    "Adding battery info to SR map, Address CC:4B:04:2C:FE:08 "
    "batteryLevel: 0.640000"
)


class ParseSampleTests(unittest.TestCase):
    def test_parses_case_first_line_with_charging_flags(self):
        sample = parse_sample(LINE_CASE_FIRST)

        self.assertIsNotNone(sample)
        self.assertEqual(sample.address, "CC:4B:04:2C:FE:08")
        self.assertEqual(sample.ts, datetime(2026, 10, 19, 13, 59, 7, 254000))
        self.assertEqual((sample.l, sample.r, sample.c), (100, 100, 65))
        self.assertTrue(sample.l_charging)
        self.assertTrue(sample.r_charging)
        self.assertFalse(sample.c_charging)
        self.assertFalse(sample.cnx)

    def test_parses_connected_line_without_case_battery(self):
        sample = parse_sample(LINE_LR_CONNECTED)

        self.assertIsNotNone(sample)
        self.assertEqual((sample.l, sample.r, sample.c), (100, 99, None))
        self.assertFalse(sample.l_charging)
        self.assertFalse(sample.r_charging)
        self.assertIsNone(sample.c_charging)
        self.assertTrue(sample.cnx)

    def test_parses_timestamp_without_milliseconds_and_reordered_fields(self):
        sample = parse_sample(LINE_NO_MILLIS)

        self.assertIsNotNone(sample)
        self.assertEqual(sample.ts, datetime(2026, 10, 16, 10, 1, 1))
        self.assertEqual((sample.l, sample.r), (75, 76))

    def test_ignores_non_ble_prox_lines(self):
        self.assertIsNone(parse_sample(LINE_NAME_ONLY))

    def test_ignores_percentages_outside_valid_range(self):
        sample = parse_sample(
            "2026-10-16 10:01:01.000 Df sharingd[1] BLE Prox changed "
            "BDA CC:4B:04:2C:FE:08, Cnx yes, Batt L -140%; R -76%"
        )

        self.assertIsNotNone(sample)
        self.assertIsNone(sample.l)
        self.assertEqual(sample.r, 76)

    def test_returns_none_when_no_valid_battery_component(self):
        self.assertIsNone(
            parse_sample(
                "2026-10-16 10:01:01.000 Df sharingd[1] BLE Prox changed "
                "BDA CC:4B:04:2C:FE:08, Cnx yes, Batt L -140%"
            )
        )

    def test_treats_zero_percent_as_unknown(self):
        sample = parse_sample(
            "2026-10-16 10:01:01.000 Df sharingd[1] BLE Prox changed "
            "BDA CC:4B:04:2C:FE:08, Cnx yes, Batt C -0%; L -0%; R -76%"
        )

        self.assertIsNotNone(sample)
        self.assertIsNone(sample.l)
        self.assertIsNone(sample.c)
        self.assertEqual(sample.r, 76)


class ParseBatteryInfoTests(unittest.TestCase):
    def test_parses_nearby_case_battery_and_maps_alias_to_primary(self):
        sample = parse_battery_info(LINE_NEARBY_CASE)

        self.assertIsNotNone(sample)
        self.assertEqual(sample.address, "A4:C6:F0:CD:1D:2F")
        self.assertEqual((sample.l, sample.r, sample.c), (100, 100, 34))
        self.assertTrue(sample.l_charging)
        self.assertTrue(sample.r_charging)
        self.assertFalse(sample.c_charging)
        self.assertFalse(sample.cnx)

    def test_parses_bluetoothd_component_battery_as_connected(self):
        sample = parse_battery_info(LINE_COMPONENT_BATTERY)

        self.assertIsNotNone(sample)
        self.assertEqual(sample.address, "CC:4B:04:2C:FE:08")
        self.assertEqual((sample.l, sample.r, sample.c), (100, 100, 65))
        self.assertTrue(sample.cnx)
        self.assertIsNone(sample.l_charging)

    def test_ignores_zero_components_in_component_battery(self):
        sample = parse_battery_info(
            "2026-10-19 13:59:09.082 Df bluetoothd[616] [x] "
            "Component battery changed: device CC:4B:04:2C:FE:08, "
            "S 0%, L 0%, R 100%, Cs 0%, Cm 0%"
        )

        self.assertIsNotNone(sample)
        self.assertIsNone(sample.l)
        self.assertEqual(sample.r, 100)
        self.assertIsNone(sample.c)

    def test_parses_case_only_battery_without_percent_signs(self):
        sample = parse_battery_info(LINE_NEARBY_CASE_ONLY)

        self.assertIsNotNone(sample)
        self.assertEqual(sample.address, "CC:4B:04:2C:FE:08")
        self.assertEqual((sample.l, sample.r, sample.c), (None, None, 63))
        self.assertFalse(sample.cnx)

    def test_ignores_unrelated_lines(self):
        self.assertIsNone(parse_battery_info(LINE_NAME_ONLY))

    def test_parse_any_sample_prefers_ble_prox_rows(self):
        sample = parse_any_sample(LINE_LR_CONNECTED)

        self.assertTrue(sample.cnx)
        self.assertEqual(sample.l, 100)

    def test_parse_any_sample_falls_back_to_audioaccessoryd_rows(self):
        sample = parse_any_sample(LINE_NEARBY_CASE)

        self.assertEqual(sample.address, "A4:C6:F0:CD:1D:2F")


class ScanDevicesTests(unittest.TestCase):
    def test_lists_stable_primary_addresses(self):
        lines = FIXTURE.read_text(encoding="utf-8").splitlines()

        devices = scan_devices(lines)

        self.assertEqual([d.address for d in devices], ["CC:4B:04:2C:FE:08"])

    def test_prefers_readable_name_over_obfuscated_name(self):
        devices = scan_devices(FIXTURE.read_text(encoding="utf-8").splitlines())

        self.assertEqual(devices[0].name, "Sqy's Pods")

    def test_records_last_seen_and_sample_count(self):
        devices = scan_devices(FIXTURE.read_text(encoding="utf-8").splitlines())

        self.assertEqual(devices[0].last_seen, datetime(2026, 10, 19, 14, 0, 9, 579000))
        self.assertEqual(devices[0].sample_count, 2)

    def test_falls_back_to_empty_name(self):
        devices = scan_devices([LINE_LR_CONNECTED])

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].name, "")

    def test_collapses_rotating_case_alias_to_primary_device(self):
        lines = [
            "2026-10-20 14:45:32.133 Df audioaccessoryd[1] [x] AANearbyDevice updated: "
            "AANearbyDevice identifier: C7E4DCBE-36A4-9958-7B74-43CDEF7B94B6, "
            "Bt addr 'C3:0F:22:5F:EC:E0', Md 'Device1,8213', Nm 'Sqy’s Pods Pro', "
            "paired, Case, Prim Id '9B702B90-EBC9-FB3F-6CA3-F82464097544', "
            "Prim Bt addr 'A4:C6:F0:CD:1D:2F'. AAProximityPairingAccessoryStatusPayload, "
            "C Batt: -34%, L Batt: +100%, R Batt: +100%",
            "2026-10-20 14:45:32.131 Df sharingd[1] [x] BLE Prox found, "
            "BDA C3:0F:22:5F:EC:E0, Cnx no, Batt C -34%",
            "2026-10-20 14:45:32.200 Df audioaccessoryd[1] [x] AADeviceBatteryInfo updated: "
            "AADeviceBatteryInfo identifier: 9B702B90-EBC9-FB3F-6CA3-F82464097544, "
            "Bt Addr 'A4:C6:F0:CD:1D:2F', Col '255', Nm 'Sqy’s Pods Pro', Pid '8212'",
        ]

        devices = scan_devices(lines)

        self.assertEqual([d.address for d in devices], ["A4:C6:F0:CD:1D:2F"])
        self.assertEqual(devices[0].name, "Sqy's Pods Pro")
        self.assertEqual(devices[0].sample_count, 1)

    def test_lists_known_device_even_without_recent_samples(self):
        line = (
            "2026-10-20 14:45:32.200 Df audioaccessoryd[1] [x] AADeviceBatteryInfo updated: "
            "AADeviceBatteryInfo identifier: 9B702B90-EBC9-FB3F-6CA3-F82464097544, "
            "Bt Addr 'A4:C6:F0:CD:1D:2F', Col '255', Nm 'Sqy’s Pods Pro', Pid '8212'"
        )

        devices = scan_devices([line])

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].sample_count, 0)
        self.assertEqual(devices[0].last_seen, datetime(2026, 10, 20, 14, 45, 32, 200000))

    def test_ignores_unknown_random_broadcast_addresses(self):
        line = (
            "2026-10-20 14:45:32.131 Df sharingd[1] [x] BLE Prox found, "
            "BDA AA:BB:CC:DD:EE:FF, Cnx no, Batt C -34%"
        )

        self.assertEqual(scan_devices([line]), [])


if __name__ == "__main__":
    unittest.main()
