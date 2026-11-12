"""End-to-end tests for rooms, renames, the change log and undo."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_manager.const import DOMAIN


async def _setup(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, title="HA Manager")
    entry.add_to_hass(hass)
    areas = ar.async_get(hass)
    floors = fr.async_get(hass)
    ground = floors.async_create("Ground", level=0)
    kitchen = areas.async_create("Kitchen", floor_id=ground.floor_id)
    lounge = areas.async_create("Lounge")
    devices = dr.async_get(hass)
    entities = er.async_get(hass)

    def device(key: str, name: str, area_id: str | None):
        dev = devices.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={("test", key)}, name=name
        )
        if area_id:
            devices.async_update_device(dev.id, area_id=area_id)
        ent = entities.async_get_or_create("light", "test", key, device_id=dev.id)
        hass.states.async_set(ent.entity_id, "on")
        return dev

    lamp = device("lamp", "Lamp", None)
    plug = device("plug", "TS0601_plug", kitchen.id)
    helper = entities.async_get_or_create(
        "input_boolean", "input_boolean", "guest", suggested_object_id="guest_mode"
    )
    hass.states.async_set(helper.entity_id, "off", {"friendly_name": "guest_mode"})

    backup = entities.async_get_or_create(
        "sensor", "backup", "last_successful_automatic_backup",
        suggested_object_id="backup_last_successful_automatic_backup",
    )
    hass.states.async_set(backup.entity_id, (dt_util.utcnow() - timedelta(days=20)).isoformat())

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, kitchen, lounge, ground, lamp, plug, helper


async def test_rooms_rename_log_and_undo(hass: HomeAssistant, hass_ws_client, hass_storage) -> None:
    entry, kitchen, lounge, ground, lamp, plug, helper = await _setup(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    client = await hass_ws_client(hass)

    async def call(**message):
        await client.send_json_auto_id(message)
        response = await client.receive_json()
        return response

    # Backup warning and the names summary appear on the overview.
    scan = (await call(type="ha_manager/scan", refresh=True))["result"]
    found = {f["id"]: f for f in scan["findings"]}
    assert "20 days ago" in found["backup_old"]["title"]
    assert found["names"]["severity"] == "tidy"

    # Rooms tab data.
    rooms = (await call(type="ha_manager/rooms"))["result"]
    assert [f["name"] for f in rooms["floors"]] == ["Ground"]
    assert {a["name"]: a["floor_id"] for a in rooms["areas"]} == {
        "Kitchen": ground.floor_id, "Lounge": None,
    }
    by_name = {i["name"]: i for i in rooms["items"]}
    assert by_name["Lamp"]["area_id"] is None
    assert by_name["Lamp"]["detail"] == "1 entity"
    assert by_name["guest_mode"]["type"] == "entity"

    # Move a device and a helper into the lounge in one go.
    response = await call(
        type="ha_manager/move",
        items=[{"type": "device", "id": lamp.id}, {"type": "entity", "id": helper.entity_id}],
        area_id=lounge.id,
    )
    move = response["result"]["change"]
    assert move["summary"] == "Moved 2 things to Lounge"
    assert [(i["before_text"], i["after_text"]) for i in move["items"]] == [("No room", "Lounge")] * 2
    assert devices.async_get(lamp.id).area_id == lounge.id
    assert entities.async_get(helper.entity_id).area_id == lounge.id
    assert {i["name"]: i["area_id"] for i in response["result"]["rooms"]["items"]}["Lamp"] == lounge.id

    # Moving to where it already is does nothing and logs nothing.
    response = await call(
        type="ha_manager/move", items=[{"type": "device", "id": lamp.id}], area_id=lounge.id
    )
    assert response["result"]["change"]["items"] == []

    # A bad room is refused and nothing changes.
    response = await call(
        type="ha_manager/move", items=[{"type": "device", "id": plug.id}], area_id="nowhere"
    )
    assert not response["success"]
    assert devices.async_get(plug.id).area_id == kitchen.id

    # Put the lounge on a floor.
    response = await call(type="ha_manager/set_floor", area_id=lounge.id, floor_id=ground.floor_id)
    assert ar.async_get(hass).async_get_area(lounge.id).floor_id == ground.floor_id

    # Names: suggestions, then rename.
    names = (await call(type="ha_manager/names"))["result"]
    issues = {i["id"]: i for i in names["issues"]}
    assert issues[plug.id]["suggestion"] == "Kitchen Plug"
    assert issues[lamp.id]["suggestion"] == "Lounge Lamp"
    names = (await call(type="ha_manager/set_naming_style", style="no_room"))["result"]
    assert {i["id"]: i for i in names["issues"]}[plug.id]["suggestion"] == "Plug"
    await call(type="ha_manager/set_naming_style", style="room_first")

    response = await call(
        type="ha_manager/rename",
        items=[
            {"type": "device", "id": plug.id, "name": "  Kitchen   Plug "},
            {"type": "entity", "id": helper.entity_id, "name": "Lounge Guest Mode"},
        ],
    )
    rename = response["result"]["change"]
    assert devices.async_get(plug.id).name_by_user == "Kitchen Plug"
    assert devices.async_get(plug.id).name == "TS0601_plug"
    assert entities.async_get(helper.entity_id).name == "Lounge Guest Mode"
    assert plug.id not in {i["id"] for i in response["result"]["names"]["issues"]}
    response = await call(type="ha_manager/rename", items=[{"type": "device", "id": plug.id, "name": " "}])
    assert not response["success"]

    # The log has it all, newest first, with who did it.
    log = (await call(type="ha_manager/changes"))["result"]
    assert [e["summary"] for e in log] == [
        "Renamed 2 things", "Changed the floor for Lounge", "Moved 2 things to Lounge",
    ]
    assert log[0]["user"]
    assert hass_storage[f"{DOMAIN}_changes"]["data"]["entries"][0]["id"] == move["id"]

    # Someone changes the plug's name again elsewhere: undo leaves that one alone.
    devices.async_update_device(plug.id, name_by_user="Kettle Plug")
    result = (await call(type="ha_manager/undo", change_id=rename["id"]))["result"]
    assert result["reverted"] == 1
    assert [s["label"] for s in result["skipped"]] == ["TS0601_plug"]
    assert devices.async_get(plug.id).name_by_user == "Kettle Plug"
    assert entities.async_get(helper.entity_id).name is None

    # Undo the move: both go back to having no room.
    result = (await call(type="ha_manager/undo", change_id=move["id"]))["result"]
    assert result == {"reverted": 2, "skipped": []}
    assert devices.async_get(lamp.id).area_id is None
    assert entities.async_get(helper.entity_id).area_id is None

    # Cannot undo twice.
    assert not (await call(type="ha_manager/undo", change_id=move["id"]))["success"]
    log = (await call(type="ha_manager/changes"))["result"]
    assert [bool(e["undone"]) for e in log] == [True, False, True]

    # The log survives a reload.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len((await call(type="ha_manager/changes"))["result"]) == 3
