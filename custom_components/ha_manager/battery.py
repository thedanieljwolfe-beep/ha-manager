"""Work out when batteries will run flat.

Pure Python: no Home Assistant imports.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# A jump up of this many points means the battery was replaced or charged.
REPLACED_JUMP = 15
MIN_POINTS = 3
MIN_DAYS = 5
GOOD_POINTS = 7
GOOD_DAYS = 21
# Slower than this (percent per day) counts as "not dropping".
STEADY_RATE = 0.02


def forecast(points: list[tuple[datetime, float]], now: datetime) -> dict[str, Any]:
    """Estimate days left from a history of (time, percent) readings.

    Fits a straight line through the readings since the battery was last
    replaced. Batteries do not really drain in a straight line, so treat the
    answer as a guide, not a promise.
    """
    points = sorted(points)
    if not points:
        return {"status": "learning", "level": None, "days_of_data": 0}

    start = 0
    for index in range(1, len(points)):
        if points[index][1] - points[index - 1][1] >= REPLACED_JUMP:
            start = index
    segment = points[start:]
    level = segment[-1][1]
    span_days = (segment[-1][0] - segment[0][0]).total_seconds() / 86400
    result: dict[str, Any] = {
        "level": level,
        "days_of_data": round(span_days),
        "replaced": points[start][0].date().isoformat() if start else None,
    }
    if len(segment) < MIN_POINTS or span_days < MIN_DAYS:
        return {**result, "status": "learning"}

    # Least-squares straight line: percent against days.
    xs = [(when - segment[0][0]).total_seconds() / 86400 for when, _ in segment]
    ys = [value for _, value in segment]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread
    drain = -slope  # percent lost per day
    if drain < STEADY_RATE:
        return {**result, "status": "steady", "rate_per_day": 0.0}

    days_left = max(0, round(level / drain))
    return {
        **result,
        "status": "forecast",
        "rate_per_day": round(drain, 2),
        "days_left": days_left,
        "empty_on": (now + timedelta(days=days_left)).date().isoformat(),
        "confidence": "good"
        if len(segment) >= GOOD_POINTS and span_days >= GOOD_DAYS
        else "rough",
    }
