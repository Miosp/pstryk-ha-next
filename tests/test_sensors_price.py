"""Price sensor tests. Strategy: load entry with mocked HTTP, then push synthetic data."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.pstryk_energy.const import (
    CONF_PRICE_BASIS,
    DEFAULT_WINDOW_HOURS,
    DOMAIN,
    PRICE_BASIS_NET,
    TZ_WARSAW,
)
from custom_components.pstryk_energy.models import PricingData, cheapest_window
from tests.conftest import setup_entry

UTC = timezone.utc


def price_frame(start_utc, gross, cheap=False):
    return {"start": start_utc.isoformat().replace("+00:00", "Z"),
            "end": (start_utc + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "metrics": {"pricing": {
                "price_gross": gross, "price_net": round(gross / 1.23, 4) if gross else None,
                "tge_price": gross, "dist_price": 0.1, "service_price": 0.08,
                "vat_component": 0.1, "excise_component": 0.005,
                "is_cheap": cheap, "is_expensive": False}}}


def _day_frames(day, gross_fn):
    """Wall-clock-complete hour frames of a Warsaw day (23/24/25 on DST days).

    Steps absolute time from local midnight while the frame start still
    falls on the target local date, mirroring real API bucketing.
    """
    midnight = datetime.combine(day, datetime.min.time(), TZ_WARSAW)
    frames = []
    h = 0
    while True:
        start = midnight + timedelta(hours=h)
        if start.astimezone(TZ_WARSAW).date() != day:
            return frames
        frames.append(price_frame(start.astimezone(UTC), gross_fn(h)))
        h += 1


def synthetic_pricing(now=None, tomorrow_published=False):
    """Frames: yesterday full, today full, tomorrow (null or published)."""
    now = now or dt_util.utcnow()
    local_today = now.astimezone(TZ_WARSAW).date()
    frames = []
    frames.extend(_day_frames(local_today - timedelta(days=1),
                              lambda h: 0.5 + (h % 3) * 0.2))
    frames.extend(_day_frames(local_today,
                              lambda h: {0: 0.40, 1: 0.41, 2: 0.39, 3: 0.90,
                                         4: 0.91, 5: 0.50, 6: 0.30}.get(h, 0.60)))
    frames.extend(_day_frames(local_today + timedelta(days=1),
                              lambda h: 0.55 if tomorrow_published else None))
    return PricingData.from_api({"frames": frames})


def unpublished_tail_pricing(now=None):
    """synthetic_pricing with every frame after the current hour unpublished."""
    now = now or dt_util.utcnow()
    data = synthetic_pricing(now, tomorrow_published=False)
    current = data.frame_at(now)
    assert current is not None and current.published
    return PricingData(frames=tuple(
        f if f.start <= current.start else replace(f, gross=None, net=None)
        for f in data.frames
    ))


async def test_current_price_and_attributes(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]
    # Installed HA (2026.9): async_set_updated_data is a plain sync callback.
    coordinator.async_set_updated_data(synthetic_pricing())
    await hass.async_block_till_done()

    state = hass.states.get("sensor.pstryk_current_price")
    assert state is not None
    assert float(state.state) > 0
    attrs = state.attributes
    assert attrs["unit_of_measurement"] == "PLN/kWh"
    today = dt_util.utcnow().astimezone(TZ_WARSAW).date()
    assert "today_prices" in attrs and len(attrs["today_prices"]) >= 23  # 23-25 on DST days
    assert attrs["hour_rank_today"] >= 1


async def test_tomorrow_unavailable_until_published(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]

    coordinator.async_set_updated_data(synthetic_pricing(tomorrow_published=False))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pstryk_tomorrow_avg_price").state == "unavailable"

    coordinator.async_set_updated_data(synthetic_pricing(tomorrow_published=True))
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.pstryk_tomorrow_avg_price").state) > 0


async def test_cheapest_window_sensor(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]
    data = synthetic_pricing()
    coordinator.async_set_updated_data(data)
    await hass.async_block_till_done()

    now = dt_util.utcnow()
    remaining = [
        f for f in data.for_day(now.astimezone(TZ_WARSAW).date()) if f.end > now
    ]
    state = hass.states.get("sensor.pstryk_cheapest_window")
    assert state is not None
    if len([f for f in remaining if f.published]) < DEFAULT_WINDOW_HOURS:
        # Late in the day: too few published hours remain for a 3h window.
        assert state.state == "unknown"
        return
    assert float(state.state) > 0
    assert state.attributes["length"] == 3  # default window hours
    assert "start" in state.attributes and "end" in state.attributes


async def test_next_price_change_is_timestamp(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]
    coordinator.async_set_updated_data(synthetic_pricing())
    await hass.async_block_till_done()

    state = hass.states.get("sensor.pstryk_next_price_change")
    assert state is not None
    assert state.attributes["device_class"] == "timestamp"


async def test_next_hour_price_matches_synthetic(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]
    now = dt_util.utcnow()
    data = synthetic_pricing(now, tomorrow_published=True)
    coordinator.async_set_updated_data(data)
    await hass.async_block_till_done()

    current = data.frame_at(now)
    nxt = data.frame_at(current.end)
    assert nxt is not None and nxt.published
    state = hass.states.get("sensor.pstryk_next_hour_price")
    assert state is not None
    assert abs(float(state.state) - nxt.gross) < 0.0001


async def test_next_hour_price_unknown_on_unpublished_tail(
    hass: HomeAssistant, aioclient_mock
):
    """Tomorrow unpublished and today's remaining hours unpublished -> no next price."""
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]
    coordinator.async_set_updated_data(unpublished_tail_pricing())
    await hass.async_block_till_done()

    state = hass.states.get("sensor.pstryk_next_hour_price")
    assert state is not None
    assert state.state == "unknown"


async def test_avg_and_window_honor_net_basis(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]
    data = synthetic_pricing()
    coordinator.async_set_updated_data(data)
    await hass.async_block_till_done()

    # Default basis is gross; flip the option to net (update listener reloads
    # the entry), then push synthetic data on the fresh coordinator.
    hass.config_entries.async_update_entry(entry, options={CONF_PRICE_BASIS: PRICE_BASIS_NET})
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]
    coordinator.async_set_updated_data(data)
    await hass.async_block_till_done()

    today = data.for_day(dt_util.utcnow().astimezone(TZ_WARSAW).date())
    published = [f for f in today if f.published]
    expected_avg = sum(f.net for f in published) / len(published)
    avg_state = float(hass.states.get("sensor.pstryk_today_avg_price").state)
    assert abs(avg_state - expected_avg) < 0.01

    # Window selection stays gross-based over REMAINING hours (forward-looking);
    # displayed avg must recompute on net.
    now = dt_util.utcnow()
    remaining = [f for f in today if f.end > now]
    win = cheapest_window(remaining, DEFAULT_WINDOW_HOURS)
    window_state_raw = hass.states.get("sensor.pstryk_cheapest_window").state
    if win is None or len(remaining) < DEFAULT_WINDOW_HOURS:
        assert window_state_raw == "unknown"
    else:
        win_frames = [f for f in remaining if win.start <= f.start < win.end]
        expected_window = sum(f.net for f in win_frames) / len(win_frames)
        assert abs(float(window_state_raw) - expected_window) < 0.01


async def test_cheapest_window_is_forward_looking(hass, aioclient_mock):
    """Elapsed cheap hours must not win; the window must start at or after now."""
    from datetime import datetime as dt_cls

    now = dt_util.utcnow()
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]
    # Custom data: everything before the current hour is ultra-cheap (elapsed),
    # remaining hours are moderate.
    data = synthetic_pricing(now=now, tomorrow_published=False)
    local_today = now.astimezone(TZ_WARSAW).date()
    rebuilt = []
    for f in data.frames:
        if f.start.astimezone(TZ_WARSAW).date() == local_today:
            cheap = f.end <= now
            rebuilt.append(price_frame(
                f.start.astimezone(UTC).astimezone(TZ_WARSAW).astimezone(UTC),
                0.05 if cheap else 0.80))
        else:
            rebuilt.append({
                "start": f.start.isoformat(), "end": f.end.isoformat(),
                "metrics": {"pricing": {
                    "price_gross": f.gross, "price_net": f.net,
                    "is_cheap": False, "is_expensive": False}}})
    rebuilt_data = PricingData.from_api({"frames": rebuilt})
    coordinator.async_set_updated_data(rebuilt_data)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.pstryk_cheapest_window")
    assert state is not None
    remaining = [
        f for f in rebuilt_data.for_day(now.astimezone(TZ_WARSAW).date())
        if f.end > now and f.published
    ]
    if len(remaining) < DEFAULT_WINDOW_HOURS:
        assert state.state == "unknown"  # too few published hours remain
        return
    win_start = dt_cls.fromisoformat(state.attributes["start"])
    assert win_start >= now.replace(minute=0, second=0, microsecond=0)
