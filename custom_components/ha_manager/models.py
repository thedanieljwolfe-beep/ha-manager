"""Plain data classes describing a snapshot of a Home Assistant setup.

No Home Assistant imports here: the collector fills these in, and the analysis
works only on these, which keeps the analysis easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

UNAVAILABLE = "unavailable"


@dataclass
class EntityInfo:
    """One entity."""

    entity_id: str
    name: str
    state: str | None = None
    device_id: str | None = None
    area_id: str | None = None  # effective area (its own, else its device's)
    platform: str | None = None
    device_class: str | None = None
    entity_category: str | None = None
    labels: set[str] = field(default_factory=set)
    in_registry: bool = True
    disabled: bool = False
    hidden: bool = False
    orphaned: bool = False  # left behind by an integration that has gone
    last_seen: datetime | None = None
    members: list[str] | None = None  # for groups

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]

    @property
    def unavailable(self) -> bool:
        return self.state == UNAVAILABLE


@dataclass
class DeviceInfo:
    """One device."""

    device_id: str
    name: str
    area_id: str | None = None
    disabled: bool = False
    is_service: bool = False  # "service" devices are not physical things
    orphaned: bool = False


@dataclass
class Consumer:
    """Something that uses entities: an automation, script, scene, group or dashboard."""

    kind: str  # automation | script | scene | group | dashboard
    id: str  # entity_id, or dashboard URL path
    name: str
    state: str | None = None
    entities: set[str] = field(default_factory=set)
    mentioned: set[str] = field(default_factory=set)  # only seen in templates
    devices: set[str] = field(default_factory=set)
    areas: set[str] = field(default_factory=set)
    scripts_called: set[str] = field(default_factory=set)
    last_triggered: datetime | None = None
    triggers_24h: int | None = None
    edit_url: str | None = None

    @property
    def all_entities(self) -> set[str]:
        return self.entities | self.mentioned | self.scripts_called


@dataclass
class RepairIssue:
    """An item from Home Assistant's Repairs list."""

    domain: str
    issue_id: str
    title: str
    severity: str  # critical | error | warning


@dataclass
class Snapshot:
    """Everything the analysis needs to know."""

    now: datetime
    entities: dict[str, EntityInfo] = field(default_factory=dict)
    devices: dict[str, DeviceInfo] = field(default_factory=dict)
    areas: dict[str, str] = field(default_factory=dict)  # area_id -> name
    consumers: list[Consumer] = field(default_factory=list)
    services: set[str] = field(default_factory=set)  # "domain.service"
    repairs: list[RepairIssue] = field(default_factory=list)
    watchman: dict[str, int] | None = None  # label -> count
    counting_since: datetime | None = None  # when trigger counting began


@dataclass
class Finding:
    """One problem, worded for a human."""

    id: str
    severity: str
    category: str
    title: str
    detail: str = ""
    advice: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    link: str | None = None
    counts: bool = True  # False = shown, but does not affect the score

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "detail": self.detail,
            "advice": self.advice,
            "items": self.items,
            "link": self.link,
            "counts": self.counts,
        }
