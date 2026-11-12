"""Turn a snapshot of the house into a health score and a list of findings.

Pure Python: no Home Assistant imports, so it can be tested on its own.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from .const import (
    BACKUP_MAX_AGE_DAYS,
    BATTERY_LOW,
    CRITICAL,
    CROSS_CHECK_DOMAINS,
    FLAPPING_TRIGGERS_PER_DAY,
    SAFETY_BATTERY_CRITICAL,
    SAFETY_BATTERY_LOW,
    SAFETY_DEVICE_CLASSES,
    SAFETY_LABEL_ID,
    SAFETY_TEST_INTERVAL_DAYS,
    SCORE_CAPS,
    SCORE_WEIGHTS,
    SEVERITIES,
    STYLE_ROOM_FIRST,
    TIDY,
    WARNING,
    ZOMBIE_DAYS,
)
from .models import Consumer, EntityInfo, Finding, Snapshot
from .naming import NAMED_DOMAINS, check_names

KIND_NAMES = {
    "automation": "automation",
    "script": "script",
    "scene": "scene",
    "group": "group",
    "dashboard": "dashboard",
}


def _plural(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else (plural or word + 's')}"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _number(state: str | None) -> float | None:
    try:
        return float(state)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class Analyser:
    """Runs every check over one snapshot."""

    def __init__(self, snapshot: Snapshot, store: dict[str, Any] | None = None) -> None:
        self.snap = snapshot
        store = store or {}
        self.tests: dict[str, list[str]] = store.get("safety_tests", {})
        self.excluded: set[str] = set(store.get("safety_excluded", []))
        self.ignored: set[str] = set(store.get("ignored", []))
        self.naming_style: str = store.get("naming_style", STYLE_ROOM_FIRST)
        self.findings: list[Finding] = []
        self.safety_units: list[dict[str, Any]] = []
        self._safety_device_ids: set[str] = set()
        self._safety_entity_ids: set[str] = set()

    # ----- helpers -------------------------------------------------------

    def _name(self, entity_id: str) -> str:
        entity = self.snap.entities.get(entity_id)
        return entity.name if entity else entity_id

    def _area(self, area_id: str | None) -> str | None:
        return self.snap.areas.get(area_id) if area_id else None

    def _item(self, entity_id: str, note: str = "") -> dict[str, Any]:
        entity = self.snap.entities.get(entity_id)
        return {
            "entity_id": entity_id,
            "name": entity.name if entity else entity_id,
            "area": self._area(entity.area_id) if entity else None,
            "note": note,
        }

    def _add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def _device_entities(self) -> dict[str, list[EntityInfo]]:
        by_device: dict[str, list[EntityInfo]] = defaultdict(list)
        for entity in self.snap.entities.values():
            if entity.device_id:
                by_device[entity.device_id].append(entity)
        return by_device

    # ----- checks --------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Run all checks and return the full result."""
        by_device = self._device_entities()
        self._check_safety(by_device)
        self._check_consumers()
        self._check_unavailable(by_device)
        self._check_orphans()
        self._check_no_area(by_device)
        self._check_batteries(by_device)
        activity = self._check_activity()
        self._check_repairs()
        self._check_backup()
        self._check_names()

        order = {severity: index for index, severity in enumerate(SEVERITIES)}
        self.findings.sort(key=lambda f: (order[f.severity], f.category, f.title))
        active = [f for f in self.findings if f.id not in self.ignored]
        ignored = [f for f in self.findings if f.id in self.ignored]

        kinds = defaultdict(int)
        for consumer in self.snap.consumers:
            kinds[consumer.kind] += 1

        return {
            "generated": _iso(self.snap.now),
            "score": score(active),
            "findings": [f.as_dict() for f in active],
            "ignored": [f.as_dict() for f in ignored],
            "safety": {
                "units": self.safety_units,
                "test_interval_days": SAFETY_TEST_INTERVAL_DAYS,
            },
            "activity": activity,
            "totals": {
                "entities": len(self.snap.entities),
                "devices": len(self.snap.devices),
                "areas": len(self.snap.areas),
                "automations": kinds["automation"],
                "scripts": kinds["script"],
                "scenes": kinds["scene"],
                "dashboards": kinds["dashboard"],
            },
            "sources": {
                "counting_since": _iso(self.snap.counting_since),
                "watchman": self.snap.watchman is not None,
                "spook": any(r.domain == "spook" for r in self.snap.repairs),
            },
        }

    def _check_safety(self, by_device: dict[str, list[EntityInfo]]) -> None:
        """Smoke, CO, gas and leak sensors get stricter treatment."""
        units: dict[str, list[EntityInfo]] = defaultdict(list)
        for entity in self.snap.entities.values():
            if entity.disabled or entity.orphaned:
                continue
            is_safety = (
                entity.domain == "binary_sensor"
                and entity.device_class in SAFETY_DEVICE_CLASSES
            ) or SAFETY_LABEL_ID in entity.labels
            if is_safety:
                units[entity.device_id or entity.entity_id].append(entity)

        untested: list[dict[str, Any]] = []
        for unit_id, sensors in sorted(units.items()):
            device = self.snap.devices.get(unit_id)
            name = device.name if device else sensors[0].name
            area = self._area(device.area_id if device else sensors[0].area_id)
            excluded = unit_id in self.excluded

            battery: float | None = None
            battery_flag = False
            for sibling in by_device.get(unit_id, []):
                if sibling.device_class != "battery" or sibling.disabled:
                    continue
                if sibling.domain == "sensor":
                    level = _number(sibling.state)
                    if level is not None:
                        battery = level if battery is None else min(battery, level)
                elif sibling.domain == "binary_sensor" and sibling.state == "on":
                    battery_flag = True

            tests = sorted(
                t for t in (_parse(v) for v in self.tests.get(unit_id, [])) if t
            )
            last_test = tests[-1] if tests else None
            test_due = (
                last_test is None
                or self.snap.now - last_test > timedelta(days=SAFETY_TEST_INTERVAL_DAYS)
            )
            seen = [s.last_seen for s in sensors if s.last_seen]
            offline = [s for s in sensors if s.unavailable]
            alarming = [s for s in sensors if s.state == "on"]

            problems: list[str] = []
            status = "ok"
            if not excluded:
                self._safety_entity_ids.update(s.entity_id for s in sensors)
                if device:
                    self._safety_device_ids.add(unit_id)
                where = f" ({area})" if area else ""
                if offline:
                    status = "critical"
                    problems.append("Not responding")
                    self._add(
                        Finding(
                            id=f"safety_offline:{unit_id}",
                            severity=CRITICAL,
                            category="Life safety",
                            title=f"{name}{where} is not responding",
                            detail="Home Assistant cannot reach this life-safety sensor, "
                            "so it would not tell you about an alarm.",
                            advice="Check the battery and that it is still connected. "
                            "The alarm itself may still sound, but do not rely on "
                            "notifications until this is fixed.",
                            items=[self._item(s.entity_id) for s in offline],
                        )
                    )
                if battery is not None and battery <= SAFETY_BATTERY_LOW or battery_flag:
                    is_critical = battery is not None and battery <= SAFETY_BATTERY_CRITICAL
                    level = f"{battery:.0f}%" if battery is not None else "low"
                    problems.append(f"Battery {level}")
                    if status != "critical":
                        status = "critical" if is_critical else "warning"
                    self._add(
                        Finding(
                            id=f"safety_battery:{unit_id}",
                            severity=CRITICAL if is_critical else WARNING,
                            category="Life safety",
                            title=f"{name}{where} battery is {level}",
                            advice="Replace the battery, then press the test button "
                            "and log the test.",
                        )
                    )
                if test_due:
                    problems.append("Test overdue" if last_test else "No test logged")
                    if status == "ok":
                        status = "warning"
                    untested.append(
                        {
                            "name": name,
                            "area": area,
                            "note": f"last tested {last_test.date().isoformat()}"
                            if last_test
                            else "no test logged",
                        }
                    )

            self.safety_units.append(
                {
                    "id": unit_id,
                    "name": name,
                    "area": area,
                    "excluded": excluded,
                    "status": "excluded" if excluded else status,
                    "alarm": bool(alarming),
                    "problems": problems,
                    "battery": battery,
                    "battery_low": battery_flag,
                    "last_seen": _iso(max(seen)) if seen else None,
                    "last_test": _iso(last_test),
                    "test_count": len(tests),
                    "sensors": [
                        {
                            "entity_id": s.entity_id,
                            "name": s.name,
                            "type": SAFETY_DEVICE_CLASSES.get(
                                s.device_class or "", "Safety"
                            ),
                            "state": s.state,
                        }
                        for s in sensors
                    ],
                }
            )

        if untested:
            self._add(
                Finding(
                    id="safety_tests_due",
                    severity=WARNING,
                    category="Life safety",
                    title=f"{_plural(len(untested), 'life-safety device')} "
                    f"{'is' if len(untested) == 1 else 'are'} due a test",
                    detail=f"No test has been logged in the last "
                    f"{SAFETY_TEST_INTERVAL_DAYS} days.",
                    advice="Press the test button on each one, then log it on the "
                    "Life safety tab.",
                    items=untested,
                )
            )

    def _missing(self, consumer: Consumer) -> tuple[list[dict[str, Any]], bool]:
        """Return what a consumer points at that is not there.

        The second value is True when at least one item is a definite problem
        rather than just a mention inside a template.
        """
        snap = self.snap
        items: list[dict[str, Any]] = []
        definite = False

        def known(entity_id: str) -> bool:
            return entity_id in snap.entities or entity_id in snap.services

        for entity_id in sorted(consumer.entities):
            if "." not in entity_id:
                continue
            if not known(entity_id):
                items.append({"entity_id": entity_id, "name": entity_id, "note": "does not exist"})
                definite = True
            elif entity_id in snap.entities and snap.entities[entity_id].disabled:
                items.append(self._item(entity_id, "is disabled"))
                definite = True
        for entity_id in sorted(consumer.scripts_called - consumer.entities):
            if entity_id not in snap.entities:
                items.append({"entity_id": entity_id, "name": entity_id, "note": "script does not exist"})
                definite = True
        for device_id in sorted(consumer.devices):
            if device_id not in snap.devices:
                items.append({"name": f"Device {device_id[:8]}…", "note": "device has been removed"})
                definite = True
        for area_id in sorted(consumer.areas):
            if area_id not in snap.areas:
                items.append({"name": f"Room '{area_id}'", "note": "room does not exist"})
                definite = True
        for entity_id in sorted(consumer.mentioned - consumer.entities):
            if not known(entity_id):
                items.append(
                    {
                        "entity_id": entity_id,
                        "name": entity_id,
                        "note": "mentioned in a template, does not exist",
                    }
                )
        return items, definite

    def _check_consumers(self) -> None:
        """Broken automations and scripts, and references to missing things."""
        for consumer in self.snap.consumers:
            kind = KIND_NAMES[consumer.kind]
            items, definite = self._missing(consumer)
            if consumer.kind in ("automation", "script") and consumer.state == "unavailable":
                self._add(
                    Finding(
                        id=f"broken:{consumer.id}",
                        severity=CRITICAL,
                        category="Broken",
                        title=f"The {kind} '{consumer.name}' is broken and cannot run",
                        detail="Home Assistant could not load it, usually because "
                        "something it relies on was removed or its settings are invalid.",
                        advice=f"Open the {kind} and fix or delete it.",
                        items=items,
                        link=consumer.edit_url,
                    )
                )
                continue
            if not items:
                continue
            count = _plural(len(items), "thing")
            self._add(
                Finding(
                    id=f"missing_ref:{consumer.kind}:{consumer.id}",
                    severity=WARNING if definite else TIDY,
                    category="Broken links",
                    title=f"The {kind} '{consumer.name}' points at {count} "
                    f"that {'is' if len(items) == 1 else 'are'} missing",
                    detail="It will quietly skip or fail on these."
                    if definite
                    else "These were only spotted inside templates, so this may be a false alarm.",
                    advice=f"Open the {kind} and swap in the right entity, or remove the line.",
                    items=items,
                    link=consumer.edit_url,
                )
            )

    def _check_unavailable(self, by_device: dict[str, list[EntityInfo]]) -> None:
        """Devices that have gone offline and entities that are unavailable."""
        handled_domains = {"automation", "script"}
        partial: list[dict[str, Any]] = []
        for device_id, entities in sorted(by_device.items()):
            device = self.snap.devices.get(device_id)
            if device is None or device.disabled or device_id in self._safety_device_ids:
                continue
            live = [
                e
                for e in entities
                if not e.disabled and not e.orphaned and e.state is not None
            ]
            down = [e for e in live if e.unavailable]
            if not down:
                continue
            area = self._area(device.area_id)
            where = f" ({area})" if area else ""
            if len(down) == len(live):
                self._add(
                    Finding(
                        id=f"offline:{device_id}",
                        severity=WARNING,
                        category="Offline",
                        title=f"{device.name}{where} appears to be offline",
                        detail=f"All {_plural(len(live), 'entity', 'entities')} on this "
                        "device are unavailable.",
                        advice="Check it has power or battery and is in range. If you "
                        "no longer own it, delete the device.",
                        items=[self._item(e.entity_id) for e in down[:10]],
                        link=f"/config/devices/device/{device_id}",
                    )
                )
            else:
                partial.extend(self._item(e.entity_id, f"on {device.name}") for e in down)
        if partial:
            self._add(
                Finding(
                    id="unavailable_partial",
                    severity=TIDY,
                    category="Offline",
                    title=f"{_plural(len(partial), 'entity', 'entities')} unavailable "
                    "on devices that otherwise work",
                    detail="Often these are features the device does not really "
                    "support, or that only appear some of the time.",
                    advice="If one never works, disable that entity to cut the noise.",
                    items=partial,
                )
            )

        standalone = [
            e
            for e in self.snap.entities.values()
            if e.unavailable
            and not e.device_id
            and not e.disabled
            and not e.orphaned
            and e.domain not in handled_domains
            and e.entity_id not in self._safety_entity_ids
        ]
        if standalone:
            self._add(
                Finding(
                    id="unavailable_standalone",
                    severity=WARNING,
                    category="Offline",
                    title=f"{_plural(len(standalone), 'helper or standalone entity', 'helpers or standalone entities')} "
                    f"{'is' if len(standalone) == 1 else 'are'} unavailable",
                    detail="These do not belong to a device, so they are usually "
                    "templates, helpers or groups that have stopped working.",
                    advice="Open each one and check what it depends on.",
                    items=[self._item(e.entity_id) for e in sorted(standalone, key=lambda e: e.entity_id)],
                )
            )

    def _check_orphans(self) -> None:
        """Entities left behind by integrations that have been removed."""
        by_platform: dict[str, list[EntityInfo]] = defaultdict(list)
        for entity in self.snap.entities.values():
            if entity.orphaned:
                by_platform[entity.platform or "unknown"].append(entity)
        for platform, entities in sorted(by_platform.items()):
            self._add(
                Finding(
                    id=f"orphans:{platform}",
                    severity=TIDY,
                    category="Leftovers",
                    title=f"{_plural(len(entities), 'leftover entity', 'leftover entities')} "
                    f"from '{platform}'",
                    detail="Nothing provides these any more. They are safe to "
                    "delete once nothing uses them.",
                    advice="Check each one on the Blast radius tab, then delete it "
                    "from Settings > Devices & services > Entities.",
                    items=[self._item(e.entity_id) for e in sorted(entities, key=lambda e: e.entity_id)],
                    link="/config/entities",
                )
            )

    def _check_no_area(self, by_device: dict[str, list[EntityInfo]]) -> None:
        """Devices that have not been put in a room."""
        homeless = [
            device
            for device in self.snap.devices.values()
            if not device.area_id
            and not device.disabled
            and not device.is_service
            and any(not e.disabled for e in by_device.get(device.device_id, []))
        ]
        if homeless:
            self._add(
                Finding(
                    id="no_area",
                    severity=TIDY,
                    category="Rooms",
                    title=f"{_plural(len(homeless), 'device')} "
                    f"{'is' if len(homeless) == 1 else 'are'} not in a room",
                    detail="Room-based voice commands and dashboards will miss these.",
                    advice="Give each one a room from its device page.",
                    items=[
                        {"name": d.name, "device_id": d.device_id}
                        for d in sorted(homeless, key=lambda d: d.name.lower())
                    ],
                    link="/config/devices/dashboard",
                )
            )

    def _check_batteries(self, by_device: dict[str, list[EntityInfo]]) -> None:
        """Low batteries on anything that is not a life-safety device."""
        low: list[tuple[float, dict[str, Any]]] = []
        for entity in self.snap.entities.values():
            if (
                entity.device_class != "battery"
                or entity.disabled
                or entity.orphaned
                or entity.device_id in self._safety_device_ids
            ):
                continue
            device = self.snap.devices.get(entity.device_id or "")
            label = device.name if device else entity.name
            area = self._area(entity.area_id)
            if entity.domain == "sensor":
                level = _number(entity.state)
                if level is not None and level <= BATTERY_LOW:
                    low.append((level, {"entity_id": entity.entity_id, "name": label, "area": area, "note": f"{level:.0f}%"}))
            elif entity.domain == "binary_sensor" and entity.state == "on":
                low.append((0.0, {"entity_id": entity.entity_id, "name": label, "area": area, "note": "reports low"}))
        if low:
            low.sort(key=lambda pair: pair[0])
            self._add(
                Finding(
                    id="battery_low",
                    severity=WARNING,
                    category="Batteries",
                    title=f"{_plural(len(low), 'battery', 'batteries')} running low",
                    detail=f"At or below {BATTERY_LOW}%.",
                    advice="Swap them before the device drops offline.",
                    items=[item for _, item in low],
                )
            )

    def _check_activity(self) -> list[dict[str, Any]]:
        """Flapping and zombie automations and scripts."""
        cutoff = self.snap.now - timedelta(days=ZOMBIE_DAYS)
        used_scripts: set[str] = set()
        for consumer in self.snap.consumers:
            used_scripts |= {e for e in consumer.all_entities if e.startswith("script.") and e != consumer.id}

        rows: list[dict[str, Any]] = []
        zombies: dict[str, list[dict[str, Any]]] = {"automation": [], "script": []}
        for consumer in self.snap.consumers:
            if consumer.kind not in ("automation", "script"):
                continue
            status = "ok"
            note = ""
            if consumer.state == "unavailable":
                status = "broken"
            elif consumer.kind == "automation" and consumer.state == "off":
                status = "off"
            elif (
                consumer.triggers_24h is not None
                and consumer.triggers_24h > FLAPPING_TRIGGERS_PER_DAY
            ):
                status = "flapping"
                self._add(
                    Finding(
                        id=f"flapping:{consumer.id}",
                        severity=WARNING,
                        category="Automations",
                        title=f"The {consumer.kind} '{consumer.name}' fired "
                        f"{consumer.triggers_24h} times in the last 24 hours",
                        detail="That is unusually busy and often means a sensor is "
                        "bouncing or the trigger is too broad.",
                        advice="Add a 'for' duration to the trigger, or a condition, "
                        "so it only fires when it matters.",
                        link=consumer.edit_url,
                    )
                )
            elif consumer.last_triggered is None or consumer.last_triggered < cutoff:
                status = "zombie"
                note = (
                    f"last ran {consumer.last_triggered.date().isoformat()}"
                    if consumer.last_triggered
                    else "no record of it ever running"
                )
                if consumer.kind == "script" and consumer.id not in used_scripts:
                    note += ", and nothing calls it"
                zombies[consumer.kind].append(
                    {"entity_id": consumer.id, "name": consumer.name, "note": note}
                )
            rows.append(
                {
                    "entity_id": consumer.id,
                    "kind": consumer.kind,
                    "name": consumer.name,
                    "status": status,
                    "note": note,
                    "last_triggered": _iso(consumer.last_triggered),
                    "triggers_24h": consumer.triggers_24h,
                    "edit_url": consumer.edit_url,
                }
            )

        for kind, items in zombies.items():
            if not items:
                continue
            self._add(
                Finding(
                    id=f"zombies:{kind}",
                    severity=TIDY,
                    category="Automations",
                    title=f"{_plural(len(items), kind)} "
                    f"{'has' if len(items) == 1 else 'have'} not run in {ZOMBIE_DAYS} days",
                    detail="They may be seasonal, or they may be dead weight. "
                    "Home Assistant forgets the last run time if an automation is "
                    "recreated, so new ones can show up here too.",
                    advice="Delete the ones you no longer need, or ignore this if "
                    "they are meant to be rare.",
                    items=sorted(items, key=lambda i: i["name"].lower()),
                    link=f"/config/{kind}/dashboard",
                )
            )
        order = {"broken": 0, "flapping": 1, "zombie": 2, "off": 3, "ok": 4}
        rows.sort(key=lambda r: (order[r["status"]], r["name"].lower()))
        return rows

    def _check_backup(self) -> None:
        """Warn when the last automatic backup is getting old."""
        if not self.snap.backup_known:
            return
        last = self.snap.last_backup
        if last is not None and self.snap.now - last <= timedelta(days=BACKUP_MAX_AGE_DAYS):
            return
        if last is None:
            title = "No automatic backup has completed yet"
        else:
            days = (self.snap.now - last).days
            title = f"The last automatic backup was {days} days ago"
        self._add(
            Finding(
                id="backup_old",
                severity=WARNING,
                category="Backups",
                title=title,
                detail="HA Manager can undo its own changes, but only a backup "
                "protects you from everything else.",
                advice="Turn on automatic backups, or run one now, under "
                "Settings > System > Backups.",
                link="/config/backup",
            )
        )

    def _check_names(self) -> None:
        """One tidy-up item pointing at the Names tab."""
        issues = check_names(self.snap, self.naming_style)
        if not issues:
            return
        self._add(
            Finding(
                id="names",
                severity=TIDY,
                category="Names",
                title=f"{_plural(len(issues), 'name')} could be clearer",
                detail="Duplicates, factory names, and names that do not match "
                "the room they are in.",
                advice="Open the Names tab to fix them one click at a time.",
                items=[
                    {"name": i["name"], "area": i["area"], "note": i["reason"]}
                    for i in issues[:15]
                ],
            )
        )

    def _check_repairs(self) -> None:
        """Pull in Home Assistant's own Repairs list, plus Watchman's counts."""
        severity_map = {"critical": CRITICAL, "error": WARNING, "warning": TIDY}
        for issue in self.snap.repairs:
            cross_check = issue.domain in CROSS_CHECK_DOMAINS
            self._add(
                Finding(
                    id=f"repair:{issue.domain}:{issue.issue_id}",
                    severity=severity_map.get(issue.severity, TIDY),
                    category="Spook" if issue.domain == "spook" else "Home Assistant repairs",
                    title=issue.title,
                    detail="Reported by Spook. Shown for cross-checking, so it does "
                    "not count towards the score."
                    if cross_check
                    else f"Raised by the '{issue.domain}' integration.",
                    advice="Open Settings > System > Repairs for the details.",
                    link="/config/repairs",
                    counts=not cross_check,
                )
            )
        for label, count in (self.snap.watchman or {}).items():
            if count <= 0:
                continue
            self._add(
                Finding(
                    id=f"watchman:{label}",
                    severity=WARNING,
                    category="Watchman",
                    title=f"Watchman reports {count} {label}",
                    detail="Shown for cross-checking, so it does not count "
                    "towards the score.",
                    advice="Run Watchman's report for the full list.",
                    counts=False,
                )
            )


def score(findings: list[Finding]) -> dict[str, Any]:
    """Work out the health score from the findings that count."""
    counts = dict.fromkeys(SEVERITIES, 0)
    for finding in findings:
        if finding.counts:
            counts[finding.severity] += 1
    penalties = {
        severity: min(counts[severity] * SCORE_WEIGHTS[severity], SCORE_CAPS[severity])
        for severity in SEVERITIES
    }
    value = max(0, round(100 - sum(penalties.values())))
    if counts[CRITICAL] == 0 and value >= 90:
        grade = "Shipshape"
    elif counts[CRITICAL] == 0 and value >= 75:
        grade = "Good"
    elif value >= 50:
        grade = "Needs attention"
    else:
        grade = "Poorly"
    return {"value": value, "grade": grade, "counts": counts, "penalties": penalties}


def analyse(snapshot: Snapshot, store: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run every check and return the result as plain data."""
    return Analyser(snapshot, store).run()


def targets(snapshot: Snapshot) -> list[dict[str, Any]]:
    """Everything you can pick on the Blast radius tab."""
    result: list[dict[str, Any]] = [
        {"type": "area", "id": area_id, "name": name}
        for area_id, name in snapshot.areas.items()
    ]
    result += [
        {
            "type": "device",
            "id": device.device_id,
            "name": device.name,
            "area": snapshot.areas.get(device.area_id or ""),
        }
        for device in snapshot.devices.values()
    ]
    result += [
        {
            "type": "entity",
            "id": entity.entity_id,
            "name": entity.name,
            "area": snapshot.areas.get(entity.area_id or ""),
        }
        for entity in snapshot.entities.values()
    ]
    return result


def blast_radius(snapshot: Snapshot, target_type: str, target_id: str) -> dict[str, Any]:
    """List everything that uses an entity, a device or a room."""
    entity_ids: set[str] = set()
    device_ids: set[str] = set()
    area_ids: set[str] = set()
    name = target_id

    if target_type == "entity":
        entity_ids.add(target_id)
        if target_id in snapshot.entities:
            name = snapshot.entities[target_id].name
    elif target_type == "device":
        device_ids.add(target_id)
        if target_id in snapshot.devices:
            name = snapshot.devices[target_id].name
        entity_ids = {e.entity_id for e in snapshot.entities.values() if e.device_id == target_id}
    elif target_type == "area":
        area_ids.add(target_id)
        name = snapshot.areas.get(target_id, target_id)
        device_ids = {d.device_id for d in snapshot.devices.values() if d.area_id == target_id}
        entity_ids = {e.entity_id for e in snapshot.entities.values() if e.area_id == target_id}
    else:
        raise ValueError(f"Unknown target type: {target_type}")

    def label(entity_id: str) -> str:
        entity = snapshot.entities.get(entity_id)
        return entity.name if entity else entity_id

    users: dict[tuple[str, str], dict[str, Any]] = {}

    def add(consumer: Consumer, reason: str) -> None:
        entry = users.setdefault(
            (consumer.kind, consumer.id),
            {
                "kind": consumer.kind,
                "id": consumer.id,
                "name": consumer.name,
                "edit_url": consumer.edit_url,
                "why": [],
            },
        )
        if reason not in entry["why"]:
            entry["why"].append(reason)

    groups_hit: dict[str, str] = {}
    for consumer in snapshot.consumers:
        if consumer.id in entity_ids:
            continue  # a thing does not use itself
        for entity_id in sorted(consumer.all_entities & entity_ids):
            add(consumer, f"uses {label(entity_id)}" if target_type != "entity" else "uses it directly")
            if consumer.kind == "group":
                groups_hit[consumer.id] = consumer.name
        if consumer.devices & device_ids:
            add(consumer, "uses the device directly" if target_type == "device" else "uses a device in this room")
        if consumer.areas & area_ids:
            add(consumer, "targets the whole room")

    # One step further: things that use a group which contains the target.
    for consumer in snapshot.consumers:
        if consumer.id in entity_ids:
            continue
        for group_id in sorted(consumer.all_entities & set(groups_hit)):
            if (consumer.kind, consumer.id) != ("group", group_id):
                add(consumer, f"uses the group '{groups_hit[group_id]}', which contains it")

    order = ["automation", "script", "scene", "group", "dashboard"]
    used_by = sorted(users.values(), key=lambda u: (order.index(u["kind"]), u["name"].lower()))
    summary = {kind: sum(1 for u in used_by if u["kind"] == kind) for kind in order}
    return {
        "target": {
            "type": target_type,
            "id": target_id,
            "name": name,
            "exists": (
                target_id in snapshot.entities
                if target_type == "entity"
                else target_id in snapshot.devices
                if target_type == "device"
                else target_id in snapshot.areas
            ),
            "entity_count": len(entity_ids),
        },
        "used_by": used_by,
        "summary": summary,
        "safe": not used_by,
    }


def rooms(snapshot: Snapshot) -> dict[str, Any]:
    """Everything the Rooms tab needs: floors, rooms and what is in them."""
    counts: dict[str, int] = defaultdict(int)
    for entity in snapshot.entities.values():
        if entity.device_id and not entity.disabled:
            counts[entity.device_id] += 1

    items: list[dict[str, Any]] = [
        {
            "type": "device",
            "id": device.device_id,
            "name": device.name,
            "area_id": device.area_id,
            "detail": _plural(counts[device.device_id], "entity", "entities"),
        }
        for device in snapshot.devices.values()
        if not device.disabled and not device.is_service and counts[device.device_id]
    ]
    items += [
        {
            "type": "entity",
            "id": entity.entity_id,
            "name": entity.name,
            "area_id": entity.area_id,
            "detail": entity.domain.replace("_", " "),
        }
        for entity in snapshot.entities.values()
        if not entity.device_id
        and entity.in_registry
        and not entity.disabled
        and not entity.hidden
        and not entity.orphaned
        and entity.domain in NAMED_DOMAINS
    ]
    items.sort(key=lambda item: item["name"].lower())

    def floor_order(pair: tuple[str, dict[str, Any]]) -> tuple[float, str]:
        level = pair[1].get("level")
        return (-level if level is not None else float("inf"), pair[1]["name"].lower())

    return {
        "floors": [
            {"id": floor_id, "name": floor["name"], "level": floor.get("level")}
            for floor_id, floor in sorted(snapshot.floors.items(), key=floor_order)
        ],
        "areas": [
            {"id": area_id, "name": name, "floor_id": snapshot.area_floors.get(area_id)}
            for area_id, name in sorted(snapshot.areas.items(), key=lambda p: p[1].lower())
        ],
        "items": items,
    }
