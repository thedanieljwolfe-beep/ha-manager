"""Find entity references inside automation, script and dashboard configs.

Pure Python with no Home Assistant imports, so it is easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

# Keys whose value is the name of an action (service) rather than an entity.
SERVICE_KEYS = {"service", "action", "perform_action", "service_template"}

# Script services that are not themselves the name of a script.
SCRIPT_BUILTIN_SERVICES = {"turn_on", "turn_off", "toggle", "reload"}

_OBJECT_ID = r"[a-z0-9_]+"
_FULL_ENTITY_RE = re.compile(rf"^([a-z][a-z0-9_]*)\.({_OBJECT_ID})$")


@dataclass
class Refs:
    """References found in one config."""

    # The whole value was an entity ID, e.g. `entity_id: light.kitchen`.
    explicit: set[str] = field(default_factory=set)
    # An entity ID mentioned inside a template, e.g. `{{ states('light.x') }}`.
    templated: set[str] = field(default_factory=set)
    # Actions called, e.g. `light.turn_on` or `script.goodnight`.
    services: set[str] = field(default_factory=set)

    @property
    def scripts_called(self) -> set[str]:
        """Scripts run directly as an action, e.g. `action: script.goodnight`."""
        return {
            service
            for service in self.services
            if service.startswith("script.")
            and service.split(".", 1)[1] not in SCRIPT_BUILTIN_SERVICES
        }


def _mention_regex(domains: set[str]) -> re.Pattern[str] | None:
    if not domains:
        return None
    alternation = "|".join(sorted((re.escape(d) for d in domains), key=len, reverse=True))
    # Not preceded by a word character, and not followed by "(" (a function call).
    return re.compile(rf"(?<![a-z0-9_])({alternation})\.({_OBJECT_ID})(?![a-z0-9_]*\()")


def extract_references(config: Any, domains: set[str]) -> Refs:
    """Walk a config and collect everything that looks like an entity ID.

    `domains` is the set of entity domains that exist (light, sensor, ...), so
    that things like `mdi.icon` or `www.example` are not mistaken for entities.
    """
    refs = Refs()
    mention_re = _mention_regex(domains)

    def visit_string(value: str, key: str | None) -> None:
        text = value.strip()
        if not text:
            return
        is_template = "{{" in text or "{%" in text
        if key in SERVICE_KEYS and not is_template:
            if _FULL_ENTITY_RE.match(text):
                refs.services.add(text)
            return
        match = _FULL_ENTITY_RE.match(text)
        if match:
            if match.group(1) in domains:
                refs.explicit.add(text)
            return
        if not is_template:
            # Comma separated lists: "light.a, light.b"
            parts = [part.strip() for part in text.split(",")]
            if len(parts) > 1 and all(_FULL_ENTITY_RE.match(part) for part in parts):
                refs.explicit.update(
                    part for part in parts if part.split(".", 1)[0] in domains
                )
            return
        if mention_re is None:
            return
        for found in mention_re.finditer(text):
            refs.templated.add(f"{found.group(1)}.{found.group(2)}")

    def visit(node: Any, key: str | None) -> None:
        if isinstance(node, str):
            visit_string(node, key)
        elif isinstance(node, dict):
            for child_key, child in node.items():
                # Scene-style maps use the entity ID as the key.
                if isinstance(child_key, str):
                    match = _FULL_ENTITY_RE.match(child_key)
                    if match and match.group(1) in domains:
                        refs.explicit.add(child_key)
                visit(child, child_key if isinstance(child_key, str) else None)
        elif isinstance(node, (list, tuple, set)):
            for child in node:
                visit(child, key)

    visit(config, None)
    return refs
