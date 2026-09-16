"""Tests for pstryk_energy.models — pure logic, no HA imports needed."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from custom_components.pstryk_energy.models import (
    PricingData,
    cheapest_window,
    hour_rank,
    month_forecast,
    next_price_change,
    parse_daily,
    parse_hourly,
    parse_latest,
)

UTC = timezone.utc
TZ = ZoneInfo("Europe/Warsaw")


def price_frame(start_h, gross, cheap=False, expensive=False):
    start = datetime(2026, 9, 16, start_h, tzinfo=UTC)
    return {
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": (start + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "metrics": {"pricing": {
            "price_gross": gross,
            "price_net": round(gross / 1.23, 4) if gross is not None else None,
            "tge_price": gross,
            "dist_price": 0.1, "service_price": 0.08,
            "vat_component": 0.1, "excise_component": 0.005,
            "is_cheap": cheap, "is_expensive": expensive,
        }},
    }


def pricing_payload(hours: dict[int, float | None]):
    return {"frames": [price_frame(h, p) for h, p in sorted(hours.items())]}


def test_price_frame_null_tomorrow_is_unpublished():
    data = PricingData.from_api(pricing_payload({10: 0.5, 11: None}))
    assert data.frames[0].published is True
    assert data.frames[1].published is False
    assert data.frames[1].gross is None


def test_for_day_filters_by_warsaw_date():
    # 2026-09-15T22:00Z == 2026-09-16 00:00 Warsaw
    payload = {"frames": [price_frame(22, 0.5)]}
    payload["frames"][0]["start"] = "2026-09-15T22:00:00Z"
    payload["frames"][0]["end"] = "2026-09-16T23:00:00Z"
    data = PricingData.from_api(payload)
    assert data.for_day(date(2026, 9, 16)) == [data.frames[0]]


def test_cheapest_window_three_consecutive():
    frames = PricingData.from_api(pricing_payload(
        {0: 1.0, 1: 0.2, 2: 0.3, 3: 0.4, 4: 0.9})).frames
    win = cheapest_window(frames, 3)
    assert win is not None
    assert win.hours == 3
    assert abs(win.avg_price - 0.3) < 1e-9  # hours 1+2+3
    assert win.start.hour == 1
    assert win.end.hour == 4


def test_cheapest_window_requires_three_published_consecutive():
    frames = PricingData.from_api(pricing_payload(
        {0: 1.0, 1: 0.2, 2: None, 3: 0.4, 4: 0.9})).frames
    # published: 0,1,3,4 — no run of 3 time-consecutive published frames (gap at 2)
    assert cheapest_window(frames, 3) is None


def test_cheapest_window_too_few_published():
    frames = PricingData.from_api(pricing_payload({0: 1.0, 1: 0.2})).frames
    assert cheapest_window(frames, 3) is None


def test_hour_rank_cheapest_is_one():
    frames = PricingData.from_api(pricing_payload(
        {0: 0.9, 1: 0.2, 2: 0.5, 3: 0.4})).frames
    assert hour_rank(frames, frames[1]) == 1
    assert hour_rank(frames, frames[0]) == 4


def test_next_price_change_skips_equal_prices():
    frames = PricingData.from_api(pricing_payload(
        {0: 0.5, 1: 0.5, 2: 0.8, 3: None})).frames
    change = next_price_change(frames, frames[0])
    assert change is not None
    at, new, delta = change
    assert at.hour == 2 and new == 0.8 and abs(delta - 0.3) < 1e-9


def test_next_price_change_none_when_last_published():
    frames = PricingData.from_api(pricing_payload({0: 0.5})).frames
    assert next_price_change(frames, frames[0]) is None


def test_month_forecast_mid_month():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=TZ)
    # completed days = 15; 310/15*30 = 620
    assert abs(month_forecast(310.0, now) - 620.0) < 0.01


def test_month_forecast_first_day_returns_mtd():
    now = datetime(2026, 9, 1, 10, 0, tzinfo=TZ)
    assert month_forecast(50.0, now) == 50.0


LATEST = {"frames": {
    "meter_values": {"resolution": 1, "as_of": "2026-09-16T11:14:00Z",
                     "energy_active_import_register": 0.0049,
                     "energy_active_export_register": 0, "energy_balance": 0.0049},
    "cost": {"resolution": 3, "as_of": "2026-09-16T11:00:00Z",
             "energy_import_cost": 0.613, "energy_cost_net": 0.237,
             "var_dist_cost_net": 0.156, "fix_dist_cost_net": 0.0548,
             "service_cost_net": 0.047, "excise": 0.0029, "vat": 0.114},
    "pricing": {"resolution": 3, "as_of": "2026-09-16T11:00:00Z",
                "price_gross": 0.92, "tge_price": 0.40, "dist_price": 0.26,
                "service_price": 0.08, "is_cheap": False, "is_expensive": False},
}}


def test_parse_latest_semantics():
    latest = parse_latest(LATEST)
    assert latest.meter_as_of == datetime(2026, 9, 16, 11, 14, tzinfo=UTC)
    assert abs(latest.meter_kwh_minute - 0.0049) < 1e-9
    assert abs(latest.hour_cost - 0.613) < 1e-9
    assert latest.is_cheap is False


HOURLY = {"frames": [
    {"start": "2026-09-15T22:00:00Z", "end": "2026-09-15T23:00:00Z",
     "metrics": {"meter_values": {"energy_active_import_register": 0.5,
                                   "energy_active_export_register": 0, "energy_balance": 0.5},
                 "cost": {"energy_import_cost": 0.61}}},
    {"start": "2026-09-15T23:00:00Z", "end": "2026-09-16T00:00:00Z",
     "metrics": {"meter_values": {"energy_active_import_register": 0.7,
                                   "energy_active_export_register": 0, "energy_balance": 0.7},
                 "cost": {"energy_import_cost": 0.42}}},
]}


def test_parse_hourly():
    hours = parse_hourly(HOURLY)
    assert len(hours) == 2
    assert abs(hours[0].kwh - 0.5) < 1e-9
    assert abs(hours[1].cost - 0.42) < 1e-9
    assert hours[1].start.hour == 23


DAILY = {"frames": [
    {"start": "2026-08-31T22:00:00Z", "end": "2026-09-01T22:00:00Z",
     "metrics": {"meter_values": {"energy_active_import_register": 5.455,
                                   "energy_active_export_register": 0, "energy_balance": 5.455},
                 "cost": {"energy_import_cost": 7.385, "energy_cost_net": 3.277,
                          "var_dist_cost_net": 0.952, "fix_dist_cost_net": 1.315,
                          "service_cost_net": 0.436, "excise": 0.027, "vat": 1.375}}},
]}


def test_parse_daily_breakdown():
    days = parse_daily(DAILY)
    assert len(days) == 1
    assert abs(days[0].kwh - 5.455) < 1e-9
    assert abs(days[0].cost.total - 7.385) < 1e-9
    assert abs(days[0].cost.dist_fix_net - 1.315) < 1e-9
