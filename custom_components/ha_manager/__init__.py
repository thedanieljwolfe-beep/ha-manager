"""HA Manager: an MOT for your Home Assistant setup."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.start import async_at_started

from .const import (
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
    STATIC_URL,
    VERSION,
)
from .coordinator import HAManagerConfigEntry, HAManagerCoordinator
from .websocket_api import async_register_commands

PLATFORMS = [Platform.SENSOR]
_STATIC_REGISTERED = f"{DOMAIN}_static_registered"


async def async_setup_entry(hass: HomeAssistant, entry: HAManagerConfigEntry) -> bool:
    """Set up HA Manager."""
    coordinator = HAManagerCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_start_counting())

    async_register_commands(hass)

    if not hass.data.get(_STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    STATIC_URL,
                    str(Path(__file__).parent / "frontend"),
                    cache_headers=False,
                )
            ]
        )
        hass.data[_STATIC_REGISTERED] = True

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"{STATIC_URL}/ha-manager-panel.js?v={VERSION}",
        require_admin=True,
        config={},
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # The first scan runs in the background so it never slows start-up, and
    # waits until Home Assistant has finished loading everything else.
    async def _first_scan(_hass: HomeAssistant) -> None:
        await coordinator.async_refresh()

    entry.async_on_unload(async_at_started(hass, _first_scan))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HAManagerConfigEntry) -> bool:
    """Unload HA Manager."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await entry.runtime_data.async_save()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
