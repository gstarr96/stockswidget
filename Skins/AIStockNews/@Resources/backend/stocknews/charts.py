"""Turns price series into compact, normalized points for the skin to draw."""

from __future__ import annotations

from collections.abc import Sequence


def downsample(values: Sequence[float], max_points: int) -> list[float]:
    """Evenly spaced subset of ``values`` that always keeps the first and last point."""
    if max_points < 2 or len(values) <= max_points:
        return list(values)
    step = (len(values) - 1) / (max_points - 1)
    return [values[round(i * step)] for i in range(max_points)]


def normalize(
    values: Sequence[float], *, max_points: int, baseline: float | None = None
) -> tuple[list[float], float | None]:
    """Scale values into 0..1 (0 = lowest, 1 = highest).

    The baseline (usually the previous close) is scaled the same way, or None
    when it falls outside the day's range so the skin can skip drawing it.
    """
    points = downsample(values, max_points)
    if not points:
        return [], None

    low, high = min(points), max(points)
    span = high - low
    if span == 0:
        return [0.5] * len(points), 0.5 if baseline == low else None

    scaled = [round((v - low) / span, 4) for v in points]
    scaled_baseline = None
    if baseline is not None and low <= baseline <= high:
        scaled_baseline = round((baseline - low) / span, 4)
    return scaled, scaled_baseline
