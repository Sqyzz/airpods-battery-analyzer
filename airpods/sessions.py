from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .parser import Sample


@dataclass
class FirstDrop:
    seconds: float
    to_level: int
    skipped: bool


@dataclass
class Session:
    start: datetime
    end: datetime
    duration_min: float
    l_start: Optional[int] = None
    l_end: Optional[int] = None
    l_drop: Optional[int] = None
    l_rate: Optional[float] = None
    r_start: Optional[int] = None
    r_end: Optional[int] = None
    r_drop: Optional[int] = None
    r_rate: Optional[float] = None
    c_start: Optional[int] = None
    c_end: Optional[int] = None
    sample_count: int = 0
    max_gap_min: Optional[float] = None
    l_first_drop: Optional[FirstDrop] = None
    r_first_drop: Optional[FirstDrop] = None


def _first_drop(samples: list[Sample], ear: str, start: datetime) -> Optional[FirstDrop]:
    first = getattr(samples[0], ear)
    if first != 100:
        return None
    for sample in samples[1:]:
        value = getattr(sample, ear)
        if value is not None and value < 100:
            return FirstDrop(
                seconds=(sample.ts - start).total_seconds(),
                to_level=value,
                skipped=value != 99,
            )
    return None


def _summarize(samples: list[Sample]) -> Session:
    start = samples[0].ts
    end = samples[-1].ts
    duration_min = (end - start).total_seconds() / 60
    duration_hours = duration_min / 60

    l_start, l_end = samples[0].l, samples[-1].l
    r_start, r_end = samples[0].r, samples[-1].r
    l_drop = l_start - l_end
    r_drop = r_start - r_end

    gaps = [
        (b.ts - a.ts).total_seconds() / 60
        for a, b in zip(samples, samples[1:])
    ]

    case_values = [sample.c for sample in samples if sample.c is not None]

    return Session(
        start=start,
        end=end,
        duration_min=duration_min,
        l_start=l_start,
        l_end=l_end,
        l_drop=l_drop,
        l_rate=(l_drop / duration_hours) if duration_hours > 0 else None,
        r_start=r_start,
        r_end=r_end,
        r_drop=r_drop,
        r_rate=(r_drop / duration_hours) if duration_hours > 0 else None,
        c_start=case_values[0] if case_values else None,
        c_end=case_values[-1] if case_values else None,
        sample_count=len(samples),
        max_gap_min=max(gaps) if gaps else None,
        l_first_drop=_first_drop(samples, "l", start),
        r_first_drop=_first_drop(samples, "r", start),
    )


def build_sessions(samples, gap_minutes: float = 60) -> list[Session]:
    """Split connected, non-charging samples into usage sessions.

    A session ends when either earbud starts charging, or when two
    consecutive samples are more than ``gap_minutes`` apart.
    """
    usable = sorted(
        (
            sample
            for sample in samples
            if sample.cnx and sample.l is not None and sample.r is not None
        ),
        key=lambda sample: sample.ts,
    )

    sessions: list[Session] = []
    current: list[Sample] = []

    def flush() -> None:
        if len(current) >= 2:
            sessions.append(_summarize(list(current)))
        current.clear()

    for sample in usable:
        if sample.l_charging or sample.r_charging:
            flush()
            continue
        if current and (sample.ts - current[-1].ts).total_seconds() / 60 > gap_minutes:
            flush()
        current.append(sample)

    flush()
    return sessions
