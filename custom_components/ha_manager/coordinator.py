"""Runs the scan on a schedule and keeps the latest result."""

from __future__ import annotations

from datetime import datetime
from functools import partial
import hashlib
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .analysis import analyse
from .changes import (
    AREA_FLOOR,
    DEVICE_AREA,
    DEVICE_NAME,
    ENTITY_AREA,
    ENTITY_NAME,
    ChangeError,
    ChangeLog,
)
from .collector import async_collect
from .const import (
    BATTERY_BACKFILL_DAYS,
    BATTERY_HISTORY_DAYS,
    DOMAIN,
    PLAN_IMAGE_MAX,
    PLAN_STORAGE_KEY,
    REPORT_HISTORY_KEEP,
    NAMING_STYLES,
    SCAN_INTERVAL,
    STORAGE_KEY,
    STORAGE_VERSION,
    STYLE_ROOM_FIRST,
)
from .explain import explain
from .models import Snapshot
from .report import build_report

_LOGGER = logging.getLogger(__name__)
SAVE_DELAY = 300  # seconds

type HAManagerConfigEntry = ConfigEntry[HAManagerCoordinator]


class HAManagerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Scan the house and remember what the user has told us."""

    snapshot: Snapshot | None = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.changes = ChangeLog(hass)
        self.saved: dict[str, Any] = {
            "safety_tests": {},
            "safety_excluded": [],
            "ignored": [],
            "naming_style": STYLE_ROOM_FIRST,
            # {automation entity_id: {hour number: times fired in that hour}}
            "triggers": {},
            "triggers_since": dt_util.utcnow().isoformat(),
            # {battery entity_id: {day number: percent}}
            "battery_samples": {},
            "report": {
                "enabled": True,
                "weekday": 6,  # Monday is 0, so 6 is Sunday
                "hour": 18,
                "notify": None,
                "last_sent_week": None,
                "last": None,
                "history": [],
            },
            # {entity_id: {"hash": ..., "text": ...}} AI explanations already fetched
            "explanations": {},
        }
        self._plan_store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, PLAN_STORAGE_KEY)
        self.layouts: dict[str, dict[str, Any]] = {}
        self._backfilled: set[str] = set()

    async def async_load(self) -> None:
        """Load what the user has saved (test log, ignored findings)."""
        if data := await self._store.async_load():
            report = {**self.saved["report"], **data.get("report", {})}
            self.saved.update(data)
            self.saved["report"] = report
        if layouts := await self._plan_store.async_load():
            self.layouts = layouts
        await self.changes.async_load()

    @callback
    def async_start_counting(self) -> CALLBACK_TYPE:
        """Count every time an automation fires, in hourly buckets."""

        @callback
        def _triggered(event: Event) -> None:
            entity_id = event.data.get("entity_id")
            if not isinstance(entity_id, str):
                return
            hour = str(int(dt_util.utcnow().timestamp() // 3600))
            buckets = self.saved["triggers"].setdefault(entity_id, {})
            buckets[hour] = buckets.get(hour, 0) + 1
            self._store.async_delay_save(lambda: self.saved, SAVE_DELAY)

        return self.hass.bus.async_listen("automation_triggered", _triggered)

    def _triggers_last_24h(self) -> dict[str, int]:
        """Add up the last 24 hourly buckets and drop anything older."""
        oldest = int(dt_util.utcnow().timestamp() // 3600) - 24
        totals: dict[str, int] = {}
        for entity_id, buckets in list(self.saved["triggers"].items()):
            for hour in [h for h in buckets if int(h) < oldest]:
                del buckets[hour]
            if buckets:
                totals[entity_id] = sum(buckets.values())
            else:
                del self.saved["triggers"][entity_id]
        return totals

    async def _async_update_data(self) -> dict[str, Any]:
        snapshot = await async_collect(self.hass)
        totals = self._triggers_last_24h()
        snapshot.counting_since = dt_util.parse_datetime(self.saved["triggers_since"])
        for consumer in snapshot.consumers:
            if consumer.kind == "automation":
                consumer.triggers_24h = totals.get(consumer.id, 0)
        await self._async_sample_batteries(snapshot)
        self.snapshot = snapshot
        return analyse(snapshot, self.saved)

    async def async_save(self) -> None:
        """Write everything to disk now."""
        await self._store.async_save(self.saved)

    async def _async_saved_changed(self) -> None:
        await self._store.async_save(self.saved)
        if self.snapshot is not None:
            # Re-run the checks on the data we already have: instant, no rescan.
            self.async_set_updated_data(analyse(self.snapshot, self.saved))

    async def async_log_safety_test(self, unit_id: str) -> None:
        """Record that a life-safety device was tested just now."""
        tests = self.saved["safety_tests"].setdefault(unit_id, [])
        tests.append(dt_util.utcnow().isoformat())
        del tests[:-24]  # keep the last two years of monthly tests
        await self._async_saved_changed()

    async def async_set_safety_excluded(self, unit_id: str, excluded: bool) -> None:
        """Take a device off, or put it back on, the life-safety list."""
        current = set(self.saved["safety_excluded"])
        current.add(unit_id) if excluded else current.discard(unit_id)
        self.saved["safety_excluded"] = sorted(current)
        await self._async_saved_changed()

    async def async_set_ignored(self, finding_id: str, ignored: bool) -> None:
        """Ignore a finding, or stop ignoring it."""
        current = set(self.saved["ignored"])
        current.add(finding_id) if ignored else current.discard(finding_id)
        self.saved["ignored"] = sorted(current)
        await self._async_saved_changed()

    async def async_set_naming_style(self, style: str) -> None:
        """Choose which naming style the checker looks for."""
        if style not in NAMING_STYLES:
            raise ChangeError("Unknown naming style")
        self.saved["naming_style"] = style
        await self._async_saved_changed()

    # ----- changes to Home Assistant, all logged and undoable -------------

    async def _async_changed(self) -> None:
        """Rescan so every tab reflects what was just changed."""
        await self.async_refresh()

    async def async_move(
        self, items: list[dict[str, str]], area_id: str | None, user_id: str | None
    ) -> dict[str, Any]:
        """Move devices and standalone entities to a room (or to no room)."""
        requested = [
            (DEVICE_AREA if item["type"] == "device" else ENTITY_AREA, item["id"], area_id)
            for item in items
        ]
        room = self.snapshot.areas.get(area_id, area_id) if self.snapshot and area_id else None
        count = len(requested)
        summary = (
            f"Moved {count} thing{'' if count == 1 else 's'} to {room}"
            if area_id
            else f"Took {count} thing{'' if count == 1 else 's'} out of their room"
        )
        entry = await self.changes.async_apply(summary, requested, user_id)
        await self._async_changed()
        return entry

    async def async_set_floor(
        self, area_id: str, floor_id: str | None, user_id: str | None
    ) -> dict[str, Any]:
        """Put a room on a floor."""
        room = self.snapshot.areas.get(area_id, area_id) if self.snapshot else area_id
        entry = await self.changes.async_apply(
            f"Changed the floor for {room}", [(AREA_FLOOR, area_id, floor_id)], user_id
        )
        await self._async_changed()
        return entry

    async def async_rename(
        self, items: list[dict[str, str]], user_id: str | None
    ) -> dict[str, Any]:
        """Rename devices and standalone entities (friendly names only)."""
        requested = [
            (DEVICE_NAME if item["type"] == "device" else ENTITY_NAME, item["id"], item["name"])
            for item in items
        ]
        count = len(requested)
        summary = (
            f"Renamed '{self.changes._label(requested[0][0], requested[0][1])}' to '{items[0]['name']}'"  # noqa: SLF001
            if count == 1
            else f"Renamed {count} things"
        )
        entry = await self.changes.async_apply(summary, requested, user_id)
        await self._async_changed()
        return entry

    async def async_undo(self, change_id: str) -> dict[str, Any]:
        """Undo one entry in the log."""
        result = await self.changes.async_undo(change_id)
        await self._async_changed()
        return result

    # ----- battery history -------------------------------------------------

    async def _async_sample_batteries(self, snapshot: Snapshot) -> None:
        """Keep one battery reading a day, and hand the history to the snapshot."""
        samples: dict[str, dict[str, float]] = self.saved["battery_samples"]
        today = int(snapshot.now.timestamp() // 86400)
        current: set[str] = set()
        for entity in snapshot.entities.values():
            if entity.domain != "sensor" or entity.device_class != "battery":
                continue
            if entity.disabled or entity.orphaned:
                continue
            current.add(entity.entity_id)
            try:
                level = float(entity.state)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if 0 <= level <= 100:
                samples.setdefault(entity.entity_id, {})[str(today)] = level

        await self._async_backfill_batteries(
            [e for e in current if len(samples.get(e, {})) < 3 and e not in self._backfilled],
            today,
        )

        oldest = today - BATTERY_HISTORY_DAYS
        for entity_id in list(samples):
            if entity_id not in current:
                del samples[entity_id]
                continue
            days = samples[entity_id]
            for day in [d for d in days if int(d) < oldest]:
                del days[day]
            snapshot.battery_history[entity_id] = [
                (
                    snapshot.now
                    if int(day) == today
                    else dt_util.utc_from_timestamp(int(day) * 86400 + 43200),
                    level,
                )
                for day, level in sorted(days.items(), key=lambda pair: int(pair[0]))
            ]

    async def _async_backfill_batteries(self, entity_ids: list[str], today: int) -> None:
        """Fill in past readings from Home Assistant's long-term statistics."""
        if not entity_ids or "recorder" not in self.hass.config.components:
            return
        self._backfilled.update(entity_ids)
        try:
            from homeassistant.components.recorder import get_instance  # noqa: PLC0415
            from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
                statistics_during_period,
            )

            start = dt_util.utc_from_timestamp((today - BATTERY_BACKFILL_DAYS) * 86400)
            rows = await get_instance(self.hass).async_add_executor_job(
                partial(
                    statistics_during_period,
                    self.hass, start, None, set(entity_ids), "day",
                    {"unitless": "%"},  # always in percent, never as a 0-1 ratio
                    {"mean"},
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not read battery statistics", exc_info=True)
            return
        samples = self.saved["battery_samples"]
        for entity_id, points in rows.items():
            days = samples.setdefault(entity_id, {})
            for point in points:
                mean = point.get("mean")
                if mean is None or not 0 <= mean <= 100:
                    continue
                day = str(int(point["start"] // 86400))
                days.setdefault(day, round(mean, 1))

    # ----- weekly report ---------------------------------------------------

    @callback
    def async_start_reports(self) -> CALLBACK_TYPE:
        """Check on the hour whether the weekly report is due."""

        async def _tick(now: datetime) -> None:
            settings = self.saved["report"]
            week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
            if (
                settings["enabled"]
                and now.weekday() == settings["weekday"]
                and now.hour == settings["hour"]
                and settings["last_sent_week"] != week
            ):
                await self.async_send_report(week=week)

        return async_track_time_change(self.hass, _tick, minute=0, second=0)

    def report_preview(self) -> dict[str, Any] | None:
        """What the report would say right now."""
        if self.data is None:
            return None
        history = self.saved["report"]["history"]
        return build_report(self.data, history[-1] if history else None)

    async def async_send_report(self, week: str | None = None) -> dict[str, Any] | None:
        """Send the report. With `week` set, it is the real weekly one and is remembered."""
        if week is not None or self.data is None:
            await self.async_refresh()
        report = self.report_preview()
        if report is None:
            return None
        settings = self.saved["report"]
        from homeassistant.components import persistent_notification  # noqa: PLC0415

        persistent_notification.async_create(
            self.hass,
            "\n".join([report["headline"], "", *report["lines"]]),
            title=report["title"],
            notification_id=f"{DOMAIN}_weekly_report",
        )
        target = settings["notify"]
        if target and self.hass.services.has_service("notify", target):
            try:
                await self.hass.services.async_call(
                    "notify", target, {"title": report["title"], "message": report["text"]}
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Could not send the weekly report to notify.%s", target, exc_info=True)
        summary = report.pop("summary")
        settings["last"] = {**report, "sent": dt_util.utcnow().isoformat()}
        if week is not None:
            settings["last_sent_week"] = week
            settings["history"].append(summary)
            del settings["history"][:-REPORT_HISTORY_KEEP]
        await self._store.async_save(self.saved)
        return settings["last"]

    async def async_set_report_settings(
        self, enabled: bool, weekday: int, hour: int, notify: str | None
    ) -> None:
        """Change when and where the weekly report goes."""
        self.saved["report"].update(
            {"enabled": enabled, "weekday": weekday, "hour": hour, "notify": notify or None}
        )
        await self._store.async_save(self.saved)

    # ----- explainer -------------------------------------------------------

    def _namer(self, value: str) -> str:
        snapshot = self.snapshot
        if snapshot is None:
            return value
        if value.startswith("area:"):
            return snapshot.areas.get(value[5:], value[5:])
        entity = snapshot.entities.get(value)
        return entity.name if entity else value

    @property
    def ai_available(self) -> bool:
        """True when Home Assistant has an AI Task service to ask."""
        return self.hass.services.has_service("ai_task", "generate_data")

    async def async_explain(self, entity_id: str, use_ai: bool) -> dict[str, Any]:
        """Explain an automation or script, optionally asking Home Assistant's AI."""
        consumer = next(
            (
                c
                for c in (self.snapshot.consumers if self.snapshot else [])
                if c.id == entity_id and c.kind in ("automation", "script")
            ),
            None,
        )
        if consumer is None:
            raise ChangeError("That automation or script was not found")
        result = explain(consumer.kind, consumer.config, self._namer)
        result["ai_available"] = self.ai_available and bool(consumer.config)
        result["ai_text"] = None
        result["ai_error"] = None
        if not consumer.config:
            return result
        digest = hashlib.sha1(  # noqa: S324 - only used to spot changes
            json.dumps(consumer.config, sort_keys=True, default=str).encode()
        ).hexdigest()
        cached = self.saved["explanations"].get(entity_id)
        if cached and cached["hash"] == digest:
            result["ai_text"] = cached["text"]
        elif use_ai and result["ai_available"]:
            names = {
                e: self._namer(e) for e in sorted(consumer.all_entities) if self._namer(e) != e
            }
            instructions = (
                "Explain what this Home Assistant "
                f"{consumer.kind} does, for someone who is not technical. "
                "Use two or three short plain-English sentences. Say what starts it, "
                "any conditions, and what it does. Use the friendly names given, never "
                "entity IDs. Do not give advice or add a heading.\n\n"
                f"Name: {consumer.name}\n"
                f"Friendly names: {json.dumps(names)}\n"
                f"Config: {json.dumps(consumer.config, default=str)[:6000]}"
            )
            try:
                response = await self.hass.services.async_call(
                    "ai_task",
                    "generate_data",
                    {"task_name": f"Explain {consumer.name}"[:100], "instructions": instructions},
                    blocking=True,
                    return_response=True,
                )
                text = str((response or {}).get("data") or "").strip()
                if not text:
                    raise ValueError("The AI gave an empty answer")  # noqa: TRY301
                result["ai_text"] = text
                self.saved["explanations"][entity_id] = {"hash": digest, "text": text}
                await self._store.async_save(self.saved)
            except Exception as err:  # noqa: BLE001
                result["ai_error"] = str(err) or "The AI did not answer"
        return result

    # ----- floor plan ------------------------------------------------------

    async def async_save_layout(
        self,
        floor: str,
        positions: dict[str, list[float]] | None,
        image: str | None,
        set_image: bool,
    ) -> None:
        """Save where the rooms sit on a floor, and optionally its picture."""
        layout = self.layouts.setdefault(floor, {"image": None, "positions": {}})
        if set_image:
            if image is not None and (
                not image.startswith("data:image/") or len(image) > PLAN_IMAGE_MAX
            ):
                raise ChangeError("That picture is too big or is not an image")
            layout["image"] = image
        if positions is not None:
            layout["positions"] = {
                area_id: [min(100.0, max(0.0, float(x))), min(100.0, max(0.0, float(y)))]
                for area_id, (x, y) in positions.items()
            }
        await self._plan_store.async_save(self.layouts)
