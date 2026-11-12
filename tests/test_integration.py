"""End-to-end tests against a real Home Assistant instance."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_manager.const import DOMAIN


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    hass.states.async_set("light.kitchen", "on", {"friendly_name": "Kitchen Light"})
    hass.states.async_set("sensor.lux", "5")

    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "goodnight": {
                    "alias": "Goodnight",
                    "sequence": [
                        {"action": "light.turn_off", "target": {"entity_id": "light.kitchen"}}
                    ],
                }
            }
        },
    )
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "id": "motion1",
                    "alias": "Kitchen motion",
                    "trigger": {"platform": "state", "entity_id": "binary_sensor.gone", "to": "on"},
                    "condition": "{{ states('sensor.lux') | int < 10 and is_state('sensor.typo', 'x') }}",
                    "action": [
                        {"action": "light.turn_on", "target": {"entity_id": "light.kitchen"}},
                        {"action": "script.goodnight"},
                        {"action": "script.not_a_script"},
                    ],
                },
                {
                    "id": "busy1",
                    "alias": "Busy",
                    "trigger": {"platform": "event", "event_type": "poke"},
                    "action": [],
                },
            ]
        },
    )
    assert await async_setup_component(
        hass,
        "scene",
        {"scene": [{"id": "s1", "name": "Movie", "entities": {"light.kitchen": "on", "light.missing": "on"}}]},
    )
    assert await async_setup_component(
        hass, "group", {"group": {"downstairs": {"entities": ["light.kitchen", "light.nope"]}}}
    )

    entry = MockConfigEntry(domain=DOMAIN, title="HA Manager")
    entry.add_to_hass(hass)

    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("test", "smoke")}, name="Hall Smoke Alarm"
    )
    entities = er.async_get(hass)
    smoke = entities.async_get_or_create(
        "binary_sensor", "test", "smoke1", device_id=device.id, original_device_class="smoke",
        suggested_object_id="hall_smoke",
    )
    hass.states.async_set(smoke.entity_id, "unavailable")
    # An entity whose integration has been removed.
    entities.async_get_or_create("sensor", "ghosts", "g1", suggested_object_id="ghost")
    hass.states.async_set("sensor.ghost", "unavailable", {"restored": True})

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_full_scan(hass: HomeAssistant, hass_ws_client, hass_storage) -> None:
    entry = await _setup(hass)
    assert "ha-manager" in hass.data["frontend_panels"]

    for _ in range(3):
        hass.bus.async_fire("poke")
        await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "ha_manager/scan", "refresh": True})
    response = await client.receive_json()
    assert response["success"], response
    result = response["result"]
    found = {f["id"]: f for f in result["findings"]}

    motion = found["missing_ref:automation:automation.kitchen_motion"]
    notes = {i["name"]: i["note"] for i in motion["items"]}
    assert notes == {
        "binary_sensor.gone": "does not exist",
        "script.not_a_script": "script does not exist",
        "sensor.typo": "mentioned in a template, does not exist",
    }
    assert motion["link"] == "/config/automation/edit/motion1"
    assert [i["name"] for i in found["missing_ref:scene:scene.movie"]["items"]] == ["light.missing"]
    assert [i["name"] for i in found["missing_ref:group:group.downstairs"]["items"]] == ["light.nope"]
    assert "missing_ref:script:script.goodnight" not in found
    assert found["safety_offline:" + result["safety"]["units"][0]["id"]]["severity"] == "critical"
    assert "orphans:ghosts" in found
    assert result["totals"]["automations"] == 2
    assert result["sources"]["counting_since"]

    activity = {row["entity_id"]: row for row in result["activity"]}
    assert activity["automation.busy"]["triggers_24h"] == 3
    assert activity["automation.busy"]["status"] == "ok"
    assert activity["automation.kitchen_motion"]["triggers_24h"] == 0

    state = hass.states.get("sensor.ha_manager_health_score")
    assert int(float(state.state)) == result["score"]["value"]
    assert state.attributes["critical"] == 1

    # Blast radius.
    await client.send_json_auto_id(
        {"type": "ha_manager/blast_radius", "target_type": "entity", "target_id": "light.kitchen"}
    )
    blast = (await client.receive_json())["result"]
    assert {u["id"] for u in blast["used_by"]} == {
        "automation.kitchen_motion", "script.goodnight", "scene.movie", "group.downstairs",
    }
    await client.send_json_auto_id({"type": "ha_manager/targets"})
    targets = (await client.receive_json())["result"]
    assert any(t["id"] == "light.kitchen" for t in targets)

    # Log a test, ignore a finding, exclude a device: all saved and applied at once.
    unit_id = result["safety"]["units"][0]["id"]
    await client.send_json_auto_id({"type": "ha_manager/safety/log_test", "unit_id": unit_id})
    result = (await client.receive_json())["result"]
    assert result["safety"]["units"][0]["test_count"] == 1
    assert "safety_tests_due" not in {f["id"] for f in result["findings"]}

    await client.send_json_auto_id(
        {"type": "ha_manager/ignore", "finding_id": "orphans:ghosts", "ignored": True}
    )
    result = (await client.receive_json())["result"]
    assert [f["id"] for f in result["ignored"]] == ["orphans:ghosts"]

    await client.send_json_auto_id(
        {"type": "ha_manager/safety/set_excluded", "unit_id": unit_id, "excluded": True}
    )
    result = (await client.receive_json())["result"]
    assert result["safety"]["units"][0]["status"] == "excluded"
    assert entry.runtime_data.saved["safety_excluded"] == [unit_id]

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert sum(hass_storage[DOMAIN]["data"]["triggers"]["automation.busy"].values()) == 3
    assert "ha-manager" not in hass.data["frontend_panels"]


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
