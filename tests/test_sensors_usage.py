"""Usage sensor + binary sensor tests. Strategy: load entry with mocked HTTP, then push synthetic usage data."""
from datetime import datetime, timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.pstryk_energy.const import CONF_POLL_MINUTES, DOMAIN, TZ_WARSAW
from custom_components.pstryk_energy.models import (
    CostBreakdown,
    LatestReading,
    UsageData,
    UsageDay,
    UsageHour,
)
from tests.conftest import setup_entry
from tests.test_sensors_price import synthetic_pricing


def _warsaw_day_start(days_ago: int):
    d = dt_util.utcnow().astimezone(TZ_WARSAW).date() - timedelta(days=days_ago)
    return datetime.combine(d, datetime.min.time(), TZ_WARSAW).astimezone(dt_util.UTC)


def synthetic_usage():
    now = dt_util.utcnow()
    local = now.astimezone(TZ_WARSAW)
    today_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt_util.UTC)
    hours = tuple(
        UsageHour(start=today_start + timedelta(hours=h),
                  end=today_start + timedelta(hours=h + 1),
                  kwh=1.0 + h * 0.1, cost=0.5 + h * 0.05)
        for h in range(max(1, local.hour))
    )
    days = [
        UsageDay(start=_warsaw_day_start(2), kwh=5.5,
                 cost=CostBreakdown(6.0, 2.7, 0.8, 1.1, 0.36, 0.02, 1.02)),
        UsageDay(start=_warsaw_day_start(1), kwh=8.0,
                 cost=CostBreakdown(7.4, 3.3, 0.95, 1.32, 0.44, 0.03, 1.38)),
        UsageDay(start=today_start, kwh=sum(h.kwh for h in hours),
                 cost=CostBreakdown(sum(h.cost for h in hours), 1.0, 0.3, 0.4, 0.2, 0.01, 0.5)),
    ]
    latest = LatestReading(
        meter_as_of=now, meter_kwh_minute=0.0049, hour_cost=0.613,
        hour_cost_as_of=now.replace(minute=0, second=0, microsecond=0),
        is_cheap=True, is_expensive=False,
    )
    return UsageData(hours_today=hours, days_month=days, latest=latest)


async def test_cost_and_consumption_sensors(hass, aioclient_mock):
    local = dt_util.utcnow().astimezone(TZ_WARSAW)
    if local.day < 3:
        pytest.skip("synthetic day-2 frame falls in previous month on the 1st/2nd")
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["usage_coordinator"]
    data = synthetic_usage()
    # Installed HA (2026.9): async_set_updated_data is a plain sync callback.
    coordinator.async_set_updated_data(data)
    await hass.async_block_till_done()

    cost_today = hass.states.get("sensor.pstryk_cost_today")
    assert cost_today is not None
    expected_today = sum(h.cost for h in data.hours_today)
    assert abs(float(cost_today.state) - expected_today) < 0.01
    assert "energy_net" in cost_today.attributes
    # TOTAL + last_reset (Warsaw midnight), not TOTAL_INCREASING:
    # negative-spot dips must not read as resets.
    assert cost_today.attributes["state_class"] == "total"
    assert "last_reset" in cost_today.attributes

    cost_yesterday = hass.states.get("sensor.pstryk_cost_yesterday")
    assert abs(float(cost_yesterday.state) - 7.4) < 0.01
    assert cost_yesterday.attributes["state_class"] == "measurement"

    cost_month = hass.states.get("sensor.pstryk_cost_month")
    # Completed days only (today's partial frame excluded): 6.0 + 7.4.
    assert abs(float(cost_month.state) - 13.4) < 0.01
    assert cost_month.attributes["forecast"] > 0
    assert len(cost_month.attributes["daily"]) >= 2

    consumption_today = hass.states.get("sensor.pstryk_consumption_today")
    assert abs(float(consumption_today.state) - sum(h.kwh for h in data.hours_today)) < 0.01
    assert consumption_today.attributes["device_class"] == "energy"
    assert consumption_today.attributes["state_class"] == "total_increasing"
    assert len(consumption_today.attributes["hourly"]) == len(data.hours_today)

    consumption_yesterday = hass.states.get("sensor.pstryk_consumption_yesterday")
    assert abs(float(consumption_yesterday.state) - 8.0) < 0.01

    consumption_month = hass.states.get("sensor.pstryk_consumption_month")
    assert abs(float(consumption_month.state) - 13.5) < 0.01

    power = hass.states.get("sensor.pstryk_power")
    assert abs(float(power.state) - 0.0049 * 60) < 0.001
    assert power.attributes["device_class"] == "power"

    hourly_cost = hass.states.get("sensor.pstryk_hourly_cost")
    assert abs(float(hourly_cost.state) - 0.613) < 0.001


async def test_today_sensors_fall_back_to_day_frame(hass, aioclient_mock):
    """Empty hours_today + today's day frame present: live values from the day frame."""
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["usage_coordinator"]
    base = synthetic_usage()
    coordinator.async_set_updated_data(
        UsageData(hours_today=(), days_month=base.days_month, latest=base.latest)
    )
    await hass.async_block_till_done()

    today_frame = base.days_month[-1]  # synthetic_usage puts today's frame last
    consumption = hass.states.get("sensor.pstryk_consumption_today")
    assert consumption is not None
    assert abs(float(consumption.state) - today_frame.kwh) < 0.01
    cost = hass.states.get("sensor.pstryk_cost_today")
    assert abs(float(cost.state) - today_frame.cost.total) < 0.01


async def test_today_sensors_zero_before_first_fetch(hass, aioclient_mock):
    """Empty hours_today and no today day frame: 0.0, not unavailable."""
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["usage_coordinator"]
    base = synthetic_usage()
    today_local = dt_util.utcnow().astimezone(TZ_WARSAW).date()
    completed_days = tuple(
        d for d in base.days_month
        if d.start.astimezone(TZ_WARSAW).date() < today_local
    )
    coordinator.async_set_updated_data(
        UsageData(hours_today=(), days_month=completed_days, latest=base.latest)
    )
    await hass.async_block_till_done()

    for entity_id in ("sensor.pstryk_consumption_today", "sensor.pstryk_cost_today"):
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state != "unavailable"
        assert float(state.state) == 0.0


async def test_is_cheap_now_binary(hass, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock)
    usage = hass.data[DOMAIN][entry.entry_id]["usage_coordinator"]
    pricing = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]

    usage.async_set_updated_data(synthetic_usage())
    pricing.async_set_updated_data(synthetic_pricing())
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.pstryk_is_cheap_now")
    assert state is not None
    assert state.state in ("on", "off")


async def test_stale_yesterday_hours_excluded_from_today(hass, aioclient_mock):
    """Post-midnight stale fetch (hours from yesterday) must not count as today."""
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["usage_coordinator"]
    data = synthetic_usage()
    stale_hours = tuple(
        UsageHour(start=h.start - timedelta(days=1), end=h.end - timedelta(days=1),
                  kwh=h.kwh, cost=h.cost)
        for h in data.hours_today
    )
    coordinator.async_set_updated_data(
        UsageData(hours_today=stale_hours, days_month=data.days_month, latest=data.latest))
    await hass.async_block_till_done()

    today = dt_util.utcnow().astimezone(TZ_WARSAW).date()
    today_frame = next(
        d for d in data.days_month
        if d.start.astimezone(TZ_WARSAW).date() == today
    )
    cost = hass.states.get("sensor.pstryk_cost_today")
    assert abs(float(cost.state) - today_frame.cost.total) < 0.01
    consumption = hass.states.get("sensor.pstryk_consumption_today")
    assert abs(float(consumption.state) - today_frame.kwh) < 0.01
    assert consumption.attributes["hourly"] == []


async def test_previous_month_days_excluded_from_month_sensors(hass, aioclient_mock):
    """Daily window covers yesterday across month boundary; month sensors must
    still sum only the current month's completed days."""
    local = dt_util.utcnow().astimezone(TZ_WARSAW)
    if local.day < 3:
        pytest.skip("synthetic day-2 frame falls in previous month on the 1st/2nd")
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["usage_coordinator"]
    data = synthetic_usage()
    today_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt_util.UTC)
    prev_month_day = UsageDay(start=today_start - timedelta(days=32), kwh=99.0,
                              cost=CostBreakdown(99.0, 40.0, 10.0, 10.0, 5.0, 1.0, 20.0))
    coordinator.async_set_updated_data(
        UsageData(hours_today=data.hours_today,
                  days_month=(*data.days_month, prev_month_day),
                  latest=data.latest))
    await hass.async_block_till_done()

    cost_month = hass.states.get("sensor.pstryk_cost_month")
    assert abs(float(cost_month.state) - 13.4) < 0.01  # 6.0 + 7.4, not 112.4
    consumption_month = hass.states.get("sensor.pstryk_consumption_month")
    assert abs(float(consumption_month.state) - 13.5) < 0.01  # 5.5 + 8.0, not 112.5


async def test_power_unavailable_on_stale_meter_bucket(hass, aioclient_mock):
    """A frozen meter_as_of must not report constant power forever."""
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["usage_coordinator"]
    data = synthetic_usage()
    stale = LatestReading(
        meter_as_of=dt_util.utcnow() - timedelta(minutes=20),
        meter_kwh_minute=0.0049, hour_cost=0.613,
        hour_cost_as_of=data.latest.hour_cost_as_of,
        is_cheap=True, is_expensive=False,
    )
    coordinator.async_set_updated_data(
        UsageData(hours_today=data.hours_today, days_month=data.days_month, latest=stale))
    await hass.async_block_till_done()
    # default poll 10 -> threshold max(15, 1.5*10) = 15 min: 20 min stale is unknown
    assert hass.states.get("sensor.pstryk_power").state == "unknown"

    # Scaled threshold: poll 20 -> stale after max(15, 1.5*20) = 30 min,
    # so the same 20-min-old reading counts as fresh after the options change.
    hass.config_entries.async_update_entry(entry, options={CONF_POLL_MINUTES: 20})
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]["usage_coordinator"]
    coordinator.async_set_updated_data(
        UsageData(hours_today=data.hours_today, days_month=data.days_month, latest=stale))
    await hass.async_block_till_done()
    state = hass.states.get("sensor.pstryk_power")
    assert state.state != "unknown"
    assert abs(float(state.state) - 0.294) < 0.001  # 0.0049 kWh/min * 60


async def test_cost_today_breakdown_zeroed_when_day_frame_zero(hass, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["usage_coordinator"]
    data = synthetic_usage()
    local = dt_util.utcnow().astimezone(TZ_WARSAW)
    today_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt_util.UTC)
    zero_day = UsageDay(start=today_start, kwh=0.0,
                        cost=CostBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    coordinator.async_set_updated_data(
        UsageData(hours_today=data.hours_today, days_month=(zero_day,), latest=data.latest))
    await hass.async_block_till_done()
    attrs = hass.states.get("sensor.pstryk_cost_today").attributes
    assert attrs["energy_net"] == 0.0
    assert attrs["vat"] == 0.0
