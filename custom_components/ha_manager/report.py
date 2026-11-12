"""Write the weekly report in plain English.

Pure Python: no Home Assistant imports.
"""

from __future__ import annotations

from typing import Any


def summarise(result: dict[str, Any]) -> dict[str, Any]:
    """The small part of a scan worth keeping to compare against next week."""
    return {
        "when": result["generated"],
        "score": result["score"]["value"],
        "grade": result["score"]["grade"],
        "counts": dict(result["score"]["counts"]),
        "findings": {f["id"]: f["title"] for f in result["findings"] if f["counts"]},
    }


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def build_report(result: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """Compare this scan with last week's and describe what changed."""
    now = summarise(result)
    score = now["score"]
    counts = now["counts"]
    lines: list[str] = []

    if previous is None:
        headline = f"Health score {score} out of 100 ({now['grade']})."
        lines.append("This is the first report, so there is nothing to compare with yet.")
        new: list[str] = []
        fixed: list[str] = []
    else:
        change = score - previous["score"]
        direction = (
            f"up {change}" if change > 0 else f"down {-change}" if change < 0 else "no change"
        )
        headline = f"Health score {score} out of 100 ({now['grade']}), {direction} on last week."
        new = [t for i, t in now["findings"].items() if i not in previous["findings"]]
        fixed = [t for i, t in previous["findings"].items() if i not in now["findings"]]
        lines.append(f"{_plural(len(new), 'new problem')}, {len(fixed)} fixed.")

    lines.append(
        f"Right now: {counts['critical']} critical, {counts['warning']} warning, "
        f"{counts['tidy']} tidy-up."
    )

    critical = [f["title"] for f in result["findings"] if f["severity"] == "critical" and f["counts"]]
    if critical:
        lines.append("Fix first:")
        lines += [f"- {title}" for title in critical[:5]]
        if len(critical) > 5:
            lines.append(f"- and {len(critical) - 5} more")
    if new:
        lines.append("New this week:")
        lines += [f"- {title}" for title in new[:5]]
        if len(new) > 5:
            lines.append(f"- and {len(new) - 5} more")
    if fixed:
        lines.append("Sorted since last week:")
        lines += [f"- {title}" for title in fixed[:5]]
        if len(fixed) > 5:
            lines.append(f"- and {len(fixed) - 5} more")

    soon = [
        b for b in result.get("batteries", [])
        if b.get("status") == "forecast" and b["days_left"] <= 30
    ]
    if soon:
        lines.append("Batteries to buy:")
        lines += [
            f"- {b['name']}: about {_plural(b['days_left'], 'day')} left ({b['level']:.0f}%)"
            for b in soon[:8]
        ]

    due = [
        u["name"] for u in result["safety"]["units"]
        if not u["excluded"] and any("est" in p for p in u["problems"])
    ]
    if due:
        lines.append(f"Life-safety tests due: {', '.join(due[:8])}.")

    if not critical and not new and not soon and not due:
        lines.append("Nothing needs you this week.")

    return {
        "title": f"HA Manager weekly report: {score}/100",
        "headline": headline,
        "lines": lines,
        "text": "\n".join([headline, *lines]),
        "summary": now,
    }
