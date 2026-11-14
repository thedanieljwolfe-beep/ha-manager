"""End-to-end tests for Tidy up: disable, ignore, the double-check and remove."""

from datetime import timedelta
from pathlib import Path

from homeassistant import config as conf_util
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_manager.const import DOMAIN

AUTOMATIONS = """
- id: "hall1"
  alias: Hall light on
  triggers: [{trigger: state, entity_id: binary_sensor.hall_motion, to: "on"}]
  actions: [{action: light.turn_on, target: {entity_id: light.hall}}]
- id: "hall2"
  alias: Hall light on (copy)
  triggers: [{trigger: state, entity_id: binary_sensor.hall_motion, to: "on"}]
  actions: [{action: light.turn_on, target: {entity_id: light.hall}}]
- id: "uses_helper"
  alias: Calls the helper script
  triggers: [{trigger: event, event_type: poke}]
  actions: [{action: script.helper}]
"""

SCRIPTS = """
helper:
  alias: Helper
  sequence: [{action: light.turn_off, target: {entity_id: light.hall}}]
forgotten:
  alias: Forgotten
  sequence: [{delay: 1}]
"""


async def _setup(hass: HomeAssistant, tmp_path: Path):
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text(
        "automation: !include automations.yaml\nscript: !include scripts.yaml\n"
    )
    (tmp_path / "automations.yaml").write_text(AUTOMATIONS)
    (tmp_path / "scripts.yaml").write_text(SCRIPTS)
    hass.states.async_set("light.hall", "off")
    config = await conf_util.async_hass_config_yaml(hass)
    assert await async_setup_component(hass, "automation", config)
    assert await async_setup_component(hass, "script", config)

    entry = MockConfigEntry(domain=DOMAIN, title="HA Manager")
    entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)

    # A plug that has been unavailable for a month, with its own config entry.
    plug_entry = MockConfigEntry(domain="test")
    plug_entry.add_to_hass(hass)
    plug = devices.async_get_or_create(
        config_entry_id=plug_entry.entry_id, identifiers={("test", "plug")}, name="Old Plug"
    )
    plug_switch = entities.async_get_or_create(
        "switch", "test", "plug", device_id=plug.id, config_entry=plug_entry,
        suggested_object_id="old_plug",
    )
    hass.states.async_set(plug_switch.entity_id, "unavailable")

    # An entity left behind by an integration that has been removed.
    entities.async_get_or_create("sensor", "ghosts", "g1", suggested_object_id="ghost")
    hass.states.async_set("sensor.ghost", "unavailable", {"restored": True})

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    # Pretend HA Manager first saw the plug unavailable a month ago.
    coordinator.saved["unavailable_since"][plug_switch.entity_id] = (
        dt_util.utcnow() - timedelta(days=30)
    ).isoformat()
    return entry, plug, plug_switch


async def test_tidy_flow(hass: HomeAssistant, hass_ws_client, tmp_path: Path) -> None:
    entry, plug, plug_switch = await _setup(hass, tmp_path)
    client = await hass_ws_client(hass)
    entities = er.async_get(hass)

    async def call(**message):
        await client.send_json_auto_id(message)
        return await client.receive_json()

    scan = (await call(type="ha_manager/scan", refresh=True))["result"]
    assert scan["tidy"]["total"] >= 3

    tidy = (await call(type="ha_manager/tidy"))["result"]
    # The two identical automations are a duplicate set, the older one marked to keep.
    sets = tidy["duplicates"]
    assert len(sets) == 1
    assert sorted(sets[0]["keys"]) == ["automation:automation.hall_light_on", "automation:automation.hall_light_on_copy"]
    assert "exactly the same settings" in sets[0]["title"]
    # The plug is offline for 30 days; the ghost is a leftover; the forgotten script is unused.
    offline = {i["key"] for i in tidy["groups"]["offline"]}
    assert f"device:{plug.id}" in offline
    leftover = {i["key"]: i for i in tidy["groups"]["leftover"]}
    assert leftover["entity:sensor.ghost"]["can_remove"]
    unused = {i["key"]: i for i in tidy["groups"]["unused"]}
    assert "script:script.forgotten" in unused
    # The helper script is used by an automation, so it is not "unused".
    assert "script:script.helper" not in unused

    # The double-check: the helper script is used, so removal is blocked.
    check = (await call(type="ha_manager/tidy/check", keys=["script:script.helper"]))["result"]
    assert [u["name"] for u in check["items"][0]["used_by"]] == ["Calls the helper script"]
    result = (await call(type="ha_manager/tidy/apply", action="remove", keys=["script:script.helper"]))["result"]
    assert result["change"] is None
    assert result["skipped"][0]["reason"].startswith("Still used by Calls the helper script")
    assert "helper" in load_yaml(str(tmp_path / "scripts.yaml"))

    # ...but removing it together with the only thing that uses it is fine.
    check = (
        await call(
            type="ha_manager/tidy/check",
            keys=["script:script.helper", "automation:automation.calls_the_helper_script"],
        )
    )["result"]
    assert all(not i["used_by"] for i in check["items"])

    # Remove the copy automation: gone from the file, logged, and can be undone.
    result = (
        await call(type="ha_manager/tidy/apply", action="remove", keys=["automation:automation.hall_light_on_copy"])
    )["result"]
    assert result["skipped"] == []
    change = result["change"]
    assert change["summary"] == "Removed 'Hall light on (copy)'"
    ids = [a["id"] for a in load_yaml(str(tmp_path / "automations.yaml"))]
    assert ids == ["hall1", "uses_helper"]
    await hass.async_block_till_done()
    assert hass.states.get("automation.hall_light_on_copy") is None
    assert result["tidy"]["duplicates"] == []

    undo = (await call(type="ha_manager/undo", change_id=change["id"]))["result"]
    assert undo == {"reverted": 1, "skipped": []}
    await hass.async_block_till_done()
    ids = [a["id"] for a in load_yaml(str(tmp_path / "automations.yaml"))]
    assert ids == ["hall1", "uses_helper", "hall2"]
    assert hass.states.get("automation.hall_light_on_copy") is not None

    # Disable: switch an automation off, and disable the offline plug's device.
    result = (
        await call(
            type="ha_manager/tidy/apply",
            action="disable",
            keys=["automation:automation.hall_light_on_copy", f"device:{plug.id}"],
        )
    )["result"]
    assert result["change"]["summary"] == "Disabled 2 things"
    await hass.async_block_till_done()
    assert hass.states.get("automation.hall_light_on_copy").state == "off"
    assert dr.async_get(hass).async_get(plug.id).disabled_by is dr.DeviceEntryDisabler.USER
    undo = (await call(type="ha_manager/undo", change_id=result["change"]["id"]))["result"]
    assert undo["reverted"] == 2
    await hass.async_block_till_done()
    assert hass.states.get("automation.hall_light_on_copy").state == "on"
    assert dr.async_get(hass).async_get(plug.id).disabled_by is None

    # A live entity cannot be removed (it would come back), only disabled.
    result = (
        await call(type="ha_manager/tidy/apply", action="remove", keys=[f"entity:{plug_switch.entity_id}"])
    )["result"]
    assert result["change"] is None
    assert "come back" in result["skipped"][0]["reason"]

    # Remove the leftover entity and an unused script in one go, then undo
    # just the entity: a single item from a batch.
    entities.async_update_entity("sensor.ghost", name="Old ghost sensor")
    result = (
        await call(
            type="ha_manager/tidy/apply", action="remove",
            keys=["entity:sensor.ghost", "script:script.forgotten"],
        )
    )["result"]
    change = result["change"]
    assert [i["label"] for i in change["items"]] == ["ghost", "Forgotten"]
    assert all(i["undoable"] for i in change["items"])
    assert entities.async_get("sensor.ghost") is None
    assert hass.states.get("sensor.ghost") is None
    assert "forgotten" not in load_yaml(str(tmp_path / "scripts.yaml"))

    undo = (await call(type="ha_manager/undo", change_id=change["id"], item=0))["result"]
    assert undo == {"reverted": 1, "skipped": []}
    ghost = entities.async_get("sensor.ghost")
    assert ghost is not None and ghost.name == "Old ghost sensor" and ghost.platform == "ghosts"
    assert hass.states.get("sensor.ghost").attributes.get("restored")
    # The script is still removed, and the entry can still undo the rest.
    assert "forgotten" not in load_yaml(str(tmp_path / "scripts.yaml"))
    log = (await call(type="ha_manager/changes"))["result"]
    assert log[0]["undone"] is None and log[0]["items"][0]["undone"]
    again = await call(type="ha_manager/undo", change_id=change["id"], item=0)
    assert not again["success"]
    undo = (await call(type="ha_manager/undo", change_id=change["id"]))["result"]
    assert undo == {"reverted": 1, "skipped": []}
    await hass.async_block_till_done()
    assert "forgotten" in load_yaml(str(tmp_path / "scripts.yaml"))
    assert hass.states.get("script.forgotten") is not None

    # Ignore: the forgotten script stops being suggested, and can come back.
    result = (await call(type="ha_manager/tidy/ignore", keys=["script:script.forgotten"], ignored=True))["result"]
    assert "script:script.forgotten" not in {i["key"] for i in result["groups"]["unused"]}
    assert [i["key"] for i in result["ignored"]] == ["script:script.forgotten"]
    result = (await call(type="ha_manager/tidy/ignore", keys=["script:script.forgotten"], ignored=False))["result"]
    assert "script:script.forgotten" in {i["key"] for i in result["groups"]["unused"]}

    # The log shows the removals.
    log = (await call(type="ha_manager/changes"))["result"]
    assert [e["summary"] for e in log][:2] == ["Removed 2 things", "Disabled 2 things"]

    assert await hass.config_entries.async_unload(entry.entry_id)
