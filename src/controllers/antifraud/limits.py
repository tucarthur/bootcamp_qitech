from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from statistics import median


@dataclass(frozen=True)
class LearnedLimit:
    value: float
    basis: str
    center: float | None = None
    scale: float | None = None


def robust_center_and_scale(
    samples: list[int | float],
    mad_factor: float,
    floor_ratio: float,
) -> tuple[float, float]:
    center = float(median(samples))
    mad = float(median(abs(sample - center) for sample in samples))
    scale = max(mad_factor * mad, floor_ratio * center)
    return center, scale


def resolve_learned_limit(
    samples: list[int | float],
    minimum_samples: int,
    floor: int | float,
    fixed: int | float,
    multiplier: float,
    mad_factor: float,
    floor_ratio: float,
) -> LearnedLimit:
    if len(samples) < minimum_samples:
        return LearnedLimit(value=float(fixed), basis="fixed")

    center, scale = robust_center_and_scale(samples, mad_factor, floor_ratio)
    return LearnedLimit(
        value=max(float(floor), center + multiplier * scale),
        basis="history",
        center=center,
        scale=scale,
    )


def burst_peak(timestamps: list[datetime], window: timedelta) -> int:
    ordered = sorted(timestamps)
    left = 0
    peak = 0
    for right, timestamp in enumerate(ordered):
        while timestamp - ordered[left] >= window:
            left += 1
        peak = max(peak, right - left + 1)
    return peak


def learned_burst_thresholds(
    timestamps: list[datetime],
    minimum_samples: int,
    fixed: tuple[int, int],
    warn_floor: int,
    block_floor: int,
    warn_factor: int,
    block_factor: int,
    window: timedelta,
) -> tuple[int, int, str]:
    if len(timestamps) < minimum_samples:
        return fixed[0], fixed[1], "fixed"

    peak = burst_peak(timestamps, window)
    return (
        max(warn_floor, ceil(warn_factor * peak)),
        max(block_floor, ceil(block_factor * peak)),
        "history",
    )
