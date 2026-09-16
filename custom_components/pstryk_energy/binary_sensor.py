"""Binary sensor: is the current hour cheap?"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_WINDOW_HOURS,
    DEFAULT_WINDOW_HOURS,
    DOMAIN,
    TZ_WARSAW,
)
from .coordinator import PricingDataCoordinator
from .models import cheapest_window
from .sensor import PstrykEntityBase


class PstrykIsCheapNowSensor(PstrykEntityBase, BinarySensorEntity):
    """On when the current frame is flagged cheap or falls in the cheapest window."""

    _attr_name = "Is cheap now"

    def __init__(self, coordinator: PricingDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_is_cheap_now"
        self.entity_id = "binary_sensor.pstryk_is_cheap_now"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        current = data.frame_at(dt_util.utcnow())
        if current is None:
            return None
        if current.published and current.is_cheap:
            return True
        now = dt_util.utcnow()
        day = now.astimezone(TZ_WARSAW).date()
        hours = self._entry.options.get(CONF_WINDOW_HOURS, DEFAULT_WINDOW_HOURS)
        # Forward-looking window, same as the cheapest_window sensor.
        remaining = [f for f in data.for_day(day) if f.end > now]
        win = cheapest_window(remaining, hours)
        if win is None:
            return current.is_cheap if current.published else None
        return win.start <= current.start < win.end


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Pstryk Energy binary sensors."""
    pricing = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]
    async_add_entities([PstrykIsCheapNowSensor(pricing, entry)])
