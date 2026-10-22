from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .parser import Sample


@dataclass
class ChargingSession:
    start: datetime
    end: datetime
    duration_min: float
    l_start: Optional[int] = None
    l_end: Optional[int] = None
    l_rate: Optional[float] = None
    l_full_min: Optional[float] = None
    r_start: Optional[int] = None
    r_end: Optional[int] = None
    r_rate: Optional[float] = None
    r_full_min: Optional[float] = None
    c_start: Optional[int] = None
    c_end: Optional[int] = None
    c_drain: Optional[int] = None
    c_rate: Optional[float] = None
    full: bool = False
    full_min: Optional[float] = None
    sample_count: int = 0
    max_gap_min: Optional[float] = None


def _ear_stats(samples: list[Sample], ear: str):
    values = [
        (sample.ts, getattr(sample, ear))
        for sample in samples
        if getattr(sample, f"{ear}_charging") is True
        and getattr(sample, ear) is not None
    ]
    if not values:
        return None, None, None, None

    start_ts, start_value = values[0]
    end_value = values[-1][1]

    if start_value >= 100:
        return start_value, end_value, 0.0, 0.0

    full_at = next((ts for ts, value in values if value >= 100), None)
    if full_at is not None:
        hours = (full_at - start_ts).total_seconds() / 3600
        rate = (100 - start_value) / hours if hours > 0 else None
        full_min = (full_at - start_ts).total_seconds() / 60
        return start_value, end_value, rate, full_min

    if len(values) < 2:
        return start_value, end_value, None, None

    hours = (values[-1][0] - start_ts).total_seconds() / 3600
    rate = (end_value - start_value) / hours if hours > 0 else None
    return start_value, end_value, rate, None


def _summarize(samples: list[Sample]) -> ChargingSession:
    start = samples[0].ts
    end = samples[-1].ts
    duration_min = (end - start).total_seconds() / 60

    l_start, l_end, l_rate, l_full_min = _ear_stats(samples, "l")
    r_start, r_end, r_rate, r_full_min = _ear_stats(samples, "r")

    case_values = [sample.c for sample in samples if sample.c is not None]
    if len(case_values) >= 2:
        c_start, c_end = case_values[0], case_values[-1]
        c_drain = c_start - c_end
        c_rate = c_drain / (duration_min / 60) if duration_min > 0 else None
    elif len(case_values) == 1:
        c_start = c_end = case_values[0]
        c_drain = None
        c_rate = None
    else:
        c_start = c_end = c_drain = c_rate = None

    charging_ends = [
        end_value
        for end_value in (l_end, r_end)
        if end_value is not None
    ]
    full = bool(charging_ends) and all(value >= 100 for value in charging_ends)
    full_times = [value for value in (l_full_min, r_full_min) if value is not None]
    full_min = max(full_times) if full and full_times else None

    gaps = [
        (b.ts - a.ts).total_seconds() / 60
        for a, b in zip(samples, samples[1:])
    ]

    return ChargingSession(
        start=start,
        end=end,
        duration_min=duration_min,
        l_start=l_start,
        l_end=l_end,
        l_rate=l_rate,
        l_full_min=l_full_min,
        r_start=r_start,
        r_end=r_end,
        r_rate=r_rate,
        r_full_min=r_full_min,
        c_start=c_start,
        c_end=c_end,
        c_drain=c_drain,
        c_rate=c_rate,
        full=full,
        full_min=full_min,
        sample_count=len(samples),
        max_gap_min=max(gaps) if gaps else None,
    )


def build_charging_sessions(
    samples, gap_minutes: float = 60
) -> list[ChargingSession]:
    """Split charging periods into sessions.

    A session is active while at least one component (left earbud, right
    earbud, or charging case) is charging. Unknown charging flags keep the
    last known state of that component, so earbud usage samples that carry
    no case data do not end a case-charging session. A session ends when
    every component's last known state is "not charging", or when the gap
    between charging samples is too large.
    """
    sessions: list[ChargingSession] = []
    current: list[Sample] = []
    known = {"l": None, "r": None, "c": None}

    def flush() -> None:
        if len(current) >= 2:
            sessions.append(_summarize(list(current)))
        current.clear()

    for sample in sorted(samples, key=lambda item: item.ts):
        for key, value in (
            ("l", sample.l_charging),
            ("r", sample.r_charging),
            ("c", sample.c_charging),
        ):
            if value is not None:
                known[key] = value

        if any(value is True for value in known.values()):
            if current and (
                sample.ts - current[-1].ts
            ).total_seconds() / 60 > gap_minutes:
                flush()
            if sample.l_charging or sample.r_charging or sample.c_charging:
                current.append(sample)
        else:
            flush()

    flush()
    return sessions
