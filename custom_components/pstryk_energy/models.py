"""Data models and derived math for the Pstryk Energy integration.

All datetimes are timezone-aware UTC except where the name says _local.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Sequence

from .const import TZ_WARSAW


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class PriceFrame:
    """One hourly pricing bucket. Unpublished buckets have null TGE-derived fields."""

    start: datetime
    end: datetime
    gross: float | None
    net: float | None
    tge: float | None
    dist: float
    service: float
    vat_component: float | None
    excise: float
    is_cheap: bool
    is_expensive: bool

    @classmethod
    def from_api(cls, frame: dict[str, Any]) -> "PriceFrame":
        m = frame["metrics"]["pricing"]
        return cls(
            start=_parse_dt(frame["start"]),
            end=_parse_dt(frame["end"]),
            gross=m.get("price_gross"),
            net=m.get("price_net"),
            tge=m.get("tge_price"),
            dist=m.get("dist_price") or 0.0,
            service=m.get("service_price") or 0.0,
            vat_component=m.get("vat_component"),
            excise=m.get("excise_component") or 0.0,
            is_cheap=bool(m.get("is_cheap", False)),
            is_expensive=bool(m.get("is_expensive", False)),
        )

    @property
    def published(self) -> bool:
        return self.gross is not None


@dataclass(frozen=True)
class PricingData:
    """Parsed pricing range payload."""

    frames: tuple[PriceFrame, ...]

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "PricingData":
        return cls(frames=tuple(PriceFrame.from_api(f) for f in payload.get("frames", [])))

    def for_day(self, day: date) -> list[PriceFrame]:
        """Frames whose start falls on the given Warsaw calendar date."""
        return [f for f in self.frames if f.start.astimezone(TZ_WARSAW).date() == day]

    def frame_at(self, moment: datetime) -> PriceFrame | None:
        for f in self.frames:
            if f.start <= moment < f.end:
                return f
        return None


@dataclass(frozen=True)
class CheapestWindow:
    start: datetime
    end: datetime
    hours: int
    avg_price: float


def _published_runs(frames: Sequence[PriceFrame]) -> list[list[PriceFrame]]:
    """Split published frames into time-consecutive runs (no gaps)."""
    runs: list[list[PriceFrame]] = []
    current: list[PriceFrame] = []
    for f in (f for f in frames if f.published):
        if current and f.start != current[-1].end:
            runs.append(current)
            current = []
        current.append(f)
    if current:
        runs.append(current)
    return runs


def cheapest_window(frames: Sequence[PriceFrame], hours: int) -> CheapestWindow | None:
    """Cheapest run of `hours` time-consecutive published frames."""
    best: tuple[float, list[PriceFrame]] | None = None
    for run in _published_runs(frames):
        for i in range(len(run) - hours + 1):
            window = run[i : i + hours]
            avg = sum(f.gross for f in window) / hours  # type: ignore[misc]
            if best is None or avg < best[0]:
                best = (avg, window)
    if best is None:
        return None
    avg, window = best
    return CheapestWindow(start=window[0].start, end=window[-1].end, hours=hours, avg_price=avg)


def hour_rank(frames: Sequence[PriceFrame], target: PriceFrame) -> int | None:
    """Rank of `target` among published frames by gross price, 1 = cheapest."""
    if not target.published:
        return None
    ordered = sorted((f for f in frames if f.published), key=lambda f: f.gross)  # type: ignore[misc]
    for rank, f in enumerate(ordered, start=1):
        if f.start == target.start:
            return rank
    return None


def next_price_change(
    frames: Sequence[PriceFrame], current: PriceFrame
) -> tuple[datetime, float, float] | None:
    """First later published frame with a different gross price: (at, new_price, delta)."""
    for f in sorted((f for f in frames if f.published and f.start > current.start), key=lambda f: f.start):
        if f.gross != current.gross:
            return f.start, f.gross, f.gross - current.gross  # type: ignore[misc]
    return None


def month_forecast(month_to_date: float, now_local: datetime) -> float:
    """Linear month-end projection: completed-days average × days in month.

    `month_to_date` covers COMPLETED days only (today excluded), so the
    denominator is the completed-day count, not elapsed fractional days.
    """
    days_in_month = calendar.monthrange(now_local.year, now_local.month)[1]
    completed = now_local.day - 1
    if completed < 1:
        return month_to_date
    return month_to_date / completed * days_in_month


@dataclass(frozen=True)
class CostBreakdown:
    total: float
    energy_net: float
    dist_var_net: float
    dist_fix_net: float
    service_net: float
    excise: float
    vat: float


@dataclass(frozen=True)
class UsageHour:
    start: datetime
    end: datetime
    kwh: float
    cost: float  # gross energy_import_cost


@dataclass(frozen=True)
class UsageDay:
    start: datetime
    kwh: float
    cost: CostBreakdown


def parse_hourly(payload: dict[str, Any]) -> tuple[UsageHour, ...]:
    hours: list[UsageHour] = []
    for frame in payload.get("frames", []):
        m = frame.get("metrics", {})
        meter = m.get("meter_values", {})
        cost = m.get("cost", {})
        hours.append(UsageHour(
            start=_parse_dt(frame["start"]),
            end=_parse_dt(frame["end"]),
            kwh=float(meter.get("energy_active_import_register") or 0.0),
            cost=float(cost.get("energy_import_cost") or 0.0),
        ))
    return tuple(hours)


def parse_daily(payload: dict[str, Any]) -> tuple[UsageDay, ...]:
    days: list[UsageDay] = []
    for frame in payload.get("frames", []):
        m = frame.get("metrics", {})
        meter = m.get("meter_values", {})
        c = m.get("cost", {})
        days.append(UsageDay(
            start=_parse_dt(frame["start"]),
            kwh=float(meter.get("energy_active_import_register") or 0.0),
            cost=CostBreakdown(
                total=float(c.get("energy_import_cost") or 0.0),
                energy_net=float(c.get("energy_cost_net") or 0.0),
                dist_var_net=float(c.get("var_dist_cost_net") or 0.0),
                dist_fix_net=float(c.get("fix_dist_cost_net") or 0.0),
                service_net=float(c.get("service_cost_net") or 0.0),
                excise=float(c.get("excise") or 0.0),
                vat=float(c.get("vat") or 0.0),
            ),
        ))
    return tuple(days)


@dataclass(frozen=True)
class LatestReading:
    """temporal=latest result. meter = last-minute kWh; cost = last completed hour."""

    meter_as_of: datetime
    meter_kwh_minute: float
    hour_cost: float
    hour_cost_as_of: datetime
    is_cheap: bool
    is_expensive: bool


def parse_latest(payload: dict[str, Any]) -> LatestReading:
    frames = payload["frames"]
    meter = frames["meter_values"]
    cost = frames["cost"]
    pricing = frames["pricing"]
    return LatestReading(
        meter_as_of=_parse_dt(meter["as_of"]),
        meter_kwh_minute=float(meter.get("energy_active_import_register") or 0.0),
        hour_cost=float(cost.get("energy_import_cost") or 0.0),
        hour_cost_as_of=_parse_dt(cost["as_of"]),
        is_cheap=bool(pricing.get("is_cheap", False)),
        is_expensive=bool(pricing.get("is_expensive", False)),
    )


@dataclass(frozen=True)
class UsageData:
    hours_today: tuple[UsageHour, ...]
    days_month: tuple[UsageDay, ...]
    latest: LatestReading
