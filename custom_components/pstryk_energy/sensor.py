"""Sensor entities for the Pstryk Energy integration."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_POLL_MINUTES,
    CONF_PRICE_BASIS,
    CONF_WINDOW_HOURS,
    DEFAULT_POLL_MINUTES,
    DEFAULT_PRICE_BASIS,
    DEFAULT_WINDOW_HOURS,
    DOMAIN,
    PRICE_BASIS_GROSS,
    TZ_WARSAW,
)
from .coordinator import (
    PricingDataCoordinator,
    UsageDataCoordinator,
)
from .models import (
    CheapestWindow,
    PriceFrame,
    PricingData,
    UsageData,
    UsageDay,
    cheapest_window,
    hour_rank,
    month_forecast,
    next_price_change,
)


class PstrykEntityBase(CoordinatorEntity):  # type: ignore[misc]
    """Shared base: device info for all Pstryk entities.

    Note: the installed HA (2026.9) derives entity ids from the friendly name
    (device name + entity name), which duplicates the "Pstryk" prefix, and no
    longer honors `_attr_suggested_object_id`. Entities therefore preset
    `entity_id` explicitly — the supported escape hatch — to guarantee
    `sensor.pstryk_*` object ids.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Pstryk Energy",
            manufacturer="Pstryk Energy",
        )

    @property
    def _basis(self) -> str:
        return self._entry.options.get(CONF_PRICE_BASIS, DEFAULT_PRICE_BASIS)


def _basis_value(frame: PriceFrame, basis: str) -> float | None:
    return frame.gross if basis == PRICE_BASIS_GROSS else frame.net


def _frame_prices(frames: list[PriceFrame]) -> list[dict]:
    return [
        {
            "start": f.start.isoformat(),
            "gross": f.gross,
            "net": f.net,
            "is_cheap": f.is_cheap,
        }
        for f in frames
    ]


def _today_day_frame(data: UsageData) -> UsageDay | None:
    """Today's partial-day row from days_month, if fetched yet."""
    today_local = dt_util.utcnow().astimezone(TZ_WARSAW).date()
    for day in data.days_month:
        if day.start.astimezone(TZ_WARSAW).date() == today_local:
            return day
    return None


class PstrykPriceSensor(PstrykEntityBase, SensorEntity):
    """Current hour buy price + full today/tomorrow lists."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "PLN/kWh"
    _attr_suggested_display_precision = 4
    _attr_name = "Current price"

    def __init__(self, coordinator: PricingDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_current_price"
        self.entity_id = "sensor.pstryk_current_price"

    def _current(self) -> PriceFrame | None:
        data: PricingData = self.coordinator.data
        if data is None:
            return None
        return data.frame_at(dt_util.utcnow())

    @property
    def native_value(self) -> float | None:
        frame = self._current()
        if frame is None or not frame.published:
            return None
        return frame.gross if self._basis == PRICE_BASIS_GROSS else frame.net

    @property
    def extra_state_attributes(self) -> dict:
        data: PricingData = self.coordinator.data
        frame = self._current()
        if data is None or frame is None:
            return {}
        today_date = dt_util.utcnow().astimezone(TZ_WARSAW).date()
        today = data.for_day(today_date)
        tomorrow = data.for_day(today_date + timedelta(days=1))
        return {
            "basis": self._basis,
            "net": frame.net,
            "gross": frame.gross,
            "tge_spot": frame.tge,
            "dist": frame.dist,
            "service": frame.service,
            "vat": frame.vat_component,
            "excise": frame.excise,
            "is_cheap": frame.is_cheap,
            "is_expensive": frame.is_expensive,
            "hour_rank_today": hour_rank(today, frame),
            "today_prices": _frame_prices(today),
            "tomorrow_prices": _frame_prices(tomorrow),
        }


class PstrykNextHourPriceSensor(PstrykEntityBase, SensorEntity):
    """Next hour buy price with delta vs current hour."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "PLN/kWh"
    _attr_suggested_display_precision = 4
    _attr_name = "Next hour price"

    def __init__(self, coordinator: PricingDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_next_hour_price"
        self.entity_id = "sensor.pstryk_next_hour_price"

    def _pair(self) -> tuple[PriceFrame, PriceFrame] | None:
        data: PricingData = self.coordinator.data
        if data is None:
            return None
        current = data.frame_at(dt_util.utcnow())
        if current is None or not current.published:
            return None
        nxt = data.frame_at(current.end)
        if nxt is None or not nxt.published:
            return None
        return current, nxt

    @property
    def native_value(self) -> float | None:
        pair = self._pair()
        if pair is None:
            return None
        _, nxt = pair
        return _basis_value(nxt, self._basis)

    @property
    def extra_state_attributes(self) -> dict:
        pair = self._pair()
        if pair is None:
            return {}
        current, nxt = pair
        nxt_value = _basis_value(nxt, self._basis)
        cur_value = _basis_value(current, self._basis)
        delta = (
            nxt_value - cur_value
            if nxt_value is not None and cur_value is not None
            else None
        )
        return {"delta_vs_current": delta}


class PstrykNextPriceChangeSensor(PstrykEntityBase, SensorEntity):
    """When the price next changes and to what."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_name = "Next price change"

    def __init__(self, coordinator: PricingDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_next_price_change"
        self.entity_id = "sensor.pstryk_next_price_change"

    def _change(self):
        data: PricingData = self.coordinator.data
        if data is None:
            return None
        current = data.frame_at(dt_util.utcnow())
        if current is None or not current.published:
            return None
        return next_price_change(data.frames, current)

    @property
    def native_value(self) -> datetime | None:
        change = self._change()
        return change[0] if change else None

    @property
    def extra_state_attributes(self) -> dict:
        data: PricingData = self.coordinator.data
        if data is None:
            return {}
        current = data.frame_at(dt_util.utcnow())
        if current is None or not current.published:
            return {}
        change = next_price_change(data.frames, current)
        if not change:
            return {}
        at, _, _ = change
        frame = data.frame_at(at)
        if frame is None or not frame.published:
            return {}
        new_value = _basis_value(frame, self._basis)
        current_value = _basis_value(current, self._basis)
        if new_value is None or current_value is None:
            return {}
        return {"new_price": new_value, "delta": new_value - current_value}


class PstrykAvgPriceSensor(PstrykEntityBase, SensorEntity):
    """Daily average price (today or tomorrow by `day_offset`)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "PLN/kWh"
    _attr_suggested_display_precision = 4

    def __init__(
        self, coordinator: PricingDataCoordinator, entry: ConfigEntry, day_offset: int
    ) -> None:
        super().__init__(coordinator, entry)
        self._day_offset = day_offset
        day = "today" if day_offset == 0 else "tomorrow"
        self._attr_unique_id = f"{entry.entry_id}_{day}_avg_price"
        self._attr_name = f"{day} avg price"
        self.entity_id = f"sensor.pstryk_{day}_avg_price"

    def _frames(self) -> list[PriceFrame]:
        data: PricingData = self.coordinator.data
        if data is None:
            return []
        day = dt_util.utcnow().astimezone(TZ_WARSAW).date() + timedelta(
            days=self._day_offset
        )
        return [f for f in data.for_day(day) if f.published]

    @property
    def available(self) -> bool:
        """Tomorrow stays unavailable until at least one frame is published."""
        if self._day_offset == 0:
            return super().available
        return super().available and bool(self._frames())

    def _basis_values(self, frames: list[PriceFrame]) -> list[float] | None:
        values = [_basis_value(f, self._basis) for f in frames]
        if any(v is None for v in values):
            return None
        return values

    @property
    def native_value(self) -> float | None:
        frames = self._frames()
        if not frames:
            return None
        values = self._basis_values(frames)
        if values is None:
            return None
        return sum(values) / len(values)

    @property
    def extra_state_attributes(self) -> dict:
        frames = self._frames()
        if not frames:
            return {}
        values = self._basis_values(frames)
        if values is None:
            return {}
        lo = frames[values.index(min(values))]
        hi = frames[values.index(max(values))]
        return {
            "min": min(values),
            "max": max(values),
            "min_hour": lo.start.astimezone(TZ_WARSAW).strftime("%H:00"),
            "max_hour": hi.start.astimezone(TZ_WARSAW).strftime("%H:00"),
        }


class PstrykCheapestWindowSensor(PstrykEntityBase, SensorEntity):
    """Cheapest consecutive-hours window today (avg price + bounds)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "PLN/kWh"
    _attr_suggested_display_precision = 4
    _attr_name = "Cheapest window"

    def __init__(self, coordinator: PricingDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_cheapest_window"
        self.entity_id = "sensor.pstryk_cheapest_window"

    def _window(self) -> CheapestWindow | None:
        data: PricingData = self.coordinator.data
        if data is None:
            return None
        now = dt_util.utcnow()
        day = now.astimezone(TZ_WARSAW).date()
        hours = self._entry.options.get(CONF_WINDOW_HOURS, DEFAULT_WINDOW_HOURS)
        # Forward-looking: only hours that have not fully elapsed, so the
        # window stays actionable for load-shifting automations.
        remaining = [f for f in data.for_day(day) if f.end > now]
        return cheapest_window(remaining, hours)

    @property
    def native_value(self) -> float | None:
        win = self._window()
        data: PricingData = self.coordinator.data
        if win is None or data is None:
            return None
        day = win.start.astimezone(TZ_WARSAW).date()
        frames = [f for f in data.for_day(day) if win.start <= f.start < win.end]
        values = [_basis_value(f, self._basis) for f in frames]
        if len(values) != win.hours or any(v is None for v in values):
            return None
        return sum(values) / win.hours

    @property
    def extra_state_attributes(self) -> dict:
        win = self._window()
        if not win:
            return {}
        return {
            "start": win.start.astimezone(TZ_WARSAW).isoformat(),
            "end": win.end.astimezone(TZ_WARSAW).isoformat(),
            "length": win.hours,
        }


def _today_hours(data: UsageData) -> list:
    """Hours belonging to today's Warsaw date only (stale rollover frames excluded)."""
    today = dt_util.utcnow().astimezone(TZ_WARSAW).date()
    return [h for h in data.hours_today if h.start.astimezone(TZ_WARSAW).date() == today]


def _completed_month_days(data: UsageData) -> list:
    """Completed days of the CURRENT Warsaw month (previous-month spillover excluded)."""
    today_local = dt_util.utcnow().astimezone(TZ_WARSAW).date()
    month_start = today_local.replace(day=1)
    return [d for d in data.days_month
            if month_start <= d.start.astimezone(TZ_WARSAW).date() < today_local]


class PstrykCostTodaySensor(PstrykEntityBase, SensorEntity):
    """Today's running cost: sum of hourly costs, with a scaled breakdown."""

    _attr_device_class = SensorDeviceClass.MONETARY
    # TOTAL + explicit last_reset (not TOTAL_INCREASING): negative-spot hours
    # can dip the running sum, which TOTAL_INCREASING would misread as a reset.
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "PLN"
    _attr_suggested_display_precision = 2
    _attr_name = "Cost today"

    def __init__(self, coordinator: UsageDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_cost_today"
        self.entity_id = "sensor.pstryk_cost_today"

    @property
    def last_reset(self) -> datetime:
        return (
            dt_util.utcnow()
            .astimezone(TZ_WARSAW)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(dt_util.UTC)
        )

    @property
    def native_value(self) -> float | None:
        data: UsageData | None = self.coordinator.data
        if not data:
            return None
        hours = _today_hours(data)
        if hours:
            return sum(h.cost for h in hours)
        # Warsaw midnight before the first hourly fetch: fall back to
        # today's partial day frame, else report zero rather than unknown.
        day = _today_day_frame(data)
        return day.cost.total if day else 0.0

    @property
    def extra_state_attributes(self) -> dict:
        data: UsageData | None = self.coordinator.data
        if not data or not data.days_month:
            return {}
        today_local = dt_util.utcnow().astimezone(TZ_WARSAW).date()
        hourly_total = sum(h.cost for h in _today_hours(data))
        today_frame = next(
            (d for d in data.days_month
             if d.start.astimezone(TZ_WARSAW).date() == today_local), None)
        if today_frame is None:
            return {}
        c = today_frame.cost
        if c.total > 0:
            return {
                "energy_net": hourly_total * c.energy_net / c.total,
                "dist_var_net": hourly_total * c.dist_var_net / c.total,
                "dist_fix_net": hourly_total * c.dist_fix_net / c.total,
                "service_net": hourly_total * c.service_net / c.total,
                "excise": hourly_total * c.excise / c.total,
                "vat": hourly_total * c.vat / c.total,
            }
        # Zero-total day frame (early day): keep attribute shape with zeros.
        return {k: 0.0 for k in
                ("energy_net", "dist_var_net", "dist_fix_net",
                 "service_net", "excise", "vat")}


class PstrykCostYesterdaySensor(PstrykEntityBase, SensorEntity):
    """Cost of the last completed day, with its full breakdown."""

    _attr_device_class = SensorDeviceClass.MONETARY
    # Period-report value (replaces wholesale at rollover): MEASUREMENT so
    # the recorder does not treat the drop as a meter anomaly.
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "PLN"
    _attr_suggested_display_precision = 2
    _attr_name = "Cost yesterday"

    def __init__(self, coordinator: UsageDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_cost_yesterday"
        self.entity_id = "sensor.pstryk_cost_yesterday"

    def _day(self) -> UsageDay | None:
        data: UsageData | None = self.coordinator.data
        if not data:
            return None
        yesterday = dt_util.utcnow().astimezone(TZ_WARSAW).date() - timedelta(days=1)
        for day in data.days_month:
            if day.start.astimezone(TZ_WARSAW).date() == yesterday:
                return day
        return None

    @property
    def native_value(self) -> float | None:
        day = self._day()
        return day.cost.total if day else None

    @property
    def extra_state_attributes(self) -> dict:
        day = self._day()
        if not day:
            return {}
        c = day.cost
        return {"energy_net": c.energy_net, "dist_var_net": c.dist_var_net,
                "dist_fix_net": c.dist_fix_net, "service_net": c.service_net,
                "excise": c.excise, "vat": c.vat}


class PstrykCostMonthSensor(PstrykEntityBase, SensorEntity):
    """Month-to-date cost over completed days, with a linear forecast."""

    _attr_device_class = SensorDeviceClass.MONETARY
    # Period-report value (replaces wholesale at rollover): MEASUREMENT.
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "PLN"
    _attr_suggested_display_precision = 2
    _attr_name = "Cost month"

    def __init__(self, coordinator: UsageDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_cost_month"
        self.entity_id = "sensor.pstryk_cost_month"

    def _completed_days(self) -> list[UsageDay]:
        data: UsageData | None = self.coordinator.data
        if not data:
            return []
        return _completed_month_days(data)

    @property
    def native_value(self) -> float | None:
        days = self._completed_days()
        if not days:
            return None
        return sum(d.cost.total for d in days)

    @property
    def extra_state_attributes(self) -> dict:
        days = self._completed_days()
        if not days:
            return {}
        mtd = sum(d.cost.total for d in days)
        now_local = dt_util.utcnow().astimezone(TZ_WARSAW)
        completed_calendar_days = max(1, now_local.day - 1)
        return {
            "forecast": round(month_forecast(mtd, now_local), 2),
            # Same denominator as the forecast so gap days cannot make the
            # two daily averages disagree.
            "avg_per_day": round(mtd / completed_calendar_days, 2),
            "daily": [
                {"start": d.start.astimezone(TZ_WARSAW).date().isoformat(),
                 "cost": round(d.cost.total, 2)}
                for d in days
            ],
        }


class PstrykHourlyCostSensor(PstrykEntityBase, SensorEntity):
    """Cost of the last completed hour."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "PLN"
    _attr_suggested_display_precision = 2
    _attr_name = "Hourly cost"

    def __init__(self, coordinator: UsageDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_hourly_cost"
        self.entity_id = "sensor.pstryk_hourly_cost"

    @property
    def native_value(self) -> float | None:
        data: UsageData | None = self.coordinator.data
        return data.latest.hour_cost if data else None

    @property
    def extra_state_attributes(self) -> dict:
        data: UsageData | None = self.coordinator.data
        return {"as_of": data.latest.hour_cost_as_of.isoformat()} if data else {}


class PstrykConsumptionTodaySensor(PstrykEntityBase, SensorEntity):
    """Today's kWh so far, with per-hour detail."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2
    _attr_name = "Consumption today"

    def __init__(self, coordinator: UsageDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_consumption_today"
        self.entity_id = "sensor.pstryk_consumption_today"

    @property
    def native_value(self) -> float | None:
        data: UsageData | None = self.coordinator.data
        if not data:
            return None
        hours = _today_hours(data)
        if hours:
            return sum(h.kwh for h in hours)
        day = _today_day_frame(data)
        return day.kwh if day else 0.0

    @property
    def extra_state_attributes(self) -> dict:
        data: UsageData | None = self.coordinator.data
        if not data:
            return {}
        return {"hourly": [
            {"start": h.start.astimezone(TZ_WARSAW).isoformat(),
             "kwh": round(h.kwh, 3), "cost": round(h.cost, 2)}
            for h in _today_hours(data)
        ]}


class PstrykConsumptionDaySensor(PstrykEntityBase, SensorEntity):
    """Yesterday (single day) or month (sum of completed days)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    # Period-report values (yesterday / month): MEASUREMENT, not meters.
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: UsageDataCoordinator, entry: ConfigEntry, kind: str) -> None:
        super().__init__(coordinator, entry)
        self._kind = kind
        self._attr_unique_id = f"{entry.entry_id}_consumption_{kind}"
        self._attr_name = f"Consumption {kind}"
        self.entity_id = f"sensor.pstryk_consumption_{kind}"

    @property
    def native_value(self) -> float | None:
        data: UsageData | None = self.coordinator.data
        if not data:
            return None
        today_local = dt_util.utcnow().astimezone(TZ_WARSAW).date()
        if self._kind == "yesterday":
            target = today_local - timedelta(days=1)
            for day in data.days_month:
                if day.start.astimezone(TZ_WARSAW).date() == target:
                    return day.kwh
            return None
        days = _completed_month_days(data)
        return sum(d.kwh for d in days) if days else None


class PstrykPowerSensor(PstrykEntityBase, SensorEntity):
    """Instantaneous power estimate: last-minute kWh scaled to kW."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kW"
    _attr_suggested_display_precision = 3
    _attr_name = "Power"

    def __init__(self, coordinator: UsageDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_power"
        self.entity_id = "sensor.pstryk_power"

    @property
    def native_value(self) -> float | None:
        data: UsageData | None = self.coordinator.data
        if data is None:
            return None
        # A stalled feed must not report a constant power forever.
        poll_minutes = self._entry.options.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES)
        stale_after = timedelta(minutes=max(15, 1.5 * poll_minutes))
        if dt_util.utcnow() - data.latest.meter_as_of > stale_after:
            return None
        return round(data.latest.meter_kwh_minute * 60, 3)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up price and usage sensors for a Pstryk Energy config entry."""
    pricing = hass.data[DOMAIN][entry.entry_id]["pricing_coordinator"]
    usage = hass.data[DOMAIN][entry.entry_id]["usage_coordinator"]
    async_add_entities(
        [
            PstrykPriceSensor(pricing, entry),
            PstrykNextHourPriceSensor(pricing, entry),
            PstrykNextPriceChangeSensor(pricing, entry),
            PstrykAvgPriceSensor(pricing, entry, day_offset=0),
            PstrykAvgPriceSensor(pricing, entry, day_offset=1),
            PstrykCheapestWindowSensor(pricing, entry),
            PstrykCostTodaySensor(usage, entry),
            PstrykCostYesterdaySensor(usage, entry),
            PstrykCostMonthSensor(usage, entry),
            PstrykHourlyCostSensor(usage, entry),
            PstrykConsumptionTodaySensor(usage, entry),
            PstrykConsumptionDaySensor(usage, entry, "yesterday"),
            PstrykConsumptionDaySensor(usage, entry, "month"),
            PstrykPowerSensor(usage, entry),
        ]
    )
