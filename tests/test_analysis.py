"""Tests for the checks, score and blast radius."""

from datetime import UTC, datetime, timedelta

from custom_components.ha_manager.analysis import analyse, blast_radius, score, targets
from custom_components.ha_manager.models import (
    Consumer,
    DeviceInfo,
    EntityInfo,
    Finding,
    RepairIssue,
    Snapshot,
)

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def make_snapshot() -> Snapshot:
    snap = Snapshot(now=NOW, counting_since=NOW)
    snap.areas = {"kitchen": "Kitchen", "hall": "Hall"}
    snap.services = {"light.turn_on", "script.turn_on"}
    snap.devices = {
        "dev_lamp": DeviceInfo("dev_lamp", "Kitchen Lamp", area_id="kitchen"),
        "dev_dead": DeviceInfo("dev_dead", "Old Plug"),
        "dev_smoke": DeviceInfo("dev_smoke", "Hall Smoke Alarm", area_id="hall"),
        "dev_leak": DeviceInfo("dev_leak", "Sink Leak Sensor", area_id="kitchen"),
        "dev_door": DeviceInfo("dev_door", "Back Door Sensor", area_id="kitchen"),
    }

    def add(entity_id, name, state="on", **kwargs):
        snap.entities[entity_id] = EntityInfo(entity_id, name, state=state, **kwargs)

    add("light.kitchen_lamp", "Kitchen Lamp", device_id="dev_lamp", area_id="kitchen")
    add("sensor.lamp_power", "Lamp Power", "unavailable", device_id="dev_lamp", area_id="kitchen")
    add("switch.old_plug", "Old Plug", "unavailable", device_id="dev_dead")
    add("sensor.old_plug_power", "Old Plug Power", "unavailable", device_id="dev_dead")
    add("sensor.ghost", "Ghost", "unavailable", platform="tuya", orphaned=True)
    add("binary_sensor.hall_smoke", "Hall Smoke", "off", device_id="dev_smoke", area_id="hall", device_class="smoke")
    add("sensor.hall_smoke_battery", "Hall Smoke Battery", "8", device_id="dev_smoke", area_id="hall", device_class="battery")
    add("binary_sensor.sink_leak", "Sink Leak", "unavailable", device_id="dev_leak", area_id="kitchen", device_class="moisture")
    add("binary_sensor.back_door", "Back Door", "off", device_id="dev_door", area_id="kitchen", device_class="door")
    add("sensor.back_door_battery", "Back Door Battery", "12", device_id="dev_door", area_id="kitchen", device_class="battery")
    add("sensor.broken_template", "Broken Template", "unavailable")
    add("light.all_lights", "All Lights", members=["light.kitchen_lamp", "light.gone"])
    add("automation.kitchen_motion", "Kitchen motion")
    add("automation.busy", "Busy one")
    add("automation.broken", "Broken one", "unavailable")
    add("automation.old", "Old one")
    add("script.goodnight", "Goodnight", "off")
    add("script.unused", "Unused", "off")
    add("scene.movie", "Movie", "unknown")

    recent = NOW - timedelta(days=1)
    snap.consumers = [
        Consumer("automation", "automation.kitchen_motion", "Kitchen motion", "on",
                 entities={"light.kitchen_lamp", "light.deleted"}, mentioned={"sensor.template_gone"},
                 scripts_called={"script.goodnight"}, last_triggered=recent, triggers_24h=4,
                 edit_url="/config/automation/edit/1"),
        Consumer("automation", "automation.busy", "Busy one", "on", entities={"light.all_lights"},
                 last_triggered=recent, triggers_24h=500),
        Consumer("automation", "automation.broken", "Broken one", "unavailable", devices={"dev_removed"}),
        Consumer("automation", "automation.old", "Old one", "on", areas={"kitchen"},
                 last_triggered=NOW - timedelta(days=200), triggers_24h=0),
        Consumer("script", "script.goodnight", "Goodnight", "off", entities={"light.kitchen_lamp"},
                 last_triggered=recent),
        Consumer("script", "script.unused", "Unused", "off", mentioned={"sensor.maybe"}),
        Consumer("scene", "scene.movie", "Movie", entities={"light.kitchen_lamp"}),
        Consumer("group", "light.all_lights", "All Lights", "on", entities={"light.kitchen_lamp", "light.gone"}),
        Consumer("dashboard", "lovelace", "Home", entities={"light.kitchen_lamp", "sensor.not_there"},
                 edit_url="/lovelace"),
    ]
    snap.repairs = [
        RepairIssue("zha", "radio_fail", "Zigbee radio failed", "error"),
        RepairIssue("spook", "x", "Unknown entities in automation", "warning"),
    ]
    snap.watchman = {"missing entities": 3, "missing actions": 0}
    return snap


def by_id(result):
    return {f["id"]: f for f in result["findings"]}


def test_findings_cover_every_check():
    result = analyse(make_snapshot())
    found = by_id(result)

    assert found["broken:automation.broken"]["severity"] == "critical"
    assert found["safety_offline:dev_leak"]["severity"] == "critical"
    assert found["safety_battery:dev_smoke"]["severity"] == "critical"
    assert found["safety_tests_due"]["severity"] == "warning"
    assert len(found["safety_tests_due"]["items"]) == 2

    missing = found["missing_ref:automation:automation.kitchen_motion"]
    assert missing["severity"] == "warning"
    assert {i["name"] for i in missing["items"]} == {"light.deleted", "sensor.template_gone"}
    # Only seen in a template: a maybe, so a tidy-up rather than a warning.
    assert found["missing_ref:script:script.unused"]["severity"] == "tidy"
    assert "missing_ref:group:light.all_lights" in found
    assert "missing_ref:dashboard:lovelace" in found
    assert "missing_ref:automation:automation.broken" not in found

    assert found["offline:dev_dead"]["severity"] == "warning"
    assert "offline:dev_lamp" not in found
    assert [i["entity_id"] for i in found["unavailable_partial"]["items"]] == ["sensor.lamp_power"]
    assert [i["entity_id"] for i in found["unavailable_standalone"]["items"]] == ["sensor.broken_template"]
    assert found["orphans:tuya"]["severity"] == "tidy"
    assert [i["name"] for i in found["no_area"]["items"]] == ["Old Plug"]

    # The smoke alarm's battery is reported under life safety, not here too.
    assert [i["name"] for i in found["battery_low"]["items"]] == ["Back Door Sensor"]

    assert found["flapping:automation.busy"]["severity"] == "warning"
    assert [i["entity_id"] for i in found["zombies:automation"]["items"]] == ["automation.old"]
    zombie_scripts = found["zombies:script"]["items"]
    assert [i["entity_id"] for i in zombie_scripts] == ["script.unused"]
    assert "nothing calls it" in zombie_scripts[0]["note"]

    assert found["repair:zha:radio_fail"]["counts"] is True
    assert found["repair:spook:x"]["counts"] is False
    assert found["watchman:missing entities"]["counts"] is False
    assert "watchman:missing actions" not in found

    statuses = {row["entity_id"]: row["status"] for row in result["activity"]}
    assert statuses == {
        "automation.broken": "broken",
        "automation.busy": "flapping",
        "automation.old": "zombie",
        "script.unused": "zombie",
        "automation.kitchen_motion": "ok",
        "script.goodnight": "ok",
    }
    assert result["sources"] == {"counting_since": NOW.isoformat(), "watchman": True, "spook": True}
    assert result["findings"][0]["severity"] == "critical"


def test_score_and_ignore():
    snap = make_snapshot()
    full = analyse(snap)
    counts = full["score"]["counts"]
    assert counts["critical"] == 3
    expected = 100 - min(counts["critical"] * 10, 60) - min(counts["warning"] * 3, 30) - min(counts["tidy"] * 0.5, 10)
    assert full["score"]["value"] == round(expected)

    ignored = analyse(snap, {"ignored": ["broken:automation.broken"]})
    assert ignored["score"]["counts"]["critical"] == 2
    assert [f["id"] for f in ignored["ignored"]] == ["broken:automation.broken"]

    assert score([])["value"] == 100
    assert score([])["grade"] == "Shipshape"
    many = [Finding(str(i), "critical", "x", "x") for i in range(50)]
    assert score(many)["value"] == 40  # capped
    not_counted = [Finding("a", "critical", "x", "x", counts=False)]
    assert score(not_counted)["value"] == 100


def test_safety_test_log_and_exclusion():
    snap = make_snapshot()
    store = {
        "safety_tests": {"dev_smoke": [(NOW - timedelta(days=3)).isoformat()]},
        "safety_excluded": ["dev_leak"],
    }
    result = analyse(snap, store)
    found = by_id(result)
    assert "safety_tests_due" not in found
    assert "safety_offline:dev_leak" not in found
    units = {u["id"]: u for u in result["safety"]["units"]}
    assert units["dev_leak"]["status"] == "excluded"
    assert units["dev_smoke"]["status"] == "critical"  # battery at 8%
    assert units["dev_smoke"]["battery"] == 8
    assert units["dev_smoke"]["test_count"] == 1
    # Once excluded, the leak sensor is treated like any other offline device.
    assert "offline:dev_leak" in found

    overdue = analyse(snap, {"safety_tests": {"dev_smoke": [(NOW - timedelta(days=60)).isoformat()]}})
    assert "Test overdue" in {u["id"]: u for u in overdue["safety"]["units"]}["dev_smoke"]["problems"]


def test_label_makes_anything_life_safety():
    snap = Snapshot(now=NOW)
    snap.entities["switch.sprinkler"] = EntityInfo(
        "switch.sprinkler", "Sprinkler valve", state="unavailable", labels={"life_safety"}
    )
    result = analyse(snap)
    assert by_id(result)["safety_offline:switch.sprinkler"]["severity"] == "critical"
    assert "unavailable_standalone" not in by_id(result)


def test_blast_radius_entity_device_area():
    snap = make_snapshot()
    result = blast_radius(snap, "entity", "light.kitchen_lamp")
    users = {(u["kind"], u["id"]): u for u in result["used_by"]}
    assert set(users) == {
        ("automation", "automation.kitchen_motion"),
        ("automation", "automation.busy"),
        ("script", "script.goodnight"),
        ("scene", "scene.movie"),
        ("group", "light.all_lights"),
        ("dashboard", "lovelace"),
    }
    assert "All Lights" in users[("automation", "automation.busy")]["why"][0]
    assert result["safe"] is False
    assert result["summary"]["automation"] == 2
    assert [u["kind"] for u in result["used_by"]][0] == "automation"

    script = blast_radius(snap, "entity", "script.goodnight")
    assert [u["id"] for u in script["used_by"]] == ["automation.kitchen_motion"]

    assert blast_radius(snap, "entity", "sensor.broken_template")["safe"] is True
    assert blast_radius(snap, "entity", "sensor.nope")["target"]["exists"] is False

    device = blast_radius(snap, "device", "dev_lamp")
    assert device["target"]["entity_count"] == 2
    assert ("scene", "scene.movie") in {(u["kind"], u["id"]) for u in device["used_by"]}

    area = blast_radius(snap, "area", "kitchen")
    old = next(u for u in area["used_by"] if u["id"] == "automation.old")
    assert old["why"] == ["targets the whole room"]


def test_targets_lists_everything():
    snap = make_snapshot()
    found = targets(snap)
    assert {t["type"] for t in found} == {"area", "device", "entity"}
    assert len(found) == len(snap.areas) + len(snap.devices) + len(snap.entities)
