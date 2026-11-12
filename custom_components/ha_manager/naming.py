"""Check that devices and helpers have clear, consistent names.

Pure Python: no Home Assistant imports. Only friendly names are ever
suggested. Entity IDs are left alone, because automations refer to those.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from .const import STYLE_NO_ROOM, STYLE_ROOM_FIRST
from .models import Snapshot

# Standalone entities worth checking (things people see and say out loud).
NAMED_DOMAINS = {
    "light", "switch", "fan", "cover", "climate", "lock", "media_player",
    "vacuum", "input_boolean", "input_number", "input_select", "input_text",
    "input_datetime", "input_button", "timer", "counter", "group",
}

_HEX_RE = re.compile(r"\b(0x)?[0-9a-f]{8,}\b", re.IGNORECASE)
_MAC_RE = re.compile(r"\b([0-9a-f]{2}[:-]){3,}[0-9a-f]{2}\b", re.IGNORECASE)
_MODEL_RE = re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]{2,}[-_]?[A-Z0-9]{3,}\b")
_SMALL_WORDS = {"a", "an", "and", "at", "for", "in", "of", "on", "or", "the", "to"}
_KEEP_UPPER = {"tv", "led", "pir", "usb", "ups", "nas", "pc", "ac", "co", "co2", "hvac"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _starts_with(name: str, prefix: str) -> bool:
    """True when `name` begins with the whole words of `prefix`."""
    n, p = _norm(name), _norm(prefix)
    return bool(p) and (n == p or n.startswith(p + " "))


def _strip_prefix(name: str, prefix: str) -> str:
    words = len(prefix.split())
    rest = " ".join(name.split()[words:])
    return rest.lstrip(" -·:,").strip()


def is_technical(name: str) -> bool:
    """True when a name looks like a factory default rather than plain English."""
    if "_" in name or _HEX_RE.search(name) or _MAC_RE.search(name):
        return True
    if _MODEL_RE.search(name):
        return True
    return name == name.lower() and any(ch.isdigit() for ch in name) and " " not in name


def tidy(name: str) -> str:
    """Make a best guess at a readable version of a technical name."""
    text = _MAC_RE.sub(" ", name)
    text = re.sub(r"[_.]+", " ", text)
    text = _HEX_RE.sub(" ", text)
    text = _MODEL_RE.sub(" ", text)
    words = [w for w in re.sub(r"\s+", " ", text).strip(" -·:,").split(" ") if w]
    result = []
    for index, word in enumerate(words):
        lower = word.lower()
        if lower in _KEEP_UPPER:
            result.append(lower.upper())
        elif index and lower in _SMALL_WORDS:
            result.append(lower)
        elif word.islower() or word.isupper():
            result.append(word.capitalize())
        else:
            result.append(word)
    return " ".join(result)


def check_names(snapshot: Snapshot, style: str = STYLE_ROOM_FIRST) -> list[dict[str, Any]]:
    """Return every name that could be clearer, with a suggestion where possible."""
    subjects: list[dict[str, Any]] = []
    for device in snapshot.devices.values():
        if device.disabled or device.is_service or device.orphaned:
            continue
        subjects.append(
            {"type": "device", "id": device.device_id, "name": device.name, "area_id": device.area_id}
        )
    for entity in snapshot.entities.values():
        if (
            entity.device_id
            or not entity.in_registry
            or entity.disabled
            or entity.hidden
            or entity.orphaned
            or entity.domain not in NAMED_DOMAINS
        ):
            continue
        subjects.append(
            {"type": "entity", "id": entity.entity_id, "name": entity.name, "area_id": entity.area_id}
        )

    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for subject in subjects:
        by_name[_norm(subject["name"])].append(subject)

    # Longest room names first, so "Kitchen Diner" wins over "Kitchen".
    rooms = sorted(snapshot.areas.items(), key=lambda pair: len(pair[1]), reverse=True)

    issues: list[dict[str, Any]] = []
    for subject in subjects:
        name: str = subject["name"]
        area_id = subject["area_id"]
        area = snapshot.areas.get(area_id) if area_id else None
        named_room = next(
            ((rid, rname) for rid, rname in rooms if _starts_with(name, rname)), None
        )
        problem = reason = None
        suggestion: str | None = None

        if is_technical(name):
            problem = "technical"
            reason = "Looks like a factory or technical name."
            cleaned = tidy(name)
            if cleaned and _norm(cleaned) != _norm(name):
                suggestion = cleaned
                if style == STYLE_ROOM_FIRST and area and not _starts_with(cleaned, area):
                    suggestion = f"{area} {cleaned}"
        elif named_room and area_id and named_room[0] != area_id:
            problem = "wrong_room"
            reason = f"Named after {named_room[1]} but it is in {area}."
            rest = _strip_prefix(name, named_room[1])
            if rest:
                suggestion = f"{area} {rest}" if style == STYLE_ROOM_FIRST else rest
        elif len(by_name[_norm(name)]) > 1:
            problem = "duplicate"
            others = len(by_name[_norm(name)]) - 1
            reason = f"{others} other thing{'s' if others > 1 else ''} share{'' if others > 1 else 's'} this exact name."
            if style == STYLE_ROOM_FIRST and area and not _starts_with(name, area):
                candidate = f"{area} {name}"
                if _norm(candidate) not in by_name:
                    suggestion = candidate
        elif style == STYLE_ROOM_FIRST and area and not _starts_with(name, area):
            problem = "no_room"
            reason = f"Does not start with its room, {area}."
            suggestion = f"{area} {name}"
        elif style == STYLE_NO_ROOM and area and _starts_with(name, area):
            rest = _strip_prefix(name, area)
            if rest:
                problem = "has_room"
                reason = f"Repeats its room, {area}, in the name."
                suggestion = rest

        if problem is None:
            continue
        if suggestion and _norm(suggestion) == _norm(name):
            suggestion = None
        issues.append(
            {
                "type": subject["type"],
                "id": subject["id"],
                "name": name,
                "area": area,
                "problem": problem,
                "reason": reason,
                "suggestion": suggestion,
            }
        )

    order = {"wrong_room": 0, "duplicate": 1, "technical": 2, "no_room": 3, "has_room": 3}
    issues.sort(key=lambda i: (order[i["problem"]], (i["area"] or "~").lower(), i["name"].lower()))
    return issues
