"""Tests for the config walker."""

from custom_components.ha_manager.references import extract_references

DOMAINS = {"light", "sensor", "script", "binary_sensor", "switch"}


def test_explicit_templated_and_services():
    config = {
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.hall_motion"}],
        "condition": "{{ states('sensor.lux') | int < 10 and is_state('light.lamp', 'off') }}",
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": ["light.hall", "light.stairs"]}},
            {"action": "script.goodnight"},
            {"service": "script.turn_on", "entity_id": "script.other"},
            {"data": {"message": "see www.example.com and states.sensor.power.state {{ 1 }}"}},
        ],
    }
    refs = extract_references(config, DOMAINS)
    assert refs.explicit == {
        "binary_sensor.hall_motion", "light.hall", "light.stairs", "script.other",
    }
    assert refs.templated == {"sensor.lux", "light.lamp", "sensor.power"}
    assert refs.services == {"light.turn_on", "script.goodnight", "script.turn_on"}
    assert refs.scripts_called == {"script.goodnight"}


def test_ignores_lookalikes_and_handles_lists_and_scene_keys():
    config = {
        "icon": "mdi.home",
        "url": "example.com",
        "entities": "light.a, switch.b",
        "states": {"light.scene_lamp": {"state": "on"}},
        "template": "{{ light.turn_on() }}",
        "none": None,
        "number": 4,
    }
    refs = extract_references(config, DOMAINS)
    assert refs.explicit == {"light.a", "switch.b", "light.scene_lamp"}
    assert refs.templated == set()


def test_empty():
    assert extract_references(None, DOMAINS).explicit == set()
