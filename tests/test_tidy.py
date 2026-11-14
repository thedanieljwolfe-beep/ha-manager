"""Tests for the tidy-up checks (pure logic, no Home Assistant needed)."""

from datetime import UTC, datetime, timedelta

from custom_components.ha_manager.models import Consumer, DeviceInfo, EntityInfo, Snapshot
from custom_components.ha_manager.tidy import config_fingerprint, tidy, track_unavailable

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
LONG_AGO = NOW - timedelta(days=20)


def make_snapshot() -> Snapshot:
    snap = Snapshot(now=NOW)
    snap.areas = {"hall": "Hall"}
    snap.devices = {
        "dev_plug": DeviceInfo("dev_plug", "Old Plug"),
        "dev_smoke": DeviceInfo("dev_smoke", "Hall Smoke Alarm", area_id="hall"),
        "dev_bulb": DeviceInfo("dev_bulb", "Hall Bulb", area_id="hall"),
        "dev_gone": DeviceInfo("dev_gone", "Tuya Thing", orphaned=True),
    }

    def add(entity_id, name, state="on", **kwargs):
        snap.entities[entity_id] = EntityInfo(entity_id, name, state=state, **kwargs)

    add("switch.old_plug", "Old Plug", "unavailable", device_id="dev_plug")
    add("binary_sensor.hall_smoke", "Hall Smoke", "unavailable", device_id="dev_smoke", device_class="smoke")
    add("light.hall_bulb", "Hall Bulb", device_id="dev_bulb", platform="hue")
    add("sensor.hall_bulb_power", "Hall Bulb Power", "unavailable", device_id="dev_bulb")
    add("sensor.tuya_temp", "Tuya Temp", "unavailable", device_id="dev_gone", orphaned=True)
    # Added twice: the old copy is dead.
    add("light.kitchen", "Kitchen", platform="zha")
    add("light.kitchen_2", "Kitchen", "unavailable", platform="zha")
    # Two genuinely different bulbs that happen to be numbered: left alone.
    add("light.desk", "Desk", platform="hue")
    add("light.desk_2", "Desk 2", platform="hue")
    add("sensor.ghost", "Ghost", "unavailable", platform="tuya", orphaned=True)

    action = [{"action": "light.turn_on", "target": {"entity_id": "light.hall_bulb"}}]
    snap.consumers = [
        Consumer("automation", "automation.a", "Hall light", "on", entities={"light.hall_bulb"},
                 last_triggered=NOW - timedelta(days=1), managed=True, config_key="a",
                 config={"id": "a", "alias": "Hall light", "trigger": [{"platform": "sun"}], "action": action}),
        Consumer("automation", "automation.b", "Hall light copy", "off", entities={"light.hall_bulb"},
                 last_triggered=None, managed=True, config_key="b",
                 config={"id": "b", "alias": "Hall light copy", "triggers": [{"platform": "sun"}], "actions": action}),
        Consumer("automation", "automation.c", "Morning", "on", last_triggered=NOW, managed=True,
                 config={"id": "c", "alias": "Morning", "triggers": [], "actions": [{"delay": 1}]}),
        Consumer("automation", "automation.d", "Morning", "on", last_triggered=NOW, managed=False,
                 config={"id": "d", "alias": "Morning", "triggers": [], "actions": [{"delay": 2}]}),
        Consumer("automation", "automation.broken", "Broken", "unavailable", managed=True),
        Consumer("script", "script.forgotten", "Forgotten", "off", managed=True),
        Consumer("script", "script.called", "Called", "off", managed=True),
        Consumer("dashboard", "lovelace", "Home", scripts_called={"script.called"}),
    ]
    for c in snap.consumers:
        if c.kind != "dashboard":
            add(c.id, c.name, c.state)
    snap.unavailable_since = {
        e.entity_id: LONG_AGO for e in snap.entities.values() if e.unavailable
    }
    return snap


def test_fingerprint_ignores_names_and_spellings() -> None:
    one = {"id": "1", "alias": "A", "trigger": [{"platform": "sun"}], "action": [{"delay": 1}]}
    two = {"id": "2", "alias": "B", "description": "x", "triggers": [{"platform": "sun"}], "actions": [{"delay": 1}]}
    assert config_fingerprint(one) == config_fingerprint(two)
    assert config_fingerprint({"alias": "empty", "triggers": []}) is None
    assert config_fingerprint(None) is None


def test_groups() -> None:
    result = tidy(make_snapshot())
    groups = {g: {i["key"] for i in items} for g, items in result["groups"].items()}

    assert groups["broken"] == {"automation:automation.broken"}
    # Leftovers: the orphaned device, its entity, and the ghost.
    assert groups["leftover"] == {"device:dev_gone", "entity:sensor.tuya_temp", "entity:sensor.ghost"}
    # Offline: the dead plug as a whole device, and the one dead sensor on a
    # working bulb. Never the smoke alarm.
    assert groups["offline"] == {"device:dev_plug", "entity:sensor.hall_bulb_power"}
    assert not any("smoke" in key for keys in groups.values() for key in keys)
    # Unused: the script nothing calls. The one a dashboard calls is kept.
    assert "script:script.forgotten" in groups["unused"]
    assert "script:script.called" not in groups["unused"]


def test_duplicates() -> None:
    result = tidy(make_snapshot())
    sets = {s["title"]: s for s in result["duplicates"]}
    items = result["items"]

    same = sets["2 automations with exactly the same settings"]
    assert sorted(same["keys"]) == ["automation:automation.a", "automation:automation.b"]
    # The one that is on and has run is the one to keep.
    assert items["automation:automation.a"]["suggest"] == "keep"
    assert items["automation:automation.b"]["suggest"] == "remove"

    named = sets["2 automations called 'Morning'"]
    assert sorted(named["keys"]) == ["automation:automation.c", "automation:automation.d"]
    # One was written by hand in YAML, so it cannot be removed from here.
    assert not items["automation:automation.d"]["can_remove"]
    assert "by hand" in items["automation:automation.d"]["remove_note"]

    twice = sets["'Kitchen' looks like it was added twice"]
    assert items["entity:light.kitchen_2"]["suggest"] == "remove"
    assert items["entity:light.kitchen"]["suggest"] == "keep"
    assert not any("desk" in k for s in result["duplicates"] for k in s["keys"])

    # Items in a duplicate set are not repeated in the other sections.
    shown = {i["key"] for items in result["groups"].values() for i in items}
    assert "entity:light.kitchen_2" not in shown
    assert result["counts"]["duplicate"] == 3
    assert twice["key"].startswith("dup:")


def test_actions_and_usage() -> None:
    items = tidy(make_snapshot())["items"]
    # Live entities cannot be removed, only disabled.
    bulb_power = items["entity:sensor.hall_bulb_power"]
    assert bulb_power["can_disable"] and not bulb_power["can_remove"]
    assert "come back" in bulb_power["remove_note"]
    # Leftovers can be removed, and put back.
    assert items["entity:sensor.ghost"]["can_remove"]
    assert items["entity:sensor.ghost"]["undoable_remove"]
    # Devices are never removed from here: Home Assistant cannot put one back.
    assert not items["device:dev_gone"]["can_remove"]
    assert items["device:dev_gone"]["can_disable"]
    # Automations from the editor can be removed and put back.
    assert items["automation:automation.b"]["undoable_remove"]
    # An automation that is already off cannot be switched off again.
    assert not items["automation:automation.b"]["can_disable"]
    assert items["automation:automation.a"]["can_disable"]
    # Usage comes from the blast radius check.
    assert items["script:script.forgotten"]["used_by"] == 0


def test_ignoring() -> None:
    snap = make_snapshot()
    first = tidy(snap)
    dup_key = next(s["key"] for s in first["duplicates"] if "Kitchen" in s["title"])
    result = tidy(snap, {"script:script.forgotten", dup_key})
    assert "script:script.forgotten" not in {i["key"] for i in result["groups"]["unused"]}
    assert [i["key"] for i in result["ignored"]] == ["script:script.forgotten"]
    assert [s["key"] for s in result["ignored_sets"]] == [dup_key]
    # The dead copy of the kitchen light is still offline, so it moves there.
    assert "entity:light.kitchen_2" in {i["key"] for i in result["groups"]["offline"]}
    assert result["counts"]["duplicate"] == 2


def test_offline_needs_a_week() -> None:
    snap = make_snapshot()
    snap.unavailable_since = {k: NOW - timedelta(days=2) for k in snap.unavailable_since}
    result = tidy(snap)
    assert result["groups"]["offline"] == []


def test_track_unavailable() -> None:
    snap = make_snapshot()
    snap.entities["switch.old_plug"].last_changed = NOW - timedelta(hours=3)
    record = {"switch.old_plug": LONG_AGO.isoformat(), "light.kitchen": LONG_AGO.isoformat()}
    track_unavailable(record, snap)
    # Our older note wins over Home Assistant's (reset by a restart).
    assert record["switch.old_plug"] == LONG_AGO.isoformat()
    # Back online, so forgotten.
    assert "light.kitchen" not in record
    # Newly seen: starts now.
    assert record["sensor.ghost"] == NOW.isoformat()
    assert snap.unavailable_since["switch.old_plug"] == LONG_AGO
