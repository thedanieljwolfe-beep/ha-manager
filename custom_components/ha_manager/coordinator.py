"""Runs the scan on a schedule and keeps the latest result."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .analysis import analyse
from .collector import async_collect
from .const import DOMAIN, SCAN_INTERVAL, STORAGE_KEY, STORAGE_VERSION
from .models import Snapshot

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
        self.saved: dict[str, Any] = {
            "safety_tests": {},
            "safety_excluded": [],
            "ignored": [],
            # {automation entity_id: {hour number: times fired in that hour}}
            "triggers": {},
            "triggers_since": dt_util.utcnow().isoformat(),
        }

    async def async_load(self) -> None:
        """Load what the user has saved (test log, ignored findings)."""
        if data := await self._store.async_load():
            self.saved.update(data)

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
