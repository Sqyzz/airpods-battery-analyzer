import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime

from .parser import scan_devices

LOG_BIN = "/usr/bin/log"
ADDRESS_RE = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


class LogFetchError(RuntimeError):
    pass


@dataclass
class FetchResult:
    line_count: int
    sample_count: int
    cancelled: bool
    stderr_tail: str = ""


def validate_address(address: str) -> str:
    value = (address or "").strip().upper()
    if not ADDRESS_RE.fullmatch(value):
        raise ValueError("蓝牙地址格式无效，应为 XX:XX:XX:XX:XX:XX")
    return value


def build_command(
    address: str, start: datetime, end: datetime, log_bin: str = LOG_BIN
) -> list[str]:
    address = validate_address(address)
    predicate = (
        '(process == "sharingd" OR process == "audioaccessoryd" '
        'OR process == "bluetoothd") '
        f'AND eventMessage CONTAINS[c] "{address}" '
        'AND eventMessage CONTAINS[c] "Batt"'
    )
    return [
        log_bin,
        "show",
        "--start",
        start.strftime(TIMESTAMP_FORMAT),
        "--end",
        end.strftime(TIMESTAMP_FORMAT),
        "--style",
        "compact",
        "--predicate",
        predicate,
    ]


def _stream(command, line_handler, cancel_event=None):
    if cancel_event is not None and cancel_event.is_set():
        return 0, 0, True, ""

    stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    process = None
    line_count = 0
    sample_count = 0
    cancelled = False

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        for line in process.stdout:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                process.terminate()
                break
            line_count += 1
            sample_count += line_handler(line)

        if cancelled:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        else:
            process.wait()

        stderr_file.seek(0)
        stderr = stderr_file.read()

        if not cancelled and process.returncode != 0:
            raise LogFetchError(
                f"log show 执行失败（退出码 {process.returncode}）：{stderr.strip()[-500:]}"
            )

        return line_count, sample_count, cancelled, stderr.strip()[-1000:]
    finally:
        if process is not None:
            if process.stdout is not None:
                process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait()
        stderr_file.close()


def stream_samples(
    address,
    start,
    end,
    on_sample,
    on_line=None,
    cancel_event=None,
    log_bin=LOG_BIN,
) -> FetchResult:
    from .parser import parse_any_sample

    command = build_command(address, start, end, log_bin=log_bin)

    def handle(line: str) -> int:
        if on_line is not None:
            on_line()
        sample = parse_any_sample(line)
        if sample is None:
            return 0
        on_sample(sample)
        return 1

    line_count, sample_count, cancelled, stderr = _stream(
        command, handle, cancel_event=cancel_event
    )
    return FetchResult(
        line_count=line_count,
        sample_count=sample_count,
        cancelled=cancelled,
        stderr_tail=stderr,
    )


DISCOVER_PREDICATE = (
    'process == "audioaccessoryd" '
    'AND eventMessage CONTAINS[c] "AADeviceBatteryInfo updated"'
)


def build_discover_command(scan_days: int, log_bin: str = LOG_BIN) -> list[str]:
    if not 1 <= scan_days <= 30:
        raise ValueError("扫描范围必须是 1 到 30 天")
    return [
        log_bin,
        "show",
        "--last",
        f"{scan_days}d",
        "--style",
        "compact",
        "--predicate",
        DISCOVER_PREDICATE,
    ]


def discover_devices(scan_days: int = 1, log_bin: str = LOG_BIN):
    command = build_discover_command(scan_days, log_bin=log_bin)

    collected = []

    def handle(line: str) -> int:
        collected.append(line)
        return 0

    _stream(command, handle)
    return scan_devices(collected)
