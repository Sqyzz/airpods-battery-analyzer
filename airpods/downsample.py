from dataclasses import dataclass
from typing import Optional


@dataclass
class Downsampled:
    samples: list
    applied: bool
    original_points: int
    returned_points: int
    bucket_seconds: Optional[float] = None


def downsample_samples(samples, max_points: int = 2000) -> Downsampled:
    """Reduce chart series to at most ``max_points`` points.

    Samples are grouped into equal time buckets and the last sample in each
    bucket is kept. The first and last samples are always preserved so the
    chart's endpoints stay accurate. Session statistics should be computed
    on the original samples, not on this downsampled view.
    """
    if max_points <= 0:
        raise ValueError("max_points 必须大于 0")

    ordered = sorted(samples, key=lambda sample: sample.ts)
    total = len(ordered)
    if total <= max_points:
        return Downsampled(
            samples=ordered,
            applied=False,
            original_points=total,
            returned_points=total,
        )

    first_ts = ordered[0].ts
    last_ts = ordered[-1].ts
    span_seconds = (last_ts - first_ts).total_seconds()

    if span_seconds <= 0:
        kept = ordered[:max_points]
        return Downsampled(
            samples=kept,
            applied=True,
            original_points=total,
            returned_points=len(kept),
        )

    bucket_seconds = span_seconds / max(1, max_points - 1)
    buckets = {}
    for sample in ordered:
        bucket = int((sample.ts - first_ts).total_seconds() / bucket_seconds)
        buckets[bucket] = sample

    kept = [ordered[0]] + [
        sample
        for _, sample in sorted(buckets.items())
        if sample is not ordered[0]
    ]

    if kept[-1] is not ordered[-1]:
        kept[-1] = ordered[-1]
    if len(kept) > max_points:
        kept = kept[: max_points - 1] + [ordered[-1]]

    return Downsampled(
        samples=kept,
        applied=True,
        original_points=total,
        returned_points=len(kept),
        bucket_seconds=bucket_seconds,
    )
