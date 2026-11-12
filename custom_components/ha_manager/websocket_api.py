"""Websocket commands used by the HA Manager panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .analysis import blast_radius, targets
from .const import DOMAIN


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
    for command in (ws_scan, ws_targets, ws_blast_radius, ws_log_test, ws_exclude, ws_ignore):
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
