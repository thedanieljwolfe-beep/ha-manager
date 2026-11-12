"""End-to-end tests for the explainer, weekly report, floor plan and batteries."""

from datetime import timedelta

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.ha_manager.const import DOMAIN


async def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="HA Manager")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_explain_report_and_plan(hass: HomeAssistant, hass_ws_client, hass_storage) -> None:
    hass.states.async_set("light.hall", "on", {"friendly_name": "Hall Light"})
    hass.states.async_set("binary_sensor.hall", "off", {"friendly_name": "Hall Motion"})
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "a1",
                "alias": "Hall light",
                "trigger": {"platform": "state", "entity_id": "binary_sensor.hall", "to": "on"},
                "action": {"action": "light.turn_on", "target": {"entity_id": "light.hall"}},
            }
        },
    )
    kitchen = ar.async_get(hass).async_create("Kitchen")
    light = er.async_get(hass).async_get_or_create("light", "test", "k1", suggested_object_id="kitchen")
    er.async_get(hass).async_update_entity(light.entity_id, area_id=kitchen.id)
    hass.states.async_set(light.entity_id, "on")

    entry = await _entry(hass)
    coordinator = entry.runtime_data
    client = await hass_ws_client(hass)

    async def call(**message):
        await client.send_json_auto_id(message)
        return await client.receive_json()

    await call(type="ha_manager/scan", refresh=True)

    # Rule-based explanation, no AI configured.
    result = (await call(type="ha_manager/explain", entity_id="automation.hall_light"))["result"]
    assert result["summary"] == "When Hall Motion turns on, it turns on Hall Light."
    assert result["ai_available"] is False
    assert not (await call(type="ha_manager/explain", entity_id="automation.nope"))["success"]

    # With an AI Task service available, its answer is used and then remembered.
    asked: list[ServiceCall] = []

    async def fake_ai(service_call: ServiceCall):
        asked.append(service_call)
        return {"data": "Turns the hall light on when someone walks past."}

    hass.services.async_register(
        "ai_task", "generate_data", fake_ai, supports_response=SupportsResponse.ONLY
    )
    result = (await call(type="ha_manager/explain", entity_id="automation.hall_light", ai=True))["result"]
    assert result["ai_text"] == "Turns the hall light on when someone walks past."
    assert "Hall Motion" in asked[0].data["instructions"]
    result = (await call(type="ha_manager/explain", entity_id="automation.hall_light"))["result"]
    assert result["ai_text"] and len(asked) == 1

    # Weekly report: settings, try-out send, then the scheduled one.
    notified = async_mock_service(hass, "notify", "mobile_app_phone")
    report = (await call(type="ha_manager/report"))["result"]
    assert report["settings"] == {"enabled": True, "weekday": 6, "hour": 18, "notify": None}
    assert report["notify_services"] == ["mobile_app_phone"]
    assert report["preview"]["headline"].startswith("Health score")
    report = (
        await call(type="ha_manager/report/settings", enabled=True, weekday=2, hour=7, notify="mobile_app_phone")
    )["result"]
    assert report["settings"]["weekday"] == 2

    report = (await call(type="ha_manager/report/send"))["result"]
    await hass.async_block_till_done()
    assert report["last"]["title"].startswith("HA Manager weekly report")
    assert report["history"] == []  # a try-out does not count as a week
    assert len(notified) == 1 and "Health score" in notified[0].data["message"]

    await coordinator.async_send_report(week="2026-W46")
    await hass.async_block_till_done()
    report = (await call(type="ha_manager/report"))["result"]
    assert len(report["history"]) == 1
    assert "no change on last week" in report["preview"]["headline"]
    assert hass_storage[DOMAIN]["data"]["report"]["last_sent_week"] == "2026-W46"

    # Floor plan: live data, save positions and a picture, reject a bad picture.
    plan = (await call(type="ha_manager/plan"))["result"]
    assert plan["areas"][0]["lights"] == [light.entity_id]
    assert plan["layouts"] == {}
    image = "data:image/jpeg;base64,AAAA"
    layouts = (
        await call(type="ha_manager/plan/save", floor="_none", positions={kitchen.id: [25, 140]}, image=image)
    )["result"]
    assert layouts["_none"] == {"image": image, "positions": {kitchen.id: [25.0, 100.0]}}
    layouts = (await call(type="ha_manager/plan/save", floor="_none", positions={kitchen.id: [10, 10]}))["result"]
    assert layouts["_none"]["image"] == image
    assert not (await call(type="ha_manager/plan/save", floor="_none", image="http://example.com/x.png"))["success"]
    assert hass_storage[f"{DOMAIN}_plan"]["data"]["_none"]["positions"][kitchen.id] == [10.0, 10.0]


async def test_battery_history_backfilled_from_statistics(
    recorder_mock: Recorder, hass: HomeAssistant, hass_ws_client
) -> None:
    battery = er.async_get(hass).async_get_or_create(
        "sensor", "test", "b1", suggested_object_id="door_battery", original_device_class="battery"
    )
    hass.states.async_set(battery.entity_id, "40", {"friendly_name": "Door Battery"})

    # Thirty days of history in long-term statistics: 100% falling 2 a day.
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(days=30)
    async_import_statistics(
        hass,
        {
            "source": "recorder",
            "statistic_id": battery.entity_id,
            "name": None,
            "unit_of_measurement": "%",
            "has_sum": False,
            "mean_type": StatisticMeanType.ARITHMETIC,
            "unit_class": None,
        },
        [{"start": start + timedelta(days=day), "mean": 100 - 2 * day} for day in range(30)],
    )
    await async_wait_recording_done(hass)

    await _entry(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "ha_manager/scan", "refresh": True})
    result = (await client.receive_json())["result"]

    door = result["batteries"][0]
    assert door["name"] == "Door Battery"
    assert door["status"] == "forecast"
    assert 1.8 <= door["rate_per_day"] <= 2.2
    assert 15 <= door["days_left"] <= 25
    assert door["days_of_data"] >= 28
