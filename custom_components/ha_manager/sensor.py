"""The health score as a sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HAManagerConfigEntry, HAManagerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HAManagerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the health score sensor."""
    async_add_entities([HealthScoreSensor(entry.runtime_data, entry.entry_id)])


class HealthScoreSensor(CoordinatorEntity[HAManagerCoordinator], SensorEntity):
    """House health score out of 100."""

    _attr_has_entity_name = False
    _attr_name = "HA Manager health score"
    _attr_icon = "mdi:home-heart"
    _attr_native_unit_of_measurement = "points"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: HAManagerCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_health_score"
        self.entity_id = f"sensor.{DOMAIN}_health_score"

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        return data["score"]["value"] if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if not data:
            return None
        return {
            "grade": data["score"]["grade"],
            **data["score"]["counts"],
            "last_scan": data["generated"],
        }
