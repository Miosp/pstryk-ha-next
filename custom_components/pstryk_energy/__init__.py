"""The Pstryk Energy integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PstrykApiClient
from .const import (
    CONF_API_KEY,
    CONF_POLL_MINUTES,
    DEFAULT_POLL_MINUTES,
    DOMAIN,
)
from .coordinator import (
    PricingDataCoordinator,
    UsageDataCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ("sensor", "binary_sensor")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pstryk Energy from a config entry."""
    client = PstrykApiClient(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    pricing_coordinator = PricingDataCoordinator(hass, client)
    usage_coordinator = UsageDataCoordinator(
        hass, client, entry.options.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES)
    )
    await pricing_coordinator.async_config_entry_first_refresh()
    await usage_coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "pricing_coordinator": pricing_coordinator,
        "usage_coordinator": usage_coordinator,
    }
    # Note: installed HA (2026.9) replaced async_forward_platform_setups.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Pstryk Energy config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
