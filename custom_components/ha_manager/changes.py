"""The Captain's Log: every change HA Manager makes, with undo.

All writes to Home Assistant go through `ChangeLog.async_apply`, which notes
the old value before changing anything, so each change can be put back.
"""

from __future__ import annotations

from typing import Any
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CHANGES_KEEP, CHANGES_STORAGE_KEY, STORAGE_VERSION

# The only things HA Manager is able to change.
DEVICE_AREA = "device_area"
ENTITY_AREA = "entity_area"
DEVICE_NAME = "device_name"
ENTITY_NAME = "entity_name"
AREA_FLOOR = "area_floor"
KINDS = (DEVICE_AREA, ENTITY_AREA, DEVICE_NAME, ENTITY_NAME, AREA_FLOOR)

MAX_NAME_LENGTH = 100


class ChangeError(HomeAssistantError):
    """A change could not be made."""


class ChangeLog:
    """Applies changes, remembers them, and can undo them."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, CHANGES_STORAGE_KEY)
        self.entries: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        if data := await self._store.async_load():
            self.entries = data.get("entries", [])

    async def _async_save(self) -> None:
        del self.entries[:-CHANGES_KEEP]
        await self._store.async_save({"entries": self.entries})

    # ----- reading and writing single values -----------------------------

    def _label(self, kind: str, target_id: str) -> str:
        if kind in (DEVICE_AREA, DEVICE_NAME):
            device = dr.async_get(self.hass).async_get(target_id)
            return (device.name_by_user or device.name or target_id) if device else target_id
        if kind in (ENTITY_AREA, ENTITY_NAME):
            state = self.hass.states.get(target_id)
            return state.name if state else target_id
        area = ar.async_get(self.hass).async_get_area(target_id)
        return area.name if area else target_id

    def _read(self, kind: str, target_id: str) -> str | None:
        """Return the current value, or raise if the thing has gone."""
        if kind in (DEVICE_AREA, DEVICE_NAME):
            device = dr.async_get(self.hass).async_get(target_id)
            if device is None:
                raise ChangeError("That device no longer exists")
            return device.area_id if kind == DEVICE_AREA else device.name_by_user
        if kind in (ENTITY_AREA, ENTITY_NAME):
            entry = er.async_get(self.hass).async_get(target_id)
            if entry is None:
                raise ChangeError("That entity no longer exists, or cannot be edited")
            return entry.area_id if kind == ENTITY_AREA else entry.name
        area = ar.async_get(self.hass).async_get_area(target_id)
        if area is None:
            raise ChangeError("That room no longer exists")
        return area.floor_id

    def _check(self, kind: str, value: str | None) -> str | None:
        """Make sure a new value is allowed."""
        if kind in (DEVICE_AREA, ENTITY_AREA):
            if value is not None and ar.async_get(self.hass).async_get_area(value) is None:
                raise ChangeError("That room does not exist")
        elif kind == AREA_FLOOR:
            if value is not None and fr.async_get(self.hass).async_get_floor(value) is None:
                raise ChangeError("That floor does not exist")
        elif value is not None:
            value = " ".join(value.split())
            if not value or len(value) > MAX_NAME_LENGTH:
                raise ChangeError(f"A name must be between 1 and {MAX_NAME_LENGTH} characters")
        return value

    def _write(self, kind: str, target_id: str, value: str | None) -> None:
        if kind == DEVICE_AREA:
            dr.async_get(self.hass).async_update_device(target_id, area_id=value)
        elif kind == DEVICE_NAME:
            dr.async_get(self.hass).async_update_device(target_id, name_by_user=value)
        elif kind == ENTITY_AREA:
            er.async_get(self.hass).async_update_entity(target_id, area_id=value)
        elif kind == ENTITY_NAME:
            er.async_get(self.hass).async_update_entity(target_id, name=value)
        elif kind == AREA_FLOOR:
            ar.async_get(self.hass).async_update(target_id, floor_id=value)
        else:
            raise ChangeError(f"Unknown kind of change: {kind}")

    def _describe(self, kind: str, value: str | None) -> str:
        """Turn a stored value into words for the log."""
        if kind in (DEVICE_AREA, ENTITY_AREA):
            if value is None:
                return "No room"
            area = ar.async_get(self.hass).async_get_area(value)
            return area.name if area else value
        if kind == AREA_FLOOR:
            if value is None:
                return "No floor"
            floor = fr.async_get(self.hass).async_get_floor(value)
            return floor.name if floor else value
        return value if value is not None else "(default name)"

    # ----- public API ----------------------------------------------------

    async def async_apply(
        self,
        summary: str,
        requested: list[tuple[str, str, str | None]],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply a batch of (kind, id, new value) changes as one log entry.

        Everything is checked first, so a bad request changes nothing.
        """
        planned: list[dict[str, Any]] = []
        for kind, target_id, value in requested:
            if kind not in KINDS:
                raise ChangeError(f"Unknown kind of change: {kind}")
            value = self._check(kind, value)
            before = self._read(kind, target_id)
            if before == value:
                continue
            planned.append(
                {
                    "kind": kind,
                    "id": target_id,
                    "label": self._label(kind, target_id),
                    "before": before,
                    "after": value,
                    "before_text": self._describe(kind, before),
                    "after_text": self._describe(kind, value),
                }
            )
        entry = {
            "id": uuid.uuid4().hex,
            "when": dt_util.utcnow().isoformat(),
            "user_id": user_id,
            "summary": summary,
            "items": planned,
            "undone": None,
        }
        if not planned:
            return entry
        for item in planned:
            self._write(item["kind"], item["id"], item["after"])
        self.entries.append(entry)
        await self._async_save()
        return entry

    async def async_undo(self, change_id: str) -> dict[str, Any]:
        """Put back everything one log entry changed.

        Anything that has been changed again since, or has gone, is left alone
        and reported back.
        """
        entry = next((e for e in self.entries if e["id"] == change_id), None)
        if entry is None:
            raise ChangeError("That log entry no longer exists")
        if entry["undone"]:
            raise ChangeError("That change has already been undone")
        reverted = 0
        skipped: list[dict[str, str]] = []
        for item in reversed(entry["items"]):
            try:
                current = self._read(item["kind"], item["id"])
            except ChangeError as err:
                skipped.append({"label": item["label"], "reason": str(err)})
                continue
            if current != item["after"]:
                skipped.append(
                    {"label": item["label"], "reason": "It has been changed again since"}
                )
                continue
            try:
                self._check(item["kind"], item["before"])
                self._write(item["kind"], item["id"], item["before"])
            except (ChangeError, ValueError) as err:
                skipped.append({"label": item["label"], "reason": str(err)})
                continue
            reverted += 1
        entry["undone"] = dt_util.utcnow().isoformat()
        entry["undo_skipped"] = skipped
        await self._async_save()
        return {"reverted": reverted, "skipped": skipped}

    def as_list(self) -> list[dict[str, Any]]:
        """Newest first."""
        return list(reversed(self.entries))
