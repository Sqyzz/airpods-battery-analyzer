import stat
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from airpods.logfetch import (
    FetchResult,
    LogFetchError,
    build_command,
    build_discover_command,
    discover_devices,
    stream_samples,
    validate_address,
)

FIXTURE = Path(__file__).parent / "fixtures" / "device_lines.log"
START = datetime(2026, 10, 19, 0, 0, 0)
END = datetime(2026, 10, 20, 0, 0, 0)
ADDR = "CC:4B:04:2C:FE:08"


def make_script(directory: Path, body: str) -> Path:
    path = directory / "fake_log"
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class ValidationTests(unittest.TestCase):
    def test_accepts_mac_address(self):
        self.assertEqual(validate_address("cc:4b:04:2c:fe:08"), ADDR)

    def test_rejects_bad_address(self):
        with self.assertRaises(ValueError):
            validate_address("CC:4B:04:2C:FE")

    def test_builds_log_show_command_with_quoted_predicate(self):
        command = build_command(ADDR, START, END)

        self.assertEqual(command[0], "/usr/bin/log")
        self.assertIn("show", command)
        self.assertIn(ADDR, command[-1])
        self.assertIn("Batt", command[-1])
        self.assertNotIn(";", command[-1])

    def test_builds_command_restricted_to_relevant_processes(self):
        predicate = build_command(ADDR, START, END)[-1]

        for process in ("sharingd", "audioaccessoryd", "bluetoothd"):
            self.assertIn(f'process == "{process}"', predicate)


class StreamSamplesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.dir = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_streams_samples_and_counts_lines(self):
        script = make_script(self.dir, f"cat '{FIXTURE}'\n")
        samples = []
        lines = []

        result = stream_samples(
            ADDR,
            START,
            END,
            on_sample=samples.append,
            on_line=lambda: lines.append(1),
            log_bin=str(script),
        )

        self.assertIsInstance(result, FetchResult)
        self.assertEqual(result.sample_count, 3)
        self.assertEqual(result.line_count, len(FIXTURE.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(len(samples), 3)
        self.assertEqual(len(lines), result.line_count)
        self.assertFalse(result.cancelled)

    def test_raises_on_nonzero_exit_with_stderr(self):
        script = make_script(self.dir, "echo 'permission denied' >&2\nexit 2\n")

        with self.assertRaises(LogFetchError) as context:
            stream_samples(
                ADDR, START, END, on_sample=lambda sample: None, log_bin=str(script)
            )

        self.assertIn("permission denied", str(context.exception))

    def test_honours_cancel_event(self):
        script = make_script(
            self.dir,
            "while true; do echo '2026-10-19 10:00:00.000 BLE Prox changed "
            "BDA CC:4B:04:2C:FE:08, Cnx yes, Batt L -100%; R -100%'; sleep 0.05; done\n",
        )
        cancel = threading.Event()
        cancel.set()

        result = stream_samples(
            ADDR,
            START,
            END,
            on_sample=lambda sample: None,
            cancel_event=cancel,
            log_bin=str(script),
        )

        self.assertTrue(result.cancelled)


class DiscoverDevicesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.dir = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_discovers_devices_from_log_output(self):
        script = make_script(self.dir, f"cat '{FIXTURE}'\n")

        devices = discover_devices(scan_days=1, log_bin=str(script))

        self.assertEqual([device.address for device in devices], [ADDR])
        self.assertEqual(devices[0].name, "Sqy's Pods")

    def test_rejects_unreasonable_scan_window(self):
        with self.assertRaises(ValueError):
            discover_devices(scan_days=0, log_bin="/bin/true")

    def test_builds_narrow_discovery_command(self):
        command = build_discover_command(7)

        self.assertIn("--last", command)
        self.assertIn("7d", command)
        self.assertIn('process == "audioaccessoryd"', command[-1])
        self.assertIn("AADeviceBatteryInfo", command[-1])


if __name__ == "__main__":
    unittest.main()
