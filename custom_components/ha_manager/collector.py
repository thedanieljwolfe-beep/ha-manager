"""Read the current Home Assistant setup into a Snapshot.

Everything here is read-only. Each source is wrapped so that one integration
behaving oddly cannot stop the whole scan.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.const import ATTR_ENTITY_ID, ATTR_RESTORED
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    issue_registry as ir,
)
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .models import Consumer, DeviceInfo, EntityInfo, RepairIssue, Snapshot
from .references import extract_references

_LOGGER = logging.getLogger(__name__)

# Entity domains that always count as "known" when reading configs.
BASE_DOMAINS = {
    "alarm_control_panel", "automation", "binary_sensor", "button", "calendar",
    "camera", "climate", "cover", "device_tracker", "event", "fan", "group",
    "humidifier", "input_boolean", "input_button", "input_datetime",
    "input_number", "input_select", "input_text", "lawn_mower", "light", "lock",
    "media_player", "number", "person", "remote", "scene", "script", "select",
    "sensor", "siren", "sun", "switch", "timer", "todo", "update", "vacuum",
    "valve", "water_heater", "weather", "zone",
}

WATCHMAN_SENSORS = {
    "sensor.watchman_missing_entities": "missing entities",
    "sensor.watchman_missing_actions": "missing actions",
    "sensor.watchman_missing_services": "missing actions",
}


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return dt_util.parse_datetime(value)
    return None


def _collect_entities(hass: HomeAssistant, snapshot: Snapshot) -> None:
    devices = dr.async_get(hass)
    for area in ar.async_get(hass).async_list_areas():
        snapshot.areas[area.id] = area.name
        snapshot.area_floors[area.id] = area.floor_id
    for floor in fr.async_get(hass).async_list_floors():
        snapshot.floors[floor.floor_id] = {"name": floor.name, "level": floor.level}

    for device in devices.devices.values():
        entry_ids = getattr(device, "config_entries", set())
        snapshot.devices[device.id] = DeviceInfo(
            device_id=device.id,
            name=device.name_by_user or device.name or "Unnamed device",
            area_id=device.area_id,
            disabled=device.disabled_by is not None,
            is_service=str(device.entry_type or "") == "service",
            orphaned=bool(entry_ids)
            and not any(hass.config_entries.async_get_entry(e) for e in entry_ids),
            user_name=device.name_by_user,
        )

    def last_seen(state: State | None) -> datetime | None:
        if state is None:
            return None
        return getattr(state, "last_reported", None) or state.last_updated

    seen: set[str] = set()
    for entry in er.async_get(hass).entities.values():
        seen.add(entry.entity_id)
        state = hass.states.get(entry.entity_id)
        device = snapshot.devices.get(entry.device_id or "")
        orphaned = (
            entry.config_entry_id is not None
            and hass.config_entries.async_get_entry(entry.config_entry_id) is None
        ) or bool(state and state.attributes.get(ATTR_RESTORED))
        members = state.attributes.get(ATTR_ENTITY_ID) if state else None
        snapshot.entities[entry.entity_id] = EntityInfo(
            entity_id=entry.entity_id,
            name=(state.name if state else None)
            or entry.name
            or entry.original_name
            or entry.entity_id,
            state=state.state if state else None,
            device_id=entry.device_id,
            area_id=entry.area_id or (device.area_id if device else None),
            platform=entry.platform,
            device_class=entry.device_class
            or entry.original_device_class
            or (state.attributes.get("device_class") if state else None),
            entity_category=str(entry.entity_category) if entry.entity_category else None,
            labels=set(entry.labels),
            disabled=entry.disabled_by is not None,
            hidden=entry.hidden_by is not None,
            orphaned=orphaned,
            registry_name=entry.name,
            last_seen=last_seen(state),
            members=list(members) if isinstance(members, (list, tuple)) else None,
        )
        if entry.platform == "backup" and entry.unique_id == "last_successful_automatic_backup":
            snapshot.backup_known = entry.disabled_by is None
            snapshot.last_backup = _as_datetime(state.state) if state else None

    for state in hass.states.async_all():
        if state.entity_id in seen:
            continue
        members = state.attributes.get(ATTR_ENTITY_ID)
        snapshot.entities[state.entity_id] = EntityInfo(
            entity_id=state.entity_id,
            name=state.name,
            state=state.state,
            device_class=state.attributes.get("device_class"),
            in_registry=False,
            orphaned=bool(state.attributes.get(ATTR_RESTORED)),
            last_seen=last_seen(state),
            members=list(members) if isinstance(members, (list, tuple)) else None,
        )


def _known_domains(snapshot: Snapshot) -> set[str]:
    return BASE_DOMAINS | {entity.domain for entity in snapshot.entities.values()}


def _raw_configs(hass: HomeAssistant, domain: str) -> dict[str, Any]:
    """Return {entity_id: raw config} for automations or scripts."""
    component = hass.data.get(domain)
    result: dict[str, Any] = {}
    for entity in getattr(component, "entities", []) or []:
        raw = getattr(entity, "raw_config", None)
        if raw:
            result[entity.entity_id] = raw
    return result


def _collect_automations_and_scripts(hass: HomeAssistant, snapshot: Snapshot) -> None:
    # Imported here so a missing integration cannot stop this module loading.
    from homeassistant.components import automation, script  # noqa: PLC0415

    domains = _known_domains(snapshot)
    registry = er.async_get(hass)
    lookups = {
        "automation": (
            automation.entities_in_automation,
            automation.devices_in_automation,
            automation.areas_in_automation,
        ),
        "script": (
            script.entities_in_script,
            script.devices_in_script,
            script.areas_in_script,
        ),
    }
    for kind, (entities_in, devices_in, areas_in) in lookups.items():
        raw_configs = _raw_configs(hass, kind)
        for state in hass.states.async_all(kind):
            entity_id = state.entity_id
            consumer = Consumer(
                kind=kind,
                id=entity_id,
                name=state.name,
                state=state.state,
                last_triggered=_as_datetime(state.attributes.get("last_triggered")),
            )
            try:
                consumer.entities = set(entities_in(hass, entity_id))
                consumer.devices = set(devices_in(hass, entity_id))
                consumer.areas = set(areas_in(hass, entity_id))
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Could not read references for %s", entity_id, exc_info=True)
            consumer.config = raw_configs.get(entity_id)
            refs = extract_references(consumer.config, domains)
            consumer.entities |= refs.explicit
            consumer.mentioned = refs.templated - consumer.entities
            consumer.scripts_called = refs.scripts_called
            consumer.entities.discard(entity_id)
            consumer.mentioned.discard(entity_id)

            entry = registry.async_get(entity_id)
            if kind == "automation":
                config_id = state.attributes.get("id") or (entry.unique_id if entry else None)
                if config_id:
                    consumer.edit_url = f"/config/automation/edit/{config_id}"
            elif entry or entity_id in raw_configs:
                consumer.edit_url = f"/config/script/edit/{entity_id.split('.', 1)[1]}"
            snapshot.consumers.append(consumer)


def _collect_scenes_and_groups(hass: HomeAssistant, snapshot: Snapshot) -> None:
    from homeassistant.components.homeassistant import scene  # noqa: PLC0415

    for state in hass.states.async_all("scene"):
        try:
            entities = set(scene.entities_in_scene(hass, state.entity_id))
        except Exception:  # noqa: BLE001
            entities = set()
        if not entities:
            members = state.attributes.get(ATTR_ENTITY_ID)
            entities = set(members) if isinstance(members, (list, tuple)) else set()
        scene_id = state.attributes.get("id")
        snapshot.consumers.append(
            Consumer(
                kind="scene",
                id=state.entity_id,
                name=state.name,
                state=state.state,
                entities=entities,
                edit_url=f"/config/scene/edit/{scene_id}" if scene_id else None,
            )
        )

    for entity in snapshot.entities.values():
        if entity.members is None or entity.domain in ("scene", "automation", "script"):
            continue
        if entity.disabled or entity.orphaned:
            continue
        snapshot.consumers.append(
            Consumer(
                kind="group",
                id=entity.entity_id,
                name=entity.name,
                state=entity.state,
                entities={m for m in entity.members if isinstance(m, str)} - {entity.entity_id},
            )
        )


async def _collect_dashboards(hass: HomeAssistant, snapshot: Snapshot) -> None:
    lovelace = hass.data.get("lovelace")
    dashboards = getattr(lovelace, "dashboards", None)
    if dashboards is None and isinstance(lovelace, dict):
        dashboards = lovelace.get("dashboards")
    if not dashboards:
        return
    domains = _known_domains(snapshot)
    for url_path, dashboard in dashboards.items():
        try:
            config = await dashboard.async_load(False)
        except Exception:  # noqa: BLE001 - no config means an auto-generated dashboard
            continue
        if not isinstance(config, dict) or "strategy" in config:
            continue
        refs = extract_references(config, domains)
        settings = getattr(dashboard, "config", None) or {}
        snapshot.consumers.append(
            Consumer(
                kind="dashboard",
                id=url_path or "lovelace",
                name=settings.get("title") or config.get("title") or "Overview",
                entities=refs.explicit,
                mentioned=refs.templated - refs.explicit,
                scripts_called=refs.scripts_called,
                edit_url=f"/{url_path or 'lovelace'}",
            )
        )


async def _collect_repairs(hass: HomeAssistant, snapshot: Snapshot) -> None:
    issues = [
        issue
        for issue in ir.async_get(hass).issues.values()
        if issue.active and issue.dismissed_version is None and issue.domain != DOMAIN
    ]
    if not issues:
        return
    owners = {issue.issue_domain or issue.domain for issue in issues}
    try:
        translations = await async_get_translations(
            hass, hass.config.language, "issues", owners
        )
    except Exception:  # noqa: BLE001
        translations = {}
    for issue in issues:
        owner = issue.issue_domain or issue.domain
        key = issue.translation_key or issue.issue_id
        title = translations.get(f"component.{owner}.issues.{key}.title")
        if title:
            for name, value in (issue.translation_placeholders or {}).items():
                title = title.replace(f"{{{name}}}", str(value))
        else:
            title = key.replace("_", " ").capitalize()
        snapshot.repairs.append(
            RepairIssue(
                domain=issue.domain,
                issue_id=issue.issue_id,
                title=title,
                severity=str(issue.severity.value if issue.severity else "warning"),
            )
        )


def _collect_watchman(hass: HomeAssistant, snapshot: Snapshot) -> None:
    counts: dict[str, int] = {}
    for entity_id, label in WATCHMAN_SENSORS.items():
        state = hass.states.get(entity_id)
        if state is None:
            continue
        try:
            counts[label] = int(float(state.state))
        except ValueError:
            counts.setdefault(label, 0)
    if counts:
        snapshot.watchman = counts


async def async_collect(hass: HomeAssistant) -> Snapshot:
    """Build a snapshot of the whole setup."""
    snapshot = Snapshot(now=dt_util.utcnow())
    _collect_entities(hass, snapshot)
    snapshot.services = {
        f"{domain}.{service}"
        for domain, services in hass.services.async_services().items()
        for service in services
    }
    steps = (
        ("automations and scripts", _collect_automations_and_scripts),
        ("scenes and groups", _collect_scenes_and_groups),
        ("watchman", _collect_watchman),
    )
    for label, step in steps:
        try:
            step(hass, snapshot)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("HA Manager could not read %s", label, exc_info=True)
    async_steps = (
        ("dashboards", _collect_dashboards),
        ("repairs", _collect_repairs),
    )
    for label, async_step in async_steps:
        try:
            await async_step(hass, snapshot)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("HA Manager could not read %s", label, exc_info=True)
    return snapshot
