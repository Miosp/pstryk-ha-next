"""Coordinator tests with mocked client."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util import dt as dt_util

from custom_components.pstryk_energy.api import (
    PstrykApiClient,
    PstrykAuthError,
    PstrykRateLimited,
)
from custom_components.pstryk_energy.coordinator import (
    PricingDataCoordinator,
    UsageDataCoordinator,
    _needs_day_refetch,
    _needs_hour_refetch,
    _next_refresh_interval,
)
from custom_components.pstryk_energy.const import TZ_WARSAW

UTC = timezone.utc


def frame(start_h, gross):
    start = datetime(2026, 9, 16, start_h, tzinfo=UTC)
    return {"start": start.isoformat().replace("+00:00", "Z"),
            "end": (start + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "metrics": {"pricing": {"price_gross": gross, "price_net": gross,
                                    "is_cheap": False, "is_expensive": False}}}


def latest_payload():
    as_of = "2026-09-16T10:00:00Z"
    return {"frames": {
        "meter_values": {"as_of": as_of},
        "cost": {"as_of": as_of, "energy_import_cost": 0.5},
        "pricing": {},
    }}


async def test_pricing_coordinator_parses_range(hass: HomeAssistant):
    client = MagicMock(spec=PstrykApiClient)
    client.async_pricing_range.return_value = {"frames": [frame(10, 0.5), frame(11, None)]}
    coord = PricingDataCoordinator(hass, client)
    data = await coord._async_update_data()
    assert len(data.frames) == 2
    assert data.frames[1].published is False
    start_arg, end_arg = client.async_pricing_range.call_args[0]
    span = end_arg - start_arg
    assert timedelta(hours=71) <= span <= timedelta(hours=73)  # 3-day window


async def test_pricing_coordinator_auth_error(hass: HomeAssistant):
    client = MagicMock(spec=PstrykApiClient)
    client.async_pricing_range.side_effect = PstrykAuthError("401")
    coord = PricingDataCoordinator(hass, client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()


async def test_pricing_coordinator_rate_limited(hass: HomeAssistant):
    from homeassistant.helpers.update_coordinator import UpdateFailed

    client = MagicMock(spec=PstrykApiClient)
    client.async_pricing_range.side_effect = PstrykRateLimited(120)
    coord = PricingDataCoordinator(hass, client)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_usage_coordinator_gates_subfetches(hass: HomeAssistant):
    client = MagicMock(spec=PstrykApiClient)
    client.async_latest.return_value = latest_payload()
    client.async_usage_hourly.return_value = {"frames": []}
    client.async_usage_daily.return_value = {"frames": []}
    coord = UsageDataCoordinator(hass, client, poll_minutes=10)
    await coord._async_update_data()
    assert client.async_latest.call_count == 1
    assert client.async_usage_hourly.call_count == 1
    assert client.async_usage_daily.call_count == 1
    # second poll within the hour: only latest refetched
    await coord._async_update_data()
    assert client.async_latest.call_count == 2
    assert client.async_usage_hourly.call_count == 1
    assert client.async_usage_daily.call_count == 1
    # simulate hour rollover
    coord._last_hour_fetch = dt_util.utcnow() - timedelta(minutes=56)
    await coord._async_update_data()
    assert client.async_usage_hourly.call_count == 2
    assert client.async_usage_daily.call_count == 1


async def test_usage_daily_window_covers_month_and_yesterday(hass: HomeAssistant):
    client = MagicMock(spec=PstrykApiClient)
    client.async_latest.return_value = latest_payload()
    client.async_usage_hourly.return_value = {"frames": []}
    client.async_usage_daily.return_value = {"frames": []}
    coord = UsageDataCoordinator(hass, client, poll_minutes=10)
    await coord._async_update_data()
    start_arg = client.async_usage_daily.call_args[0][0]
    local = start_arg.astimezone(TZ_WARSAW)
    today = dt_util.utcnow().astimezone(TZ_WARSAW).date()
    yesterday = today - timedelta(days=1)
    month_start = today.replace(day=1)
    assert local.date() == min(month_start, yesterday)
    assert local.hour == 0


def test_needs_hour_refetch_gates():
    t0 = datetime(2026, 9, 16, 12, 0, tzinfo=dt_util.UTC)
    assert _needs_hour_refetch(None, t0) is True
    assert _needs_hour_refetch(t0 - timedelta(minutes=10), t0) is False
    assert _needs_hour_refetch(t0 - timedelta(minutes=56), t0) is True
    # rollover isolated: fetched 5 min before Warsaw midnight, now just after
    # (delta < 55 min but Warsaw date changed) -> must refetch
    late = datetime(2026, 9, 16, 23, 56, tzinfo=TZ_WARSAW)
    early = datetime(2026, 9, 17, 0, 1, tzinfo=TZ_WARSAW)
    assert _needs_hour_refetch(late, early) is True


async def test_pricing_refresh_aligns_to_hour_boundary(hass: HomeAssistant):
    client = MagicMock(spec=PstrykApiClient)
    client.async_pricing_range.return_value = {"frames": [frame(10, 0.5)]}
    coord = PricingDataCoordinator(hass, client)
    await coord._async_update_data()
    assert timedelta(seconds=30) <= coord.update_interval <= timedelta(minutes=30)


def test_next_refresh_interval_aligned_and_capped():
    t = datetime(2026, 9, 16, 12, 10, tzinfo=dt_util.UTC)
    assert _next_refresh_interval(t) == timedelta(minutes=30)  # 50m15s to boundary -> capped
    t2 = datetime(2026, 9, 16, 12, 59, 50, tzinfo=dt_util.UTC)
    assert _next_refresh_interval(t2) == timedelta(seconds=30)  # 25s to boundary -> floored
    t3 = datetime(2026, 9, 16, 12, 30, 0, tzinfo=dt_util.UTC)
    # 13:00:15 - 12:30:00 = 30m15s -> capped at 30m
    assert _next_refresh_interval(t3) == timedelta(minutes=30)


def test_needs_day_refetch_gates():
    t0 = datetime(2026, 9, 16, 12, 0, tzinfo=dt_util.UTC)
    assert _needs_day_refetch(None, t0) is True
    assert _needs_day_refetch(t0 - timedelta(hours=1), t0) is False
    assert _needs_day_refetch(t0 - timedelta(hours=7), t0) is True
    # post-midnight: fetched minutes before Warsaw midnight -> refetch
    late = datetime(2026, 9, 16, 23, 56, tzinfo=TZ_WARSAW)
    early = datetime(2026, 9, 17, 0, 1, tzinfo=TZ_WARSAW)
    assert _needs_day_refetch(late, early) is True
