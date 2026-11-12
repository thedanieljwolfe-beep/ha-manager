"""Tests for the naming checker."""

from datetime import UTC, datetime

from custom_components.ha_manager.models import DeviceInfo, EntityInfo, Snapshot
from custom_components.ha_manager.naming import check_names, is_technical, tidy

NOW = datetime(2026, 11, 12, tzinfo=UTC)


def test_is_technical_and_tidy():
    assert is_technical("lumi.sensor_motion 0x00158d0001a2b3c4")
    assert is_technical("TS0601 Thermostat")
    assert is_technical("shelly1pm_kitchen")
    assert not is_technical("Kitchen Ceiling Light")
    assert not is_technical("Linn LP12")
    assert not is_technical("TV")
    assert tidy("shelly_plug_tv") == "Shelly Plug TV"
    assert tidy("TS0601 Thermostat") == "Thermostat"
    assert tidy("hall_pir 0x00158d0001a2b3c4") == "Hall PIR"


def make() -> Snapshot:
    snap = Snapshot(now=NOW)
    snap.areas = {"kitchen": "Kitchen", "lounge": "Lounge", "kd": "Kitchen Diner"}
    devices = [
        ("d1", "Kitchen Ceiling Light", "kitchen"),  # fine
        ("d2", "Lamp", "lounge"),  # duplicate + no room
        ("d3", "Lamp", "kitchen"),  # duplicate
        ("d4", "Kitchen Speaker", "lounge"),  # named after the wrong room
        ("d5", "TS0601_radiator", "lounge"),  # technical
        ("d6", "Table Light", "kd"),  # no room in name
        ("d7", "Kitchen Diner Blind", "kd"),  # fine, longest room name wins
        ("d8", "Loft Sensor", None),  # no room set, nothing to compare with
    ]
    for device_id, name, area in devices:
        snap.devices[device_id] = DeviceInfo(device_id, name, area_id=area)
    snap.devices["svc"] = DeviceInfo("svc", "Sun", is_service=True)
    snap.entities["input_boolean.guest_mode"] = EntityInfo(
        "input_boolean.guest_mode", "guest_mode", area_id="lounge"
    )
    snap.entities["sensor.on_device"] = EntityInfo("sensor.on_device", "x_y", device_id="d1")
    snap.entities["sensor.helper"] = EntityInfo("sensor.helper", "odd_name")  # not a named domain
    return snap


def test_room_first_style():
    issues = {i["id"]: i for i in check_names(make(), "room_first")}
    assert set(issues) == {"d2", "d3", "d4", "d5", "d6", "input_boolean.guest_mode"}
    assert (issues["d2"]["problem"], issues["d2"]["suggestion"]) == ("duplicate", "Lounge Lamp")
    assert (issues["d3"]["problem"], issues["d3"]["suggestion"]) == ("duplicate", "Kitchen Lamp")
    assert (issues["d4"]["problem"], issues["d4"]["suggestion"]) == ("wrong_room", "Lounge Speaker")
    assert (issues["d5"]["problem"], issues["d5"]["suggestion"]) == ("technical", "Lounge Radiator")
    assert (issues["d6"]["problem"], issues["d6"]["suggestion"]) == ("no_room", "Kitchen Diner Table Light")
    assert issues["input_boolean.guest_mode"]["suggestion"] == "Lounge Guest Mode"
    assert issues["input_boolean.guest_mode"]["type"] == "entity"
    # Worst first.
    assert check_names(make(), "room_first")[0]["problem"] == "wrong_room"


def test_no_room_style():
    issues = {i["id"]: i for i in check_names(make(), "no_room")}
    assert (issues["d1"]["problem"], issues["d1"]["suggestion"]) == ("has_room", "Ceiling Light")
    assert issues["d7"]["suggestion"] == "Blind"
    assert issues["d4"]["suggestion"] == "Speaker"
    assert issues["d5"]["suggestion"] == "Radiator"
    assert issues["d2"]["problem"] == "duplicate" and issues["d2"]["suggestion"] is None
    assert "d6" not in issues
