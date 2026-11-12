"""Tests for the battery forecast, the explainer and the weekly report."""

from datetime import UTC, datetime, timedelta

from custom_components.ha_manager.analysis import analyse, plan
from custom_components.ha_manager.battery import forecast
from custom_components.ha_manager.explain import explain
from custom_components.ha_manager.models import DeviceInfo, EntityInfo, Snapshot
from custom_components.ha_manager.report import build_report, summarise

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def series(start_level, per_day, days, end=NOW):
    return [
        (end - timedelta(days=days - i), start_level - per_day * i) for i in range(days + 1)
    ]


def test_forecast_steady_drain():
    result = forecast(series(80, 2, 30), NOW)  # now at 20%, losing 2 a day
    assert result["status"] == "forecast"
    assert result["rate_per_day"] == 2.0
    assert result["days_left"] == 10
    assert result["empty_on"] == "2026-11-22"
    assert result["confidence"] == "good"


def test_forecast_ignores_readings_before_a_replacement():
    old = series(40, 3, 10, end=NOW - timedelta(days=11))  # ran down to 10%
    new = series(100, 1, 10)  # replaced, now 90%
    result = forecast(old + new, NOW)
    assert result["status"] == "forecast"
    assert result["rate_per_day"] == 1.0
    assert result["days_left"] == 90
    assert result["confidence"] == "rough"
    assert result["replaced"] == (NOW - timedelta(days=10)).date().isoformat()


def test_forecast_learning_and_steady():
    assert forecast([], NOW)["status"] == "learning"
    assert forecast(series(90, 1, 2), NOW)["status"] == "learning"
    assert forecast(series(100, 0, 30), NOW)["status"] == "steady"


def test_batteries_in_analysis():
    snap = Snapshot(now=NOW)
    snap.devices["d"] = DeviceInfo("d", "Back Door Sensor")
    snap.entities["sensor.door_battery"] = EntityInfo(
        "sensor.door_battery", "Battery", state="20", device_id="d", device_class="battery"
    )
    snap.entities["sensor.new_battery"] = EntityInfo(
        "sensor.new_battery", "New Battery", state="100", device_class="battery"
    )
    snap.battery_history["sensor.door_battery"] = series(80, 2, 30)
    result = analyse(snap)
    assert [b["name"] for b in result["batteries"]] == ["Back Door Sensor", "New Battery"]
    assert result["batteries"][0]["days_left"] == 10
    assert result["batteries"][1]["status"] == "learning"
    found = {f["id"]: f for f in result["findings"]}
    assert "about 10 days left" in found["battery_forecast"]["items"][0]["note"]


NAMES = {
    "binary_sensor.hall": "Hall Motion",
    "light.hall": "Hall Light",
    "area:hall": "Hall",
    "script.goodnight": "Goodnight",
    "sensor.lux": "Hall Brightness",
}


def namer(value):
    return NAMES.get(value, value)


def test_explain_simple_automation():
    config = {
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.hall", "to": "on"}],
        "condition": [{"condition": "time", "after": "23:00:00"}],
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.hall"}, "data": {"brightness_pct": 20}}
        ],
    }
    result = explain("automation", config, namer)
    assert result["summary"] == (
        "When Hall Motion turns on, but only if it is after 23:00:00, "
        "it turns on Hall Light at 20% brightness."
    )


def test_explain_complex_automation():
    config = {
        "triggers": [
            {"trigger": "numeric_state", "entity_id": "sensor.lux", "below": 5, "for": {"minutes": 5}},
            {"trigger": "sun", "event": "sunset", "offset": "-00:30:00"},
        ],
        "conditions": [{"condition": "state", "entity_id": "light.hall", "state": "off"}],
        "actions": [
            {"action": "light.turn_off", "target": {"area_id": "hall"}},
            {"delay": "00:02:00"},
            {
                "choose": [
                    {
                        "conditions": [{"condition": "numeric_state", "entity_id": "sensor.lux", "below": 5}],
                        "sequence": [{"action": "script.goodnight"}],
                    }
                ],
                "default": [{"action": "notify.mobile_app_dans_phone", "data": {"message": "Hello"}}],
            },
            {"action": "something.{{ odd }}"},
            {"wibble": 1},
        ],
    }
    result = explain("automation", config, namer)
    assert result["when"] == [
        "Hall Brightness drops below 5 for 5 minutes",
        "it is 30 minutes before sunset",
    ]
    assert result["only_if"] == ["Hall Light is off"]
    assert result["then"] == [
        "turns off everything in Hall",
        "waits 2 minutes",
        "if Hall Brightness is below 5:",
        "  runs the script Goodnight",
        "otherwise:",
        "  sends a notification to dans phone: “Hello”",
        "runs an action chosen by a calculation",
        "does something this explainer cannot read",
    ]
    assert result["summary"].endswith("it runs 5 steps.")
    assert result["note"]


def test_explain_script_blueprint_and_missing():
    script = explain("script", {"sequence": [{"service": "light.toggle", "entity_id": "light.hall"}]}, namer)
    assert script["summary"] == "When this script is run, it toggles Hall Light."
    blueprint = explain(
        "automation",
        {"use_blueprint": {"path": "homeassistant/motion_light.yaml", "input": {"motion_entity": "binary_sensor.hall", "no_motion_wait": 120}}},
        namer,
    )
    assert "motion light" in blueprint["summary"]
    assert blueprint["then"] == ["motion entity: Hall Motion", "no motion wait: 120"]
    assert "did not keep" in explain("automation", None, namer)["summary"]


def _result(score, findings, batteries=()):
    counts = {"critical": 0, "warning": 0, "tidy": 0}
    for f in findings:
        counts[f["severity"]] += 1
    return {
        "generated": NOW.isoformat(),
        "score": {"value": score, "grade": "Good", "counts": counts},
        "findings": findings,
        "batteries": list(batteries),
        "safety": {"units": [
            {"name": "Hall Smoke Alarm", "excluded": False, "problems": ["Test overdue"]},
            {"name": "Ignored", "excluded": True, "problems": ["No test logged"]},
        ]},
    }


def _finding(fid, severity="warning"):
    return {"id": fid, "title": f"Problem {fid}", "severity": severity, "counts": True}


def test_weekly_report():
    first = build_report(_result(80, [_finding("a"), _finding("b")]), None)
    assert "first report" in first["text"]
    previous = summarise(_result(80, [_finding("a"), _finding("b")]))

    battery = {"name": "Back Door", "status": "forecast", "days_left": 9, "level": 18.0}
    report = build_report(
        _result(84, [_finding("b"), _finding("c", "critical")], [battery]), previous
    )
    assert report["headline"] == "Health score 84 out of 100 (Good), up 4 on last week."
    text = report["text"]
    assert "1 new problem, 1 fixed." in text
    assert "Fix first:\n- Problem c" in text
    assert "Sorted since last week:\n- Problem a" in text
    assert "- Back Door: about 9 days left (18%)" in text
    assert "Life-safety tests due: Hall Smoke Alarm." in text
    assert report["title"] == "HA Manager weekly report: 84/100"


def test_plan_groups_entities_by_room():
    snap = Snapshot(now=NOW)
    snap.areas = {"hall": "Hall", "loft": "Loft"}
    snap.area_floors = {"hall": "g", "loft": None}
    snap.floors = {"g": {"name": "Ground", "level": 0}}
    for entity_id, device_class, category in (
        ("light.hall", None, None),
        ("sensor.hall_temp", "temperature", None),
        ("binary_sensor.hall_motion", "motion", None),
        ("binary_sensor.hall_smoke", "smoke", None),
        ("sensor.hall_signal", "signal_strength", "diagnostic"),
    ):
        snap.entities[entity_id] = EntityInfo(
            entity_id, entity_id, area_id="hall", device_class=device_class, entity_category=category
        )
    result = plan(snap)
    hall = next(a for a in result["areas"] if a["id"] == "hall")
    assert hall["lights"] == ["light.hall"]
    assert hall["temps"] == ["sensor.hall_temp"]
    assert hall["motion"] == ["binary_sensor.hall_motion"]
    assert hall["safety"] == ["binary_sensor.hall_smoke"]
    assert "sensor.hall_signal" not in hall["all"]
    assert hall["floor_id"] == "g"
    assert next(a for a in result["areas"] if a["id"] == "loft")["all"] == []
