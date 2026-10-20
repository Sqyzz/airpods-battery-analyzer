def _state(sample):
    return (
        sample.l,
        sample.r,
        sample.c,
        sample.l_charging,
        sample.r_charging,
        sample.c_charging,
        sample.cnx,
    )


def compress_samples(samples, heartbeat_seconds: float = 300):
    """Collapse consecutive samples that do not change any observed state.

    A heartbeat sample is kept every ``heartbeat_seconds`` so long flat
    periods (for example an earbud sitting at 100% in its case) still have
    a visible trace without storing every broadcast.
    """
    ordered = sorted(samples, key=lambda sample: sample.ts)

    kept = []
    last_ts = None
    last_state = None

    for sample in ordered:
        state = _state(sample)
        elapsed = (
            (sample.ts - last_ts).total_seconds() if last_ts is not None else None
        )
        if (
            last_state is None
            or state != last_state
            or elapsed >= heartbeat_seconds
        ):
            kept.append(sample)
            last_ts = sample.ts
            last_state = state

    return kept
