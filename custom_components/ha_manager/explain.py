"""Describe what an automation or script does, in plain English.

Pure Python: no Home Assistant imports. This is a rule-based reading of the
config. It covers the common cases and says so honestly when it meets
something it cannot put into words.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Namer = Callable[[str], str]

STATE_WORDS = {
    "on": "turns on",
    "off": "turns off",
    "home": "comes home",
    "not_home": "leaves home",
    "open": "opens",
    "closed": "closes",
    "locked": "locks",
    "unlocked": "unlocks",
    "unavailable": "goes offline",
    "playing": "starts playing",
    "paused": "is paused",
}
IS_WORDS = {
    "on": "is on",
    "off": "is off",
    "home": "is home",
    "not_home": "is away",
    "open": "is open",
    "closed": "is closed",
    "locked": "is locked",
    "unlocked": "is unlocked",
}
SERVICE_VERBS = {
    "turn_on": "turns on",
    "turn_off": "turns off",
    "toggle": "toggles",
    "lock": "locks",
    "unlock": "unlocks",
    "open_cover": "opens",
    "close_cover": "closes",
    "stop_cover": "stops",
    "press": "presses",
    "start": "starts",
    "pause": "pauses",
    "stop": "stops",
    "return_to_base": "sends home",
    "media_play": "plays",
    "media_pause": "pauses",
    "media_stop": "stops",
    "reload": "reloads",
    "trigger": "triggers",
    "select_option": "changes the option on",
    "set_value": "sets the value of",
    "increment": "increases",
    "decrement": "decreases",
}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _join(parts: list[str], word: str = "and") -> str:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} {word} {parts[-1]}"


def _is_template(value: Any) -> bool:
    return isinstance(value, str) and ("{{" in value or "{%" in value)


def _duration(value: Any) -> str:
    if isinstance(value, dict):
        parts = []
        for unit in ("days", "hours", "minutes", "seconds"):
            amount = value.get(unit)
            if amount:
                parts.append(f"{amount} {unit if amount != 1 else unit[:-1]}")
        return _join(parts) or "a moment"
    if isinstance(value, (int, float)):
        return f"{value:g} seconds"
    if _is_template(value):
        return "a calculated time"
    if isinstance(value, str) and value.count(":") == 2:
        try:
            hours, minutes, seconds = (int(float(p)) for p in value.split(":"))
        except ValueError:
            return value
        return _duration({"hours": hours, "minutes": minutes, "seconds": seconds})
    return str(value)


def _names(value: Any, namer: Namer) -> str:
    ids = []
    for item in _list(value):
        if isinstance(item, str):
            ids += [part.strip() for part in item.split(",") if part.strip()]
    if any(_is_template(i) for i in ids):
        return "a calculated entity"
    return _join([namer(i) for i in ids], "or") if ids else "something"


def _targets(action: dict[str, Any], namer: Namer) -> str:
    """Who an action is aimed at."""
    parts: list[str] = []
    entity_ids: list[str] = []
    for source in (action, action.get("target") or {}, action.get("data") or {}):
        if not isinstance(source, dict):
            continue
        for item in _list(source.get("entity_id")):
            if isinstance(item, str):
                entity_ids += [p.strip() for p in item.split(",") if p.strip()]
        for area in _list(source.get("area_id")):
            parts.append(f"everything in {namer('area:' + str(area))}")
        if source.get("device_id"):
            count = len(_list(source["device_id"]))
            parts.append("a device" if count == 1 else f"{count} devices")
        for label in _list(source.get("label_id")):
            parts.append(f"everything labelled '{label}'")
        for floor in _list(source.get("floor_id")):
            parts.append(f"everything on the floor '{floor}'")
    seen: list[str] = []
    for entity_id in entity_ids:
        if entity_id not in seen:
            seen.append(entity_id)
    if any(_is_template(i) for i in seen):
        parts.insert(0, "a calculated entity")
    else:
        parts = [namer(i) for i in seen] + parts
    return _join(parts)


def describe_trigger(trigger: Any, namer: Namer) -> str:
    """One trigger, as the end of a sentence beginning 'When ...'."""
    if not isinstance(trigger, dict):
        return "something happens"
    kind = trigger.get("trigger") or trigger.get("platform") or "unknown"
    if kind == "state":
        who = _names(trigger.get("entity_id"), namer)
        to = trigger.get("to")
        if isinstance(to, str) and to in STATE_WORDS:
            text = f"{who} {STATE_WORDS[to]}"
        elif to is not None:
            text = f"{who} changes to {_join([repr(str(t)) for t in _list(to)], 'or')}"
        elif trigger.get("attribute"):
            text = f"the {trigger['attribute']} of {who} changes"
        else:
            text = f"{who} changes"
        if trigger.get("from") is not None and to is None:
            text += f" from {_join([repr(str(t)) for t in _list(trigger['from'])], 'or')}"
        if trigger.get("for"):
            text += f" and stays that way for {_duration(trigger['for'])}"
        return text
    if kind == "numeric_state":
        who = _names(trigger.get("entity_id"), namer)
        bounds = []
        if trigger.get("above") is not None:
            bounds.append(f"rises above {trigger['above']}")
        if trigger.get("below") is not None:
            bounds.append(f"drops below {trigger['below']}")
        text = f"{who} {_join(bounds) or 'changes'}"
        if trigger.get("for"):
            text += f" for {_duration(trigger['for'])}"
        return text
    if kind == "time":
        times = [namer(t) if isinstance(t, str) and "." in t and ":" not in t else str(t) for t in _list(trigger.get("at"))]
        return f"the time is {_join(times, 'or')}"
    if kind == "time_pattern":
        bits = [f"{unit} {trigger[unit]}" for unit in ("hours", "minutes", "seconds") if unit in trigger]
        return f"a repeating timer ticks ({', '.join(bits)})"
    if kind == "sun":
        event = trigger.get("event", "sunset")
        offset = trigger.get("offset")
        if offset:
            text = str(offset)
            before = text.startswith("-")
            return f"it is {_duration(text.lstrip('+-'))} {'before' if before else 'after'} {event}"
        return f"it is {event}"
    if kind == "zone":
        who = _names(trigger.get("entity_id"), namer)
        verb = "leaves" if trigger.get("event") == "leave" else "arrives at"
        return f"{who} {verb} {namer(str(trigger.get('zone', 'a zone')))}"
    if kind == "homeassistant":
        return f"Home Assistant {'shuts down' if trigger.get('event') == 'shutdown' else 'starts'}"
    if kind == "event":
        return f"the event '{trigger.get('event_type')}' happens"
    if kind == "device":
        what = str(trigger.get("type") or trigger.get("subtype") or "something").replace("_", " ")
        return f"a device reports '{what}'"
    if kind == "template":
        return "a calculated condition becomes true"
    if kind == "webhook":
        return "a webhook is called from outside"
    if kind == "mqtt":
        return f"an MQTT message arrives on '{trigger.get('topic')}'"
    if kind == "tag":
        return "an NFC tag is scanned"
    if kind == "calendar":
        return f"an event on {_names(trigger.get('entity_id'), namer)} {trigger.get('event', 'start')}s"
    if kind == "conversation":
        return f"someone says {_join([repr(c) for c in _list(trigger.get('command'))], 'or')}"
    if kind == "persistent_notification":
        return "a notification appears in Home Assistant"
    return f"a '{kind}' trigger fires"


def describe_condition(condition: Any, namer: Namer) -> str:
    """One condition, as the end of a sentence beginning 'Only if ...'."""
    if isinstance(condition, str):
        return "a calculated check passes"
    if not isinstance(condition, dict):
        return "a check passes"
    for joiner in ("and", "or"):
        if joiner in condition:
            return _join([describe_condition(c, namer) for c in _list(condition[joiner])], joiner)
    if "not" in condition:
        return "none of these are true: " + _join(
            [describe_condition(c, namer) for c in _list(condition["not"])], "or"
        )
    kind = condition.get("condition")
    if kind in ("and", "or"):
        return _join([describe_condition(c, namer) for c in _list(condition.get("conditions"))], kind)
    if kind == "not":
        return "none of these are true: " + _join(
            [describe_condition(c, namer) for c in _list(condition.get("conditions"))], "or"
        )
    if kind == "state":
        who = _names(condition.get("entity_id"), namer)
        states = [str(s) for s in _list(condition.get("state"))]
        if len(states) == 1 and states[0] in IS_WORDS:
            text = f"{who} {IS_WORDS[states[0]]}"
        else:
            text = f"{who} is {_join([repr(s) for s in states], 'or')}"
        if condition.get("for"):
            text += f" for at least {_duration(condition['for'])}"
        return text
    if kind == "numeric_state":
        who = _names(condition.get("entity_id"), namer)
        bounds = []
        if condition.get("above") is not None:
            bounds.append(f"above {condition['above']}")
        if condition.get("below") is not None:
            bounds.append(f"below {condition['below']}")
        return f"{who} is {_join(bounds)}"
    if kind == "time":
        bits = []
        if condition.get("after"):
            bits.append(f"after {condition['after']}")
        if condition.get("before"):
            bits.append(f"before {condition['before']}")
        if condition.get("weekday"):
            bits.append("on " + _join([str(d).capitalize() for d in _list(condition["weekday"])], "or"))
        return "it is " + (_join(bits) or "the right time")
    if kind == "sun":
        bits = [f"{key} {condition[key]}" for key in ("after", "before") if condition.get(key)]
        return "it is " + (_join(bits) or "the right time of day")
    if kind == "zone":
        return f"{_names(condition.get('entity_id'), namer)} is in {namer(str(condition.get('zone')))}"
    if kind == "template" or "value_template" in condition:
        return "a calculated check passes"
    if kind == "trigger":
        return "it was started by a particular trigger"
    if kind == "device":
        return "a device is in a particular state"
    return f"a '{kind}' check passes"


def _extras(data: Any) -> str:
    """The interesting settings on a service call."""
    if not isinstance(data, dict):
        return ""
    bits = []
    if "brightness_pct" in data:
        bits.append(f"at {data['brightness_pct']}% brightness")
    elif "brightness" in data and isinstance(data["brightness"], (int, float)):
        bits.append(f"at {round(data['brightness'] / 255 * 100)}% brightness")
    if "color_name" in data:
        bits.append(f"in {data['color_name']}")
    if "color_temp_kelvin" in data or "kelvin" in data:
        bits.append(f"at {data.get('color_temp_kelvin', data.get('kelvin'))}K")
    if "transition" in data:
        bits.append(f"fading over {_duration(data['transition'])}")
    if "temperature" in data:
        bits.append(f"to {data['temperature']}°")
    if "hvac_mode" in data:
        bits.append(f"in {data['hvac_mode']} mode")
    if "position" in data:
        bits.append(f"to {data['position']}%")
    if "volume_level" in data and isinstance(data["volume_level"], (int, float)):
        bits.append(f"at {round(data['volume_level'] * 100)}% volume")
    if "option" in data:
        bits.append(f"to '{data['option']}'")
    if "value" in data:
        bits.append(f"to {data['value']}")
    return " " + " ".join(bits) if bits else ""


def _message(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    message = data.get("message") or data.get("title")
    if not message:
        return ""
    if _is_template(message):
        return " with a calculated message"
    text = str(message)
    return f": “{text if len(text) <= 80 else text[:77] + '…'}”"


def describe_action(action: Any, namer: Namer) -> list[str]:
    """One action. Returns one or more lines."""
    if not isinstance(action, dict):
        return ["does something this explainer cannot read"]
    service = action.get("action") or action.get("service")
    if isinstance(service, str):
        if _is_template(service):
            return ["runs an action chosen by a calculation"]
        domain, _, name = service.partition(".")
        data = action.get("data") or action.get("data_template") or {}
        who = _targets(action, namer)
        if domain == "notify":
            target = name.replace("mobile_app_", "").replace("_", " ")
            return [f"sends a notification to {target}{_message(data)}"]
        if domain == "persistent_notification":
            return [f"shows a notification in Home Assistant{_message(data)}"]
        if domain == "tts" or name == "speak":
            return [f"says something out loud{_message(data)}"]
        if domain == "script" and name not in ("turn_on", "turn_off", "toggle", "reload"):
            return [f"runs the script {namer(service)}"]
        if domain == "scene" and name == "turn_on":
            return [f"activates the scene {who or 'chosen'}"]
        if domain == "automation" and name == "trigger":
            return [f"runs the automation {who}"]
        if domain == "climate" and name == "set_temperature":
            return [f"sets {who or 'the heating'}{_extras(data)}"]
        if domain == "climate" and name == "set_hvac_mode":
            return [f"sets {who or 'the heating'}{_extras(data)}"]
        if domain == "cover" and name == "set_cover_position":
            return [f"moves {who or 'a cover'}{_extras(data)}"]
        if domain == "media_player" and name == "volume_set":
            return [f"sets {who or 'a speaker'}{_extras(data)}"]
        if domain == "media_player" and name == "play_media":
            return [f"plays media on {who or 'a speaker'}"]
        if name in SERVICE_VERBS:
            return [f"{SERVICE_VERBS[name]} {who or 'something'}{_extras(data)}"]
        return [f"runs '{service}'" + (f" on {who}" if who else "")]
    if "delay" in action:
        return [f"waits {_duration(action['delay'])}"]
    if "wait_template" in action:
        return ["waits until a calculated condition is true"]
    if "wait_for_trigger" in action:
        waits = [describe_trigger(t, namer) for t in _list(action["wait_for_trigger"])]
        return [f"waits until {_join(waits, 'or')}"]
    if "scene" in action:
        return [f"activates the scene {namer(str(action['scene']))}"]
    if "event" in action:
        return [f"fires the event '{action['event']}'"]
    if "stop" in action:
        return ["stops here"]
    if "if" in action:
        conditions = _join([describe_condition(c, namer) for c in _list(action["if"])])
        lines = [f"if {conditions}:"]
        lines += [f"  {line}" for a in _list(action.get("then")) for line in describe_action(a, namer)]
        if action.get("else"):
            lines.append("otherwise:")
            lines += [f"  {line}" for a in _list(action["else"]) for line in describe_action(a, namer)]
        return lines
    if "choose" in action:
        lines = []
        for index, option in enumerate(_list(action["choose"])):
            if not isinstance(option, dict):
                continue
            conditions = _join([describe_condition(c, namer) for c in _list(option.get("conditions"))])
            lines.append(f"{'if' if index == 0 else 'or if'} {conditions}:")
            lines += [f"  {line}" for a in _list(option.get("sequence")) for line in describe_action(a, namer)]
        if action.get("default"):
            lines.append("otherwise:")
            lines += [f"  {line}" for a in _list(action["default"]) for line in describe_action(a, namer)]
        return lines or ["chooses between options"]
    if "repeat" in action and isinstance(action["repeat"], dict):
        repeat = action["repeat"]
        if "count" in repeat:
            head = f"repeats {repeat['count']} times:"
        elif "while" in repeat:
            head = "keeps repeating while " + _join([describe_condition(c, namer) for c in _list(repeat["while"])]) + ":"
        elif "until" in repeat:
            head = "keeps repeating until " + _join([describe_condition(c, namer) for c in _list(repeat["until"])]) + ":"
        else:
            head = "repeats for each item in a list:"
        return [head] + [f"  {line}" for a in _list(repeat.get("sequence")) for line in describe_action(a, namer)]
    if "parallel" in action:
        lines = ["at the same time:"]
        for branch in _list(action["parallel"]):
            for step in _list(branch):
                lines += [f"  {line}" for line in describe_action(step, namer)]
        return lines
    if "sequence" in action:
        return [line for a in _list(action["sequence"]) for line in describe_action(a, namer)]
    if "condition" in action or "and" in action or "or" in action or "not" in action:
        return [f"carries on only if {describe_condition(action, namer)}"]
    if "variables" in action or "set_conversation_response" in action:
        return []
    if "device_id" in action:
        what = str(action.get("type", "does something")).replace("_", " ")
        return [f"tells a device to '{what}'"]
    return ["does something this explainer cannot read"]


def explain(kind: str, config: dict[str, Any] | None, namer: Namer) -> dict[str, Any]:
    """Explain a whole automation or script."""
    if not config:
        return {
            "when": [],
            "only_if": [],
            "then": [],
            "summary": "Home Assistant did not keep the settings for this one, so it cannot be explained.",
            "note": None,
        }
    note = None
    if "use_blueprint" in config:
        blueprint = config["use_blueprint"] or {}
        path = str(blueprint.get("path", "a blueprint")).rsplit("/", 1)[-1].removesuffix(".yaml")
        inputs = blueprint.get("input") or {}
        settings = []
        for key, value in inputs.items():
            if isinstance(value, (dict, list)):
                shown = _targets({"target": value}, namer) if isinstance(value, dict) else _names(value, namer)
            elif isinstance(value, str) and "." in value and " " not in value:
                shown = namer(value)
            else:
                shown = str(value)
            settings.append(f"{str(key).replace('_', ' ')}: {shown or 'set'}")
        return {
            "when": [],
            "only_if": [],
            "then": settings,
            "summary": f"Built from the ready-made blueprint '{path.replace('_', ' ')}', with these settings.",
            "note": "The steps live inside the blueprint, so only its settings are shown.",
        }

    triggers = _list(config.get("triggers", config.get("trigger")))
    conditions = _list(config.get("conditions", config.get("condition"))) if kind == "automation" else []
    actions = _list(config.get("actions", config.get("action", config.get("sequence"))))

    when = [describe_trigger(t, namer) for t in triggers]
    only_if = [describe_condition(c, namer) for c in conditions]
    described = [describe_action(a, namer) for a in actions]
    then = [line for lines in described for line in lines]
    steps = sum(1 for lines in described if lines)

    if kind == "automation":
        summary = "When " + (_join(when, "or") if when else "it is run by hand")
    else:
        summary = "When this script is run"
    if only_if:
        summary += ", but only if " + _join(only_if)
    top = [line for line in then if not line.startswith(" ")]
    if not then:
        summary += ", it does nothing."
    elif len(top) <= 3 and len(top) == len(then):
        summary += ", it " + _join(top) + "."
    else:
        summary += f", it runs {steps} steps."
    if any("cannot read" in line for line in then):
        note = "Some steps were too unusual to put into words."
    return {"when": when, "only_if": only_if, "then": then, "summary": summary, "note": note}
