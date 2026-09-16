"""Diagnostics support for Pstryk Energy."""
from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, DOMAIN

TO_REDACT = {CONF_API_KEY}


def _health(coordinator) -> dict[str, Any]:
    return {
        "last_update_success": coordinator.last_update_success,
        "last_exception": str(coordinator.last_exception)
        if coordinator.last_exception
        else None,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted config plus coordinator data summaries."""
    data = hass.data[DOMAIN][entry.entry_id]
    pricing_coordinator = data["pricing_coordinator"]
    usage_coordinator = data["usage_coordinator"]
    pricing = pricing_coordinator.data
    usage = usage_coordinator.data
    return {
        "config": {"data": async_redact_data(entry.data, TO_REDACT)},
        "options": async_redact_data(entry.options, TO_REDACT),
        "coordinators": {
            "pricing": _health(pricing_coordinator),
            "usage": _health(usage_coordinator),
        },
        "pricing": {
            "frame_count": len(pricing.frames) if pricing else 0,
            "published_count": sum(1 for f in pricing.frames if f.published)
            if pricing
            else 0,
            "frames": [
                dataclasses.asdict(f)
                | {"start": f.start.isoformat(), "end": f.end.isoformat()}
                for f in (pricing.frames if pricing else [])
            ],
        },
        "usage": {
            "hours_today": [
                dataclasses.asdict(h)
                | {"start": h.start.isoformat(), "end": h.end.isoformat()}
                for h in (usage.hours_today if usage else [])
            ],
            "days_month_count": len(usage.days_month) if usage else 0,
        },
    }
