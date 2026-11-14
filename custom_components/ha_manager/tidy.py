"""Tidy up: find clutter worth clearing out, and say what can be done with it.

Pure Python: no Home Assistant imports, so it can be tested on its own.

Every suggestion is one "candidate" with a key such as `entity:sensor.x`,
`device:<id>`, `automation:automation.x` or `script:script.x`, and says which of
Disable, Ignore and Remove are possible, and why not when they are not.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import json
import re
from typing import Any

from .analysis import blast_radius
from .const import DOMAIN, SAFETY_DEVICE_CLASSES, SAFETY_LABEL_ID, TIDY_OFFLINE_DAYS, ZOMBIE_DAYS
from .models import Consumer, EntityInfo, Snapshot

# Sections, in the order they are shown.
BROKEN = "broken"
DUPLICATE = "duplicate"
LEFTOVER = "leftover"
OFFLINE = "offline"
UNUSED = "unused"
GROUPS = (BROKEN, DUPLICATE, LEFTOVER, OFFLINE, UNUSED)

# Settings that do not change what an automation or script does.
_COSMETIC_KEYS = {"id", "alias", "description", "icon", "fields", "mode", "max", "max_exceeded"}
_NUMBERED = re.compile(r"^(.+?)_(\d{1,2})$")


def _days(delta: timedelta) -> int:
    return max(0, int(delta.total_seconds() // 86400))


def _plural(count: int, word: str) -> str:
    return f"{count} {word if count == 1 else word + 's'}"


def track_unavailable(record: dict[str, str], snapshot: Snapshot) -> None:
    """Remember when each entity was first seen unavailable.

    Home Assistant forgets this on every restart, so HA Manager keeps its own
    note. `record` is {entity_id: ISO time} and is updated in place; the result
    is also put on the snapshot.
    """
    now_iso = snapshot.now.isoformat()
    current: set[str] = set()
    for entity in snapshot.entities.values():
        if not entity.unavailable or entity.disabled:
            continue
        current.add(entity.entity_id)
        start = snapshot.now
        if entity.last_changed and entity.last_changed < start:
            start = entity.last_changed
        saved = _parse(record.get(entity.entity_id))
        if saved is None or start < saved:
            record[entity.entity_id] = start.isoformat() if start != snapshot.now else now_iso
    for entity_id in [e for e in record if e not in current]:
        del record[entity_id]
    snapshot.unavailable_since = {
        entity_id: parsed for entity_id, value in record.items() if (parsed := _parse(value))
    }


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def config_fingerprint(config: dict[str, Any] | None) -> str | None:
    """A short hash of what an automation or script actually does."""
    if not isinstance(config, dict):
        return None
    working = {k: v for k, v in config.items() if k not in _COSMETIC_KEYS}
    # The two spellings Home Assistant accepts mean the same thing.
    for old, new in (("trigger", "triggers"), ("condition", "conditions"), ("action", "actions")):
        if old in working and new not in working:
            working[new] = working.pop(old)
    if not working.get("actions") and not working.get("sequence"):
        return None  # an empty one is not worth matching
    text = json.dumps(working, sort_keys=True, default=str)
    return hashlib.sha1(text.encode()).hexdigest()[:16]  # noqa: S324 - not security


class Tidy:
    """Works out the tidy-up list for one snapshot."""

    def __init__(self, snapshot: Snapshot, ignored: set[str] | None = None) -> None:
        self.snap = snapshot
        self.ignored = ignored or set()
        self.items: dict[str, dict[str, Any]] = {}
        self.sets: list[dict[str, Any]] = []
        self._consumers = {c.id: c for c in snapshot.consumers if c.kind in ("automation", "script")}
        self._safety_devices: set[str] = set()
        self._safety_entities: set[str] = set()
        for entity in snapshot.entities.values():
            if (
                entity.domain == "binary_sensor" and entity.device_class in SAFETY_DEVICE_CLASSES
            ) or SAFETY_LABEL_ID in entity.labels:
                self._safety_entities.add(entity.entity_id)
                if entity.device_id:
                    self._safety_devices.add(entity.device_id)

    # ----- building candidates -------------------------------------------

    def _area(self, area_id: str | None) -> str | None:
        return self.snap.areas.get(area_id) if area_id else None

    def _base(self, key: str) -> dict[str, Any] | None:
        """Describe one thing, with what can be done to it."""
        kind, _, ref = key.partition(":")
        snap = self.snap
        item: dict[str, Any] = {
            "key": key, "type": kind, "id": ref, "reasons": [], "group": None,
            "can_disable": False, "disable_note": "", "can_remove": False,
            "remove_note": "", "undoable_remove": False, "link": None,
        }
        if kind == "device":
            device = snap.devices.get(ref)
            if device is None:
                return None
            item.update(name=device.name, area=self._area(device.area_id),
                        link=f"/config/devices/device/{ref}")
            if device.disabled:
                item["disable_note"] = "Already disabled"
            else:
                item["can_disable"] = True
            item["remove_note"] = (
                "Devices are not removed from here, because Home Assistant has no way to "
                "put one back. Disable it instead, or delete it from its device page."
            )
            return item

        entity = snap.entities.get(ref)
        consumer = self._consumers.get(ref)
        if entity is None and consumer is None:
            return None
        item["name"] = (consumer.name if consumer else None) or (entity.name if entity else ref)
        item["area"] = self._area(entity.area_id) if entity else None

        if kind == "automation" and consumer is not None:
            item["link"] = consumer.edit_url
            if consumer.state == "on":
                item["can_disable"] = True
                item["disable_note"] = "Switches it off, like the toggle in Home Assistant."
            elif consumer.state == "off":
                item["disable_note"] = "Already switched off"
            else:
                item["disable_note"] = "It is broken, so there is nothing to switch off"
        elif kind == "script" and consumer is not None:
            item["link"] = consumer.edit_url
            if entity is not None and entity.in_registry and not entity.disabled:
                item["can_disable"] = True
            else:
                item["disable_note"] = "Scripts without an id cannot be disabled"
        if kind in ("automation", "script"):
            if consumer is not None and consumer.managed:
                item["can_remove"] = True
                item["undoable_remove"] = True
                item["remove_note"] = "A copy is kept in the Log, so it can be put back."
            else:
                item["remove_note"] = (
                    "It is written by hand in a YAML file rather than made in the editor, "
                    "so it has to be removed from that file."
                )
            return item

        # A plain entity.
        assert entity is not None
        item["link"] = (
            f"/config/devices/device/{entity.device_id}" if entity.device_id else "/config/entities"
        )
        if entity.disabled:
            item["disable_note"] = "Already disabled"
        elif not entity.in_registry:
            item["disable_note"] = "It has no unique id, so Home Assistant cannot disable it"
        else:
            item["can_disable"] = True
        if entity.orphaned:
            item["can_remove"] = True
            item["undoable_remove"] = True
            item["remove_note"] = "Nothing provides it any more. A copy is kept in the Log, so it can be put back."
        else:
            item["remove_note"] = (
                "Its integration still provides it, so it would just come back. "
                "Disable it instead."
            )
        return item

    def _add(self, key: str, group: str, reason: str, **extra: Any) -> dict[str, Any] | None:
        item = self.items.get(key)
        if item is None:
            item = self._base(key)
            if item is None:
                return None
            self.items[key] = item
        item.setdefault("_groups", set()).add(group)
        if item["group"] is None or GROUPS.index(group) < GROUPS.index(item["group"]):
            item["group"] = group
        if reason not in item["reasons"]:
            item["reasons"].append(reason)
        item.update(extra)
        return item

    def _key_for(self, entity_id: str) -> str:
        domain = entity_id.split(".", 1)[0]
        if domain in ("automation", "script") and entity_id in self._consumers:
            return f"{domain}:{entity_id}"
        return f"entity:{entity_id}"

    # ----- the checks ----------------------------------------------------

    def run(self) -> dict[str, Any]:
        self._broken()
        self._duplicates()
        self._leftovers()
        self._offline()
        self._unused()
        for item in self.items.values():
            usage = self.usage(item)
            item["used_by"] = len(usage["used_by"])
            item["used_by_names"] = [u["name"] for u in usage["used_by"][:3]]
        active = {k: v for k, v in self.items.items() if k not in self.ignored}
        sets = []
        for dup in self.sets:
            dup["ignored"] = dup["key"] in self.ignored or all(k in self.ignored for k in dup["keys"])
            sets.append(dup)
        groups: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUPS}
        in_sets = {k for s in sets if not s["ignored"] for k in s["keys"]}
        for item in sorted(active.values(), key=lambda i: i["name"].lower()):
            if item["key"] in in_sets:
                continue  # shown inside its duplicate set
            others = [g for g in GROUPS if g != DUPLICATE and g in item["_groups"]]
            if not others:
                continue  # only a duplicate, and that set has been ignored
            groups[others[0]].append(item)
        ignored = [
            v for k, v in sorted(self.items.items(), key=lambda p: p[1]["name"].lower())
            if k in self.ignored and k not in in_sets
        ]
        counts = {g: len(groups[g]) for g in GROUPS}
        counts[DUPLICATE] = sum(1 for s in sets if not s["ignored"])
        for item in self.items.values():
            item.pop("_groups", None)
        return {
            "groups": groups,
            "duplicates": [s for s in sets if not s["ignored"]],
            "items": {k: v for k, v in self.items.items()},
            "ignored": ignored,
            "ignored_sets": [s for s in sets if s["ignored"]],
            "counts": counts,
            "total": sum(counts.values()),
            "offline_days": TIDY_OFFLINE_DAYS,
            "unused_days": ZOMBIE_DAYS,
        }

    def _broken(self) -> None:
        for consumer in self._consumers.values():
            if consumer.state == "unavailable":
                self._add(
                    f"{consumer.kind}:{consumer.id}", BROKEN,
                    "Home Assistant could not load it, so it cannot run",
                )

    def _duplicates(self) -> None:
        # Automations and scripts that do exactly the same thing.
        by_print: dict[tuple[str, str], list[Consumer]] = defaultdict(list)
        for consumer in self._consumers.values():
            if (fingerprint := config_fingerprint(consumer.config)) is not None:
                by_print[(consumer.kind, fingerprint)].append(consumer)
        matched: set[str] = set()
        for (kind, _), members in sorted(by_print.items()):
            if len(members) < 2:
                continue
            matched.update(m.id for m in members)
            self._dup_set(
                f"{_plural(len(members), kind)} with exactly the same settings",
                "They do the same job. Keep one and remove the rest.",
                [(f"{kind}:{m.id}", m) for m in members],
            )
        # Automations and scripts that share a name but are not identical.
        by_name: dict[tuple[str, str], list[Consumer]] = defaultdict(list)
        for consumer in self._consumers.values():
            by_name[(consumer.kind, " ".join(consumer.name.lower().split()))].append(consumer)
        for (kind, _), members in sorted(by_name.items()):
            if len(members) < 2 or all(m.id in matched for m in members):
                continue
            self._dup_set(
                f"{_plural(len(members), kind)} called '{members[0].name}'",
                "Same name, different settings. Often an old copy someone forgot to delete. "
                "Use 'What does this do?' on the Automations tab to compare them.",
                [(f"{kind}:{m.id}", m) for m in members],
            )
        self._duplicate_entities()

    def _consumer_score(self, consumer: Consumer) -> tuple[int, float]:
        """Higher is more worth keeping."""
        working = consumer.state in ("on", "off") and consumer.state != "unavailable"
        ran = consumer.last_triggered.timestamp() if consumer.last_triggered else 0.0
        return (1 if working else 0, ran)

    def _dup_set(self, title: str, advice: str, members: list[tuple[str, Any]]) -> None:
        keep_key: str | None = None
        if members and isinstance(members[0][1], Consumer):
            keep_key = max(members, key=lambda pair: self._consumer_score(pair[1]))[0]
        else:
            alive = [k for k, e in members if not e.unavailable and not e.orphaned]
            if len(alive) == 1:
                keep_key = alive[0]
        keys: list[str] = []
        for key, thing in members:
            note = ""
            if isinstance(thing, Consumer):
                note = (
                    "broken" if thing.state == "unavailable"
                    else f"last ran {thing.last_triggered.date().isoformat()}" if thing.last_triggered
                    else "never run"
                )
                if thing.state == "off":
                    note += ", switched off"
            else:
                note = "left over" if thing.orphaned else "unavailable" if thing.unavailable else "working"
                if thing.platform:
                    note += f", from {thing.platform}"
            item = self._add(key, DUPLICATE, title, dup_note=note,
                             suggest="keep" if key == keep_key else ("remove" if keep_key else None))
            if item is not None:
                keys.append(key)
        if len(keys) >= 2:
            self.sets.append(
                {"key": "dup:" + "|".join(sorted(keys)), "title": title, "advice": advice, "keys": keys}
            )

    def _duplicate_entities(self) -> None:
        """Entities that look like the same thing added twice, e.g. light.x and light.x_2."""
        entities = self.snap.entities
        seen: set[frozenset[str]] = set()
        for entity in entities.values():
            if entity.disabled or entity.domain in ("automation", "script", "scene"):
                continue
            object_id = entity.entity_id.split(".", 1)[1]
            match = _NUMBERED.match(object_id)
            if not match:
                continue
            original = entities.get(f"{entity.domain}.{match.group(1)}")
            if original is None or original.disabled:
                continue
            same_name = _plain(original.name) == _plain(entity.name)
            different_source = (original.platform or "") != (entity.platform or "")
            one_dead = any(e.unavailable or e.orphaned for e in (original, entity))
            if not same_name or not (different_source or one_dead):
                continue
            pair = frozenset((original.entity_id, entity.entity_id))
            if pair in seen:
                continue
            seen.add(pair)
            why = (
                "from two different integrations" if different_source
                else "and one of them is not working"
            )
            self._dup_set(
                f"'{original.name}' looks like it was added twice",
                f"Two entities with the same name, {why}. This usually happens when a device or "
                "integration is set up again and the old copy is left behind.",
                [(f"entity:{e.entity_id}", e) for e in (original, entity)],
            )

    def _leftovers(self) -> None:
        orphan_devices = {
            d.device_id for d in self.snap.devices.values() if d.orphaned
        }
        for device_id in orphan_devices:
            self._add(f"device:{device_id}", LEFTOVER,
                      "Its integration has been removed, so nothing provides it any more")
        for entity in self.snap.entities.values():
            if not entity.orphaned or entity.platform == DOMAIN:
                continue
            where = f"'{entity.platform}'" if entity.platform else "an integration"
            self._add(f"entity:{entity.entity_id}", LEFTOVER,
                      f"Left behind by {where}, which no longer provides it")

    def _offline(self) -> None:
        cutoff = self.snap.now - timedelta(days=TIDY_OFFLINE_DAYS)
        since = self.snap.unavailable_since

        def long_gone(entity: EntityInfo) -> datetime | None:
            start = since.get(entity.entity_id)
            return start if start is not None and start <= cutoff else None

        by_device: dict[str, list[EntityInfo]] = defaultdict(list)
        for entity in self.snap.entities.values():
            if entity.device_id:
                by_device[entity.device_id].append(entity)
        whole_devices: set[str] = set()
        for device_id, entities in by_device.items():
            device = self.snap.devices.get(device_id)
            if device is None or device.disabled or device.orphaned or device_id in self._safety_devices:
                continue
            live = [e for e in entities if not e.disabled and not e.orphaned and e.state is not None]
            if not live or not all(e.unavailable for e in live):
                continue
            starts = [long_gone(e) for e in live]
            if any(s is None for s in starts):
                continue
            whole_devices.add(device_id)
            days = _days(self.snap.now - max(s for s in starts if s))
            self._add(f"device:{device_id}", OFFLINE,
                      f"Offline for at least {_plural(days, 'day')}")
        for entity in self.snap.entities.values():
            if (
                entity.disabled or entity.orphaned or not entity.unavailable
                or entity.device_id in whole_devices
                or entity.entity_id in self._safety_entities
                or entity.device_id in self._safety_devices
                or entity.domain in ("automation", "script")
                or entity.platform == DOMAIN
            ):
                continue
            start = long_gone(entity)
            if start is None:
                continue
            days = _days(self.snap.now - start)
            reason = f"Unavailable for at least {_plural(days, 'day')}"
            if entity.device_id:
                reason += ", although the rest of its device works. Often a feature the device does not really have"
            self._add(f"entity:{entity.entity_id}", OFFLINE, reason)

    def _unused(self) -> None:
        cutoff = self.snap.now - timedelta(days=ZOMBIE_DAYS)
        called: set[str] = set()
        for consumer in self.snap.consumers:
            called |= {e for e in consumer.all_entities if e.startswith("script.") and e != consumer.id}
        for consumer in self._consumers.values():
            if consumer.state == "unavailable":
                continue
            stale = consumer.last_triggered is None or consumer.last_triggered < cutoff
            if not stale:
                continue
            when = (
                f"has not run since {consumer.last_triggered.date().isoformat()}"
                if consumer.last_triggered else "has no record of ever running"
            )
            if consumer.kind == "automation" and consumer.state == "off":
                self._add(f"automation:{consumer.id}", UNUSED, f"Switched off, and {when}")
            elif consumer.kind == "script" and consumer.id not in called:
                self._add(f"script:{consumer.id}", UNUSED, f"Nothing calls it, and it {when}")

    # ----- the "is it used anywhere?" check --------------------------------

    def usage(self, item: dict[str, Any]) -> dict[str, Any]:
        """Everything that uses this thing, from the blast radius check."""
        target_type = "device" if item["type"] == "device" else "entity"
        return blast_radius(self.snap, target_type, item["id"])


def _plain(name: str) -> str:
    """Lower case, without a trailing number, for comparing names."""
    return re.sub(r"[\s_]+\d{1,2}$", "", " ".join(name.lower().split()))


def tidy(snapshot: Snapshot, ignored: set[str] | None = None) -> dict[str, Any]:
    """The full tidy-up list as plain data."""
    return Tidy(snapshot, ignored).run()


def describe(snapshot: Snapshot, key: str) -> dict[str, Any] | None:
    """One thing, with what can be done to it, even if it is not on the list."""
    return Tidy(snapshot)._base(key)  # noqa: SLF001


def usage(snapshot: Snapshot, key: str) -> dict[str, Any] | None:
    """What uses one thing (the double-check before removing it)."""
    finder = Tidy(snapshot)
    item = finder._base(key)  # noqa: SLF001
    if item is None:
        return None
    return finder.usage(item)
