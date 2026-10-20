import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?"
)
BLE_PROX_RE = re.compile(r"\bBLE Prox (?:found|changed|lost)\b")
BDA_RE = re.compile(r"\bBDA ([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\b")
BATT_RE = re.compile(r"\bBatt (.+)$")
COMPONENT_RE = re.compile(r"\b([LRC]) ([+-]?)(\d+)%")
CNX_RE = re.compile(r"\bCnx (yes|no)\b")
NM_RE = re.compile(r"\bNm '([^']+)'")
NM_ALT_RE = re.compile(r"\bnm ([^,]+),")
NAME_ADDR_RE = re.compile(
    r"\bname ([^,]+), addr ([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\b"
)
PRIM_BT_RE = re.compile(r"\bPrim Bt addr '([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})'")
BT_ADDR_LOWER_RE = re.compile(r"\bBt addr '([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})'")
BT_ADDR_UPPER_RE = re.compile(r"\bBt Addr '([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})'")
CASE_RE = re.compile(r",\s*Case\s*,")
INFO_COMPONENT_RE = re.compile(r"\b([LRC]) Batt: ([+-]?)(\d+)%")
CASE_ONLY_RE = re.compile(r"\bC Batt: ([+-]?)(\d+)%?")
COMPONENT_DEVICE_RE = re.compile(
    r"Component battery changed: device ([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})"
)
COMPONENT_L_RE = re.compile(r"\bL (\d+)%")
COMPONENT_R_RE = re.compile(r"\bR (\d+)%")
COMPONENT_CS_RE = re.compile(r"\bCs (\d+)%")
CONNECTED_RE = re.compile(r"\bconnected: yes\b")
CNX_YES_RE = re.compile(r"\bCnx yes\b")
OBFUSCATED_RE = re.compile(r"[A-Za-z0-9]{6,12}")


@dataclass
class Sample:
    ts: datetime
    address: str
    l: Optional[int] = None
    r: Optional[int] = None
    c: Optional[int] = None
    l_charging: Optional[bool] = None
    r_charging: Optional[bool] = None
    c_charging: Optional[bool] = None
    cnx: bool = False


@dataclass
class DeviceInfo:
    address: str
    name: str
    last_seen: Optional[datetime] = None
    sample_count: int = 0


def _parse_timestamp(line: str) -> Optional[datetime]:
    match = TIMESTAMP_RE.match(line)
    if not match:
        return None
    date_part, time_part, fraction = match.groups()
    try:
        parsed = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if fraction:
        parsed = parsed.replace(microsecond=int(fraction.ljust(6, "0")))
    return parsed


def normalize_name(name: str) -> str:
    return name.replace("‘", "'").replace("’", "'").strip()


def _name_score(name: str) -> int:
    score = 0
    if OBFUSCATED_RE.fullmatch(name):
        score -= 10
    if " " in name:
        score += 3
    if "'" in name:
        score += 2
    if len(name) >= 8:
        score += 1
    return score


def parse_sample(line: str) -> Optional[Sample]:
    """Parse one BLE proximity battery broadcast line.

    Returns None for lines that are not BLE Prox battery events or that
    contain no valid battery component.
    """
    if not BLE_PROX_RE.search(line):
        return None

    timestamp = _parse_timestamp(line)
    if timestamp is None:
        return None

    bda_match = BDA_RE.search(line)
    if not bda_match:
        return None

    batt_match = BATT_RE.search(line)
    if not batt_match:
        return None

    values = {}
    for label, sign, percent in COMPONENT_RE.findall(batt_match.group(1)):
        level = int(percent)
        if 0 < level <= 100:
            values[label] = (level, sign == "+")

    if not values:
        return None

    def level(label: str) -> Optional[int]:
        return values[label][0] if label in values else None

    def charging(label: str) -> Optional[bool]:
        return values[label][1] if label in values else None

    cnx_match = CNX_RE.search(line)
    return Sample(
        ts=timestamp,
        address=bda_match.group(1).upper(),
        l=level("L"),
        r=level("R"),
        c=level("C"),
        l_charging=charging("L"),
        r_charging=charging("R"),
        c_charging=charging("C"),
        cnx=bool(cnx_match and cnx_match.group(1) == "yes"),
    )


def parse_battery_info(line: str) -> Optional[Sample]:
    """Parse battery values from audioaccessoryd / bluetoothd log lines.

    These lines carry the stable device address even when the BLE
    advertising address has rotated, and are the only battery source for
    some AirPods models.
    """
    if BLE_PROX_RE.search(line):
        return None

    timestamp = _parse_timestamp(line)
    if timestamp is None:
        return None

    values = {}
    charging = {}
    cnx = False
    address = None

    if "Component battery changed" in line:
        device = COMPONENT_DEVICE_RE.search(line)
        l_match = COMPONENT_L_RE.search(line)
        r_match = COMPONENT_R_RE.search(line)
        c_match = COMPONENT_CS_RE.search(line)
        if not device or not (l_match or r_match or c_match):
            return None
        address = device.group(1).upper()
        for label, match in (("L", l_match), ("R", r_match), ("C", c_match)):
            if match:
                level = int(match.group(1))
                if 0 < level <= 100:
                    values[label] = level
                    charging[label] = None
        cnx = True
    else:
        for label, sign, percent in INFO_COMPONENT_RE.findall(line):
            level = int(percent)
            if 0 < level <= 100:
                values[label] = level
                charging[label] = sign == "+"

        if "C" not in values:
            case_only = CASE_ONLY_RE.search(line)
            if case_only:
                level = int(case_only.group(2))
                if 0 < level <= 100:
                    values["C"] = level
                    charging["C"] = case_only.group(1) == "+"

        address = _info_address(line)
        cnx = bool(CONNECTED_RE.search(line) or CNX_YES_RE.search(line))

    if address is None or not values:
        return None

    return Sample(
        ts=timestamp,
        address=address,
        l=values.get("L"),
        r=values.get("R"),
        c=values.get("C"),
        l_charging=charging.get("L"),
        r_charging=charging.get("R"),
        c_charging=charging.get("C"),
        cnx=cnx,
    )


def parse_any_sample(line: str) -> Optional[Sample]:
    return parse_sample(line) or parse_battery_info(line)


def _info_address(line: str) -> Optional[str]:
    primary = PRIM_BT_RE.search(line)
    if primary:
        return primary.group(1).upper()

    if "AADeviceBatteryInfo" in line:
        stable = BT_ADDR_UPPER_RE.search(line)
        if stable:
            return stable.group(1).upper()

    if "AANearbyDevice" in line and not CASE_RE.search(line):
        address = BT_ADDR_LOWER_RE.search(line)
        if address:
            return address.group(1).upper()

    return None


def _stable_mentions(line: str) -> Iterable[tuple[str, str]]:
    """Yield (stable_address, name) pairs from audioaccessoryd lines.

    AirPods rotate their BLE advertising address (especially a charging
    case while the lid is closed). The stable identity is the "Prim Bt addr"
    or the "Bt Addr" reported by AADeviceBatteryInfo.
    """
    name_match = NM_RE.search(line) or NM_ALT_RE.search(line)
    name = normalize_name(name_match.group(1)) if name_match else ""

    primary = PRIM_BT_RE.search(line)
    if primary:
        yield primary.group(1).upper(), name
        return

    if "AANearbyDevice" in line and not CASE_RE.search(line):
        address = BT_ADDR_LOWER_RE.search(line)
        if address:
            yield address.group(1).upper(), name
            return

    if "AADeviceBatteryInfo" in line:
        address = BT_ADDR_UPPER_RE.search(line)
        if address:
            yield address.group(1).upper(), name
            return

    explicit = NAME_ADDR_RE.search(line)
    if explicit:
        raw_name, address = explicit.groups()
        yield address.upper(), normalize_name(raw_name)


def _alias_mapping(line: str) -> Optional[tuple[str, str]]:
    """Map a rotating advertising address to the stable primary address."""
    primary = PRIM_BT_RE.search(line)
    alias = BT_ADDR_LOWER_RE.search(line)
    if primary and alias:
        return alias.group(1).upper(), primary.group(1).upper()
    return None


def scan_devices(lines: Iterable[str]) -> list[DeviceInfo]:
    """Find physical AirPods devices, collapsing rotating BLE addresses.

    Only stable identity addresses (and, as a fallback, addresses seen in a
    connected battery broadcast) are listed. Randomised advertising addresses
    from a closed charging case are mapped to their primary device or ignored.
    """
    stable_names: dict[str, Counter] = defaultdict(Counter)
    stable_seen: dict[str, datetime] = {}
    aliases: dict[str, str] = {}
    raw_samples: list[Sample] = []

    for line in lines:
        timestamp = _parse_timestamp(line)
        sample = parse_sample(line)
        if sample is not None:
            raw_samples.append(sample)

        alias = _alias_mapping(line)
        if alias is not None:
            aliases[alias[0]] = alias[1]

        for address, name in _stable_mentions(line):
            if name:
                stable_names[address][name] += 1
            if timestamp is not None:
                previous = stable_seen.get(address)
                if previous is None or timestamp > previous:
                    stable_seen[address] = timestamp

    samples: dict[str, list[Sample]] = defaultdict(list)
    for sample in raw_samples:
        stable = aliases.get(sample.address, sample.address)
        if stable in stable_names:
            samples[stable].append(sample)
        elif sample.cnx:
            # Connected broadcasts use the identity address; keep them even
            # if no audioaccessoryd line was present in the scanned window.
            samples[sample.address].append(sample)

    addresses = set(stable_names) | set(samples)
    devices = []
    for address in addresses:
        candidates = stable_names.get(address, Counter())
        best_name = ""
        if candidates:
            best_name = max(
                candidates,
                key=lambda candidate: (
                    _name_score(candidate),
                    candidates[candidate],
                    len(candidate),
                ),
            )

        device_samples = samples.get(address, [])
        last_seen = (
            max(sample.ts for sample in device_samples)
            if device_samples
            else stable_seen.get(address)
        )
        devices.append(
            DeviceInfo(
                address=address,
                name=best_name,
                last_seen=last_seen,
                sample_count=len(device_samples),
            )
        )

    devices.sort(
        key=lambda device: device.last_seen or datetime.min,
        reverse=True,
    )
    return devices
