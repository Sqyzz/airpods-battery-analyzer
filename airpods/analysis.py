from .charging import build_charging_sessions
from .sessions import build_sessions


def build_charging_intervals(samples, merge_gap_seconds: float = 300):
    """Return contiguous intervals where any component is charging."""
    timestamps = sorted(
        sample.ts
        for sample in samples
        if sample.l_charging or sample.r_charging or sample.c_charging
    )

    intervals = []
    start = previous = None
    for timestamp in timestamps:
        if start is None:
            start = previous = timestamp
        elif (timestamp - previous).total_seconds() > merge_gap_seconds:
            intervals.append((start, previous))
            start = previous = timestamp
        else:
            previous = timestamp

    if start is not None:
        intervals.append((start, previous))
    return intervals


def build_analysis(samples, gap_minutes: float = 60):
    sessions = build_sessions(samples, gap_minutes=gap_minutes)
    charging_sessions = build_charging_sessions(samples, gap_minutes=gap_minutes)

    total_minutes = sum(session.duration_min for session in sessions)
    total_hours = total_minutes / 60

    total_l_drop = sum(session.l_drop or 0 for session in sessions)
    total_r_drop = sum(session.r_drop or 0 for session in sessions)

    charge_minutes = sum(session.duration_min for session in charging_sessions)
    charge_hours = charge_minutes / 60
    total_case_drain = sum(session.c_drain or 0 for session in charging_sessions)

    return {
        "sessions": sessions,
        "charging_sessions": charging_sessions,
        "charging_intervals": build_charging_intervals(samples),
        "stats": {
            "session_count": len(sessions),
            "total_minutes": total_minutes,
            "total_l_drop": total_l_drop,
            "total_r_drop": total_r_drop,
            "avg_rate_l": (total_l_drop / total_hours) if total_hours > 0 else None,
            "avg_rate_r": (total_r_drop / total_hours) if total_hours > 0 else None,
            "sample_count": len(samples),
            "connected_sample_count": sum(
                1
                for sample in samples
                if sample.cnx and sample.l is not None and sample.r is not None
            ),
            "charging_session_count": len(charging_sessions),
            "total_charge_minutes": charge_minutes,
            "total_case_drain": total_case_drain,
            "avg_case_rate": (
                total_case_drain / charge_hours if charge_hours > 0 else None
            ),
        },
    }
