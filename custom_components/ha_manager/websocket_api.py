"""Websocket commands used by the HA Manager panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .analysis import blast_radius, rooms, targets
from .changes import ChangeError
from .const import DOMAIN, NAMING_STYLES
from .naming import check_names


def _coordinator(hass: HomeAssistant, connection, msg):
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]
    if not entries:
        connection.send_error(msg["id"], "not_loaded", "HA Manager is not set up")
        return None
    return entries[0].runtime_data


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the commands (safe to call more than once)."""
    for command in (
        ws_scan, ws_targets, ws_blast_radius, ws_log_test, ws_exclude, ws_ignore,
        ws_rooms, ws_move, ws_set_floor, ws_names, ws_naming_style, ws_rename,
        ws_changes, ws_undo,
    ):
        websocket_api.async_register_command(hass, command)


@websocket_api.websocket_command(
    {vol.Required("type"): "ha_manager/scan", vol.Optional("refresh", default=False): bool}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_scan(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Return the latest scan, running a new one if asked or if there is none."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    if msg["refresh"] or coordinator.data is None:
        await coordinator.async_refresh()
    if coordinator.data is None:
        connection.send_error(msg["id"], "scan_failed", "The scan failed, see the log")
        return
    connection.send_result(msg["id"], coordinator.data)


@websocket_api.websocket_command({vol.Required("type"): "ha_manager/targets"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_targets(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """List everything that can be picked on the Blast radius tab."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    if coordinator.snapshot is None:
        await coordinator.async_refresh()
    connection.send_result(
        msg["id"], targets(coordinator.snapshot) if coordinator.snapshot else []
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ha_manager/blast_radius",
        vol.Required("target_type"): vol.In(["entity", "device", "area"]),
        vol.Required("target_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_blast_radius(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Show everything that uses an entity, device or room."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    if coordinator.snapshot is None:
        await coordinator.async_refresh()
    if coordinator.snapshot is None:
        connection.send_error(msg["id"], "scan_failed", "The scan failed, see the log")
        return
    connection.send_result(
        msg["id"],
        blast_radius(coordinator.snapshot, msg["target_type"], msg["target_id"]),
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "ha_manager/safety/log_test", vol.Required("unit_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_log_test(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Record a life-safety test."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    await coordinator.async_log_safety_test(msg["unit_id"])
    connection.send_result(msg["id"], coordinator.data)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ha_manager/safety/set_excluded",
        vol.Required("unit_id"): str,
        vol.Required("excluded"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_exclude(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Take a device off the life-safety list, or put it back."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    await coordinator.async_set_safety_excluded(msg["unit_id"], msg["excluded"])
    connection.send_result(msg["id"], coordinator.data)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ha_manager/ignore",
        vol.Required("finding_id"): str,
        vol.Required("ignored"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_ignore(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Ignore a finding, or stop ignoring it."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    await coordinator.async_set_ignored(msg["finding_id"], msg["ignored"])
    connection.send_result(msg["id"], coordinator.data)


# ----- Phase 2: rooms, names and the change log --------------------------

_ITEM = vol.Schema(
    {vol.Required("type"): vol.In(["device", "entity"]), vol.Required("id"): str}
)
_RENAME_ITEM = _ITEM.extend({vol.Required("name"): str})


async def _snapshot(hass: HomeAssistant, connection, msg):
    """Return (coordinator, snapshot), scanning first if needed."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return None, None
    if coordinator.snapshot is None:
        await coordinator.async_refresh()
    if coordinator.snapshot is None:
        connection.send_error(msg["id"], "scan_failed", "The scan failed, see the log")
        return None, None
    return coordinator, coordinator.snapshot


def _names(coordinator) -> dict[str, Any]:
    style = coordinator.saved["naming_style"]
    return {"style": style, "issues": check_names(coordinator.snapshot, style)}


@websocket_api.websocket_command({vol.Required("type"): "ha_manager/rooms"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_rooms(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Floors, rooms and what is in each."""
    coordinator, snapshot = await _snapshot(hass, connection, msg)
    if coordinator is not None:
        connection.send_result(msg["id"], rooms(snapshot))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ha_manager/move",
        vol.Required("items"): vol.All([_ITEM], vol.Length(min=1, max=500)),
        vol.Required("area_id"): vol.Any(str, None),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_move(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Move things to a room. Logged, and can be undone."""
    coordinator, _ = await _snapshot(hass, connection, msg)
    if coordinator is None:
        return
    try:
        entry = await coordinator.async_move(msg["items"], msg["area_id"], connection.user.id)
    except ChangeError as err:
        connection.send_error(msg["id"], "change_failed", str(err))
        return
    connection.send_result(msg["id"], {"change": entry, "rooms": rooms(coordinator.snapshot)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ha_manager/set_floor",
        vol.Required("area_id"): str,
        vol.Required("floor_id"): vol.Any(str, None),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_floor(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Put a room on a floor. Logged, and can be undone."""
    coordinator, _ = await _snapshot(hass, connection, msg)
    if coordinator is None:
        return
    try:
        entry = await coordinator.async_set_floor(msg["area_id"], msg["floor_id"], connection.user.id)
    except ChangeError as err:
        connection.send_error(msg["id"], "change_failed", str(err))
        return
    connection.send_result(msg["id"], {"change": entry, "rooms": rooms(coordinator.snapshot)})


@websocket_api.websocket_command({vol.Required("type"): "ha_manager/names"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_names(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Names that could be clearer."""
    coordinator, _ = await _snapshot(hass, connection, msg)
    if coordinator is not None:
        connection.send_result(msg["id"], _names(coordinator))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ha_manager/set_naming_style",
        vol.Required("style"): vol.In(NAMING_STYLES),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_naming_style(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Choose the naming style to check against."""
    coordinator, _ = await _snapshot(hass, connection, msg)
    if coordinator is None:
        return
    await coordinator.async_set_naming_style(msg["style"])
    connection.send_result(msg["id"], _names(coordinator))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ha_manager/rename",
        vol.Required("items"): vol.All([_RENAME_ITEM], vol.Length(min=1, max=500)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_rename(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Rename things. Friendly names only. Logged, and can be undone."""
    coordinator, _ = await _snapshot(hass, connection, msg)
    if coordinator is None:
        return
    try:
        entry = await coordinator.async_rename(msg["items"], connection.user.id)
    except ChangeError as err:
        connection.send_error(msg["id"], "change_failed", str(err))
        return
    connection.send_result(msg["id"], {"change": entry, "names": _names(coordinator)})


@websocket_api.websocket_command({vol.Required("type"): "ha_manager/changes"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_changes(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """The change log, newest first."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    users = {user.id: user.name for user in await hass.auth.async_get_users()}
    connection.send_result(
        msg["id"],
        [{**entry, "user": users.get(entry.get("user_id"))} for entry in coordinator.changes.as_list()],
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "ha_manager/undo", vol.Required("change_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_undo(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Undo one entry in the change log."""
    coordinator, _ = await _snapshot(hass, connection, msg)
    if coordinator is None:
        return
    try:
        result = await coordinator.async_undo(msg["change_id"])
    except ChangeError as err:
        connection.send_error(msg["id"], "change_failed", str(err))
        return
    connection.send_result(msg["id"], result)
