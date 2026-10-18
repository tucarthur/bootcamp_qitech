from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil, floor
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


def average_window_thresholds(
    timestamps: list[datetime],
    window: timedelta,
    minimum_windows: int,
    fixed: tuple[int, int],
    warn_factor: float,
    strong_factor: float,
) -> tuple[int, int, str, float | None]:
    window_seconds = window.total_seconds()
    window_counts: dict[int, int] = {}
    for timestamp in timestamps:
        window_index = floor(timestamp.timestamp() / window_seconds)
        window_counts[window_index] = window_counts.get(window_index, 0) + 1

    if len(window_counts) < minimum_windows:
        return fixed[0], fixed[1], "fixed", None

    average_count = sum(window_counts.values()) / len(window_counts)
    return (
        max(fixed[0], ceil(warn_factor * average_count)),
        max(fixed[1], ceil(strong_factor * average_count)),
        "history_average",
        average_count,
    )
