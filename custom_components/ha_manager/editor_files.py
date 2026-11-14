"""Read and change automations.yaml and scripts.yaml.

These are the files Home Assistant's own automation and script editors save
to. Removing an automation here does exactly what the bin icon in Home
Assistant's editor does: take its entry out of the file, then reload. HA
Manager also keeps a copy of the entry in the Captain's Log, so it can be put
back.

Anything written by hand in other YAML files is never touched.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump, load_yaml

FILES = {"automation": "automations.yaml", "script": "scripts.yaml"}

_LOCK = asyncio.Lock()


class EditorFileError(HomeAssistantError):
    """The file could not be read or changed."""


def _read(path: str) -> Any:
    if not os.path.isfile(path):
        return None
    return load_yaml(path)


def _write(path: str, data: Any) -> None:
    write_utf8_file_atomic(path, dump(data))


async def _async_load(hass: HomeAssistant, kind: str) -> Any:
    path = hass.config.path(FILES[kind])
    try:
        data = await hass.async_add_executor_job(_read, path)
    except Exception as err:  # noqa: BLE001
        raise EditorFileError(f"Could not read {FILES[kind]}: {err}") from err
    if data is None:
        return [] if kind == "automation" else {}
    if kind == "automation" and not isinstance(data, list):
        raise EditorFileError("automations.yaml is not laid out the usual way, so it was left alone")
    if kind == "script" and not isinstance(data, dict):
        raise EditorFileError("scripts.yaml is not laid out the usual way, so it was left alone")
    return data


def _find(kind: str, data: Any, key: str) -> int | str | None:
    """Where the entry sits: a list index for automations, a key for scripts."""
    if kind == "script":
        return key if key in data else None
    for index, item in enumerate(data):
        if isinstance(item, dict) and str(item.get("id")) == key:
            return index
    return None


async def async_editor_keys(hass: HomeAssistant) -> dict[str, set[str]]:
    """The ids of every automation and script that the editor manages."""
    result: dict[str, set[str]] = {}
    for kind in FILES:
        try:
            data = await _async_load(hass, kind)
        except EditorFileError:
            result[kind] = set()
            continue
        if kind == "automation":
            result[kind] = {
                str(item["id"]) for item in data if isinstance(item, dict) and "id" in item
            }
        else:
            result[kind] = {str(key) for key in data}
    return result


async def async_take_out(hass: HomeAssistant, kind: str, key: str) -> dict[str, Any]:
    """Remove one entry from its file, reload, and return what was removed."""
    async with _LOCK:
        data = await _async_load(hass, kind)
        where = _find(kind, data, key)
        if where is None:
            raise EditorFileError(
                f"It is not in {FILES[kind]}, so it was probably written by hand in "
                "another file. Remove it there instead."
            )
        removed = data.pop(where)
        try:
            await hass.async_add_executor_job(_write, hass.config.path(FILES[kind]), data)
        except Exception as err:  # noqa: BLE001
            raise EditorFileError(f"Could not save {FILES[kind]}: {err}") from err
    # The same clean-up Home Assistant's editor does after deleting.
    registry = er.async_get(hass)
    if entity_id := registry.async_get_entity_id(kind, kind, key):
        registry.async_remove(entity_id)
    await _async_reload(hass, kind)
    return removed


async def async_put_back(hass: HomeAssistant, kind: str, key: str, config: dict[str, Any]) -> None:
    """Put a removed entry back in its file and reload."""
    async with _LOCK:
        data = await _async_load(hass, kind)
        if _find(kind, data, key) is not None:
            raise EditorFileError("Something with the same id has been added since")
        if kind == "script":
            data[key] = config
        else:
            data.append(config)
        try:
            await hass.async_add_executor_job(_write, hass.config.path(FILES[kind]), data)
        except Exception as err:  # noqa: BLE001
            raise EditorFileError(f"Could not save {FILES[kind]}: {err}") from err
    await _async_reload(hass, kind)


async def _async_reload(hass: HomeAssistant, kind: str) -> None:
    if hass.services.has_service(kind, "reload"):
        await hass.services.async_call(kind, "reload", blocking=True)
