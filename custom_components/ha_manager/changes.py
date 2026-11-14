"""The Captain's Log: every change HA Manager makes, with undo.

All writes to Home Assistant go through `ChangeLog.async_apply` (for things
that can be switched back) or `ChangeLog.async_remove` (for removals). Both note
what was there before, so each change can be put back where Home Assistant
allows it.
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
from .editor_files import EditorFileError, async_put_back, async_take_out

# The only things HA Manager is able to change.
DEVICE_AREA = "device_area"
ENTITY_AREA = "entity_area"
DEVICE_NAME = "device_name"
ENTITY_NAME = "entity_name"
AREA_FLOOR = "area_floor"
ENTITY_DISABLED = "entity_disabled"  # None = enabled, "user" = disabled
DEVICE_DISABLED = "device_disabled"
AUTOMATION_ON = "automation_on"  # "on" or "off"
KINDS = (
    DEVICE_AREA, ENTITY_AREA, DEVICE_NAME, ENTITY_NAME, AREA_FLOOR,
    ENTITY_DISABLED, DEVICE_DISABLED, AUTOMATION_ON,
)

# Removals. Each keeps a copy in the log so it can be put back. (Devices are
# never removed: Home Assistant has no way to bring one back.)
REMOVED_AUTOMATION = "removed_automation"
REMOVED_SCRIPT = "removed_script"
REMOVED_ENTITY = "removed_entity"
REMOVED_DEVICE = "removed_device"
REMOVALS = (REMOVED_AUTOMATION, REMOVED_SCRIPT, REMOVED_ENTITY, REMOVED_DEVICE)
USER = "user"

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
        if kind in (DEVICE_AREA, DEVICE_NAME, DEVICE_DISABLED, REMOVED_DEVICE):
            device = dr.async_get(self.hass).async_get(target_id)
            return (device.name_by_user or device.name or target_id) if device else target_id
        if kind != AREA_FLOOR:
            if state := self.hass.states.get(target_id):
                return state.name
            entry = er.async_get(self.hass).async_get(target_id)
            return (entry.name or entry.original_name or target_id) if entry else target_id
        area = ar.async_get(self.hass).async_get_area(target_id)
        return area.name if area else target_id

    def _read(self, kind: str, target_id: str) -> str | None:
        """Return the current value, or raise if the thing has gone."""
        if kind in (DEVICE_AREA, DEVICE_NAME, DEVICE_DISABLED):
            device = dr.async_get(self.hass).async_get(target_id)
            if device is None:
                raise ChangeError("That device no longer exists")
            if kind == DEVICE_DISABLED:
                return device.disabled_by.value if device.disabled_by else None
            return device.area_id if kind == DEVICE_AREA else device.name_by_user
        if kind in (ENTITY_AREA, ENTITY_NAME, ENTITY_DISABLED):
            entry = er.async_get(self.hass).async_get(target_id)
            if entry is None:
                raise ChangeError("That entity no longer exists, or cannot be edited")
            if kind == ENTITY_DISABLED:
                return entry.disabled_by.value if entry.disabled_by else None
            return entry.area_id if kind == ENTITY_AREA else entry.name
        if kind == AUTOMATION_ON:
            state = self.hass.states.get(target_id)
            if state is None or state.state not in ("on", "off"):
                raise ChangeError("That automation is not loaded, so it cannot be switched")
            return state.state
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
        elif kind in (ENTITY_DISABLED, DEVICE_DISABLED):
            if value not in (None, USER):
                raise ChangeError("HA Manager can only disable things as you, the user")
        elif kind == AUTOMATION_ON:
            if value not in ("on", "off"):
                raise ChangeError("An automation can only be switched on or off")
        elif value is not None:
            value = " ".join(value.split())
            if not value or len(value) > MAX_NAME_LENGTH:
                raise ChangeError(f"A name must be between 1 and {MAX_NAME_LENGTH} characters")
        return value

    async def _async_write(self, kind: str, target_id: str, value: str | None) -> None:
        if kind == ENTITY_DISABLED:
            registry = er.async_get(self.hass)
            entry = registry.async_update_entity(
                target_id, disabled_by=er.RegistryEntryDisabler.USER if value else None
            )
            # Automations and scripts have no integration to reload them, so
            # bring a re-enabled one back by reloading its kind.
            if value is None and entry.domain in ("automation", "script") and entry.config_entry_id is None:
                if self.hass.services.has_service(entry.domain, "reload"):
                    await self.hass.services.async_call(entry.domain, "reload", blocking=True)
            return
        if kind == DEVICE_DISABLED:
            dr.async_get(self.hass).async_update_device(
                target_id, disabled_by=dr.DeviceEntryDisabler.USER if value else None
            )
            return
        if kind == AUTOMATION_ON:
            await self.hass.services.async_call(
                "automation", "turn_on" if value == "on" else "turn_off",
                {"entity_id": target_id}, blocking=True,
            )
            return
        self._write(kind, target_id, value)

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
        if kind in (ENTITY_DISABLED, DEVICE_DISABLED):
            if value is None:
                return "Enabled"
            return "Disabled" if value == USER else f"Disabled by {value}"
        if kind == AUTOMATION_ON:
            return "On" if value == "on" else "Off"
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
        done: list[dict[str, Any]] = []
        try:
            for item in planned:
                await self._async_write(item["kind"], item["id"], item["after"])
                done.append(item)
        except Exception as err:
            # Something went wrong half way: keep a record of what did change.
            if done:
                entry["items"] = done
                self.entries.append(entry)
                await self._async_save()
            raise ChangeError(f"Stopped part way through: {err}") from err
        self.entries.append(entry)
        await self._async_save()
        return entry

    async def async_undo(self, change_id: str, index: int | None = None) -> dict[str, Any]:
        """Put back what one log entry changed: all of it, or just one item.

        Anything that has been changed again since, or has gone, is left alone
        and reported back.
        """
        entry = next((e for e in self.entries if e["id"] == change_id), None)
        if entry is None:
            raise ChangeError("That log entry no longer exists")
        if entry["undone"]:
            raise ChangeError("That change has already been undone")
        if index is None:
            chosen = [i for i in entry["items"] if not i.get("undone")]
        else:
            if not 0 <= index < len(entry["items"]):
                raise ChangeError("That item is not in this log entry")
            if entry["items"][index].get("undone"):
                raise ChangeError("That one has already been undone")
            chosen = [entry["items"][index]]
        reverted = 0
        skipped: list[dict[str, str]] = []
        for item in reversed(chosen):
            try:
                await self._async_undo_item(item)
            except (HomeAssistantError, ValueError) as err:
                skipped.append({"label": item["label"], "reason": str(err)})
                item["undo_failed"] = str(err)
                continue
            item["undone"] = dt_util.utcnow().isoformat()
            item.pop("undo_failed", None)
            reverted += 1
        if index is None or all(i.get("undone") for i in entry["items"]):
            entry["undone"] = dt_util.utcnow().isoformat()
            entry["undo_skipped"] = skipped
        await self._async_save()
        return {"reverted": reverted, "skipped": skipped}

    async def _async_undo_item(self, item: dict[str, Any]) -> None:
        if item["kind"] in REMOVALS:
            await self._async_put_back(item)
            return
        current = self._read(item["kind"], item["id"])
        if current != item["after"]:
            raise ChangeError("It has been changed again since")
        self._check(item["kind"], item["before"])
        await self._async_write(item["kind"], item["id"], item["before"])

    async def async_remove(
        self,
        summary: str,
        requested: list[tuple[str, str, str | None]],
        user_id: str | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """Remove things, as (kind, id, config key) tuples. One log entry.

        Each one is tried on its own, so one failure does not stop the rest.
        Returns the log entry and a list of anything that could not be removed.
        Checking that nothing uses them is the caller's job, done just before.
        """
        done: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        for kind, target_id, key in requested:
            label = self._label(kind, target_id)
            try:
                before = await self._async_take_out(kind, target_id, key)
            except (HomeAssistantError, ValueError) as err:
                failed.append({"label": label, "reason": str(err)})
                continue
            undoable = kind in (REMOVED_AUTOMATION, REMOVED_SCRIPT, REMOVED_ENTITY)
            done.append(
                {
                    "kind": kind,
                    "id": target_id,
                    "label": label,
                    "before": before,
                    "after": None,
                    "before_text": "Kept a copy",
                    "after_text": "Removed",
                    "undoable": undoable,
                }
            )
        entry = {
            "id": uuid.uuid4().hex,
            "when": dt_util.utcnow().isoformat(),
            "user_id": user_id,
            "summary": summary,
            "items": done,
            "undone": None,
        }
        if done:
            self.entries.append(entry)
            await self._async_save()
        return entry, failed

    async def _async_take_out(self, kind: str, target_id: str, key: str | None) -> Any:
        if kind in (REMOVED_AUTOMATION, REMOVED_SCRIPT):
            domain = "automation" if kind == REMOVED_AUTOMATION else "script"
            if not key:
                raise ChangeError("It has no id, so it was probably written by hand in YAML")
            try:
                config = await async_take_out(self.hass, domain, key)
            except EditorFileError as err:
                raise ChangeError(str(err)) from err
            return {"key": key, "domain": domain, "config": config}
        if kind == REMOVED_ENTITY:
            registry = er.async_get(self.hass)
            entry = registry.async_get(target_id)
            state = self.hass.states.get(target_id)
            if entry is None and state is None:
                raise ChangeError("It has already gone")
            # Keep enough to put it back exactly as it was.
            saved: dict[str, Any] = {"entity_id": target_id, "registry": None, "state": None}
            if entry is not None:
                saved["registry"] = {
                    "platform": entry.platform,
                    "unique_id": entry.unique_id,
                    "device_id": entry.device_id,
                    "name": entry.name,
                    "original_name": entry.original_name,
                    "icon": entry.icon,
                    "area_id": entry.area_id,
                    "labels": sorted(entry.labels),
                }
                registry.async_remove(target_id)
            if state is not None:
                saved["state"] = {"state": state.state, "attributes": dict(state.attributes)}
                self.hass.states.async_remove(target_id)
            return saved
        raise ChangeError(f"Unknown kind of removal: {kind}")

    async def _async_put_back(self, item: dict[str, Any]) -> None:
        before = item.get("before")
        if item["kind"] == REMOVED_ENTITY and before:
            self._put_back_entity(before)
            return
        if item["kind"] not in (REMOVED_AUTOMATION, REMOVED_SCRIPT) or not before:
            raise ChangeError("Removed for good: Home Assistant has no way to bring it back")
        try:
            await async_put_back(self.hass, before["domain"], before["key"], before["config"])
        except EditorFileError as err:
            raise ChangeError(str(err)) from err

    def _put_back_entity(self, saved: dict[str, Any]) -> None:
        """Recreate a removed leftover entity, as the leftover it was."""
        entity_id = saved["entity_id"]
        registry = er.async_get(self.hass)
        if registry.async_get(entity_id) is not None or self.hass.states.get(entity_id) is not None:
            raise ChangeError("Something else is using that entity ID now")
        domain, object_id = entity_id.split(".", 1)
        if reg := saved.get("registry"):
            device_id = reg["device_id"]
            if device_id and dr.async_get(self.hass).async_get(device_id) is None:
                device_id = None
            entry = registry.async_get_or_create(
                domain, reg["platform"], reg["unique_id"],
                suggested_object_id=object_id,
                original_name=reg["original_name"],
                device_id=device_id,
            )
            if entry.entity_id != entity_id:
                entry = registry.async_update_entity(entry.entity_id, new_entity_id=entity_id)
            area_id = reg["area_id"]
            if area_id and ar.async_get(self.hass).async_get_area(area_id) is None:
                area_id = None
            registry.async_update_entity(
                entity_id, name=reg["name"], icon=reg["icon"], area_id=area_id,
                labels=set(reg["labels"]),
            )
        if state := saved.get("state"):
            self.hass.states.async_set(entity_id, state["state"], state["attributes"])

    def as_list(self) -> list[dict[str, Any]]:
        """Newest first."""
        return list(reversed(self.entries))
