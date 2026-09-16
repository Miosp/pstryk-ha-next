"""Data update coordinators for pricing and usage."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TypeVar

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .api import PstrykApiClient, PstrykAPIError, PstrykAuthError, PstrykRateLimited
from .const import DOMAIN, TZ_WARSAW
from .models import (
    PricingData,
    UsageData,
    parse_daily,
    parse_hourly,
    parse_latest,
)

_LOGGER = logging.getLogger(__name__)

_DataT = TypeVar("_DataT")


def _warsaw_midnight(days_ago: int) -> datetime:
    # Navigate on the DATE component: absolute timedelta subtraction would
    # land at 23:00/01:00 local when the span crosses a DST transition night.
    local = dt_util.utcnow().astimezone(TZ_WARSAW)
    day = local.date() - timedelta(days=days_ago)
    return datetime(day.year, day.month, day.day, tzinfo=TZ_WARSAW).astimezone(dt_util.UTC)


def _needs_hour_refetch(last_fetch: datetime | None, now: datetime) -> bool:
    """Hourly frames must refresh on the 55-min cadence AND on Warsaw rollover,
    so stale yesterday-hours never masquerade as today's totals."""
    if last_fetch is None:
        return True
    if (now - last_fetch) > timedelta(minutes=55):
        return True
    return _warsaw_date_changed(last_fetch, now)


def _needs_day_refetch(last_fetch: datetime | None, now: datetime) -> bool:
    """Daily frames must refresh on the 6h cadence AND after Warsaw midnight,
    so yesterday's day-frame finalizes promptly for the yesterday sensors."""
    if last_fetch is None:
        return True
    if (now - last_fetch) > timedelta(hours=6):
        return True
    return _warsaw_date_changed(last_fetch, now)


def _warsaw_date_changed(last_fetch: datetime, now: datetime) -> bool:
    return last_fetch.astimezone(TZ_WARSAW).date() != now.astimezone(TZ_WARSAW).date()


class PstrykBaseCoordinator(DataUpdateCoordinator[_DataT]):
    async def _fetch(self, coro):
        """Shared error translation."""
        try:
            return await coro
        except PstrykAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PstrykRateLimited as err:
            raise UpdateFailed(str(err)) from err
        except PstrykAPIError as err:
            raise UpdateFailed(str(err)) from err


def _next_refresh_interval(now: datetime) -> timedelta:
    next_boundary = (now + timedelta(hours=1)).replace(
        minute=0, second=15, microsecond=0
    )
    return min(timedelta(minutes=30), max(timedelta(seconds=30), next_boundary - now))


class PricingDataCoordinator(PstrykBaseCoordinator[PricingData]):
    """Hourly price frames: Warsaw yesterday 00:00 -> +3 days.

    Refresh aligns to the next hourly price boundary (+15 s) so the current
    price flips promptly at each hour change, capped at 30 min so tomorrow's
    publication is still picked up quickly.
    """

    def __init__(self, hass: HomeAssistant, client: PstrykApiClient) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_pricing", update_interval=timedelta(minutes=30)
        )
        self._client = client

    def _schedule_next_refresh(self) -> None:
        self.update_interval = _next_refresh_interval(dt_util.utcnow())

    async def _async_update_data(self) -> PricingData:
        try:
            start = _warsaw_midnight(1)
            # Calendar-aware end: 3 Warsaw days after `start` is 73 absolute
            # hours across the October fall-back, so an absolute
            # `start + timedelta(days=3)` would clip tomorrow's final hour.
            end = _warsaw_midnight(-2)
            payload = await self._fetch(self._client.async_pricing_range(start, end))
            return PricingData.from_api(payload)
        finally:
            self._schedule_next_refresh()


class UsageDataCoordinator(PstrykBaseCoordinator[UsageData]):
    """Latest reading every poll; hourly-today and daily-month gated fetches."""

    def __init__(self, hass: HomeAssistant, client: PstrykApiClient, poll_minutes: int) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_usage", update_interval=timedelta(minutes=poll_minutes)
        )
        self._client = client
        self._last_hour_fetch: datetime | None = None
        self._last_day_fetch: datetime | None = None

    async def _async_update_data(self) -> UsageData:
        now = dt_util.utcnow()
        latest = parse_latest(await self._fetch(self._client.async_latest()))

        hour_fetched = False
        if _needs_hour_refetch(self._last_hour_fetch, now):
            hourly_payload = await self._fetch(self._client.async_usage_hourly(_warsaw_midnight(0), now))
            hours_today = parse_hourly(hourly_payload)
            hour_fetched = True
        else:
            hours_today = self.data.hours_today if self.data else ()

        day_fetched = False
        if _needs_day_refetch(self._last_day_fetch, now):
            # Cover the whole month AND yesterday, so cost_yesterday stays
            # available on the 1st when yesterday falls in the previous month.
            month_start = now.astimezone(TZ_WARSAW).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            ).astimezone(dt_util.UTC)
            window_start = min(month_start, _warsaw_midnight(1))
            daily_payload = await self._fetch(self._client.async_usage_daily(window_start, now))
            days_month = parse_daily(daily_payload)
            day_fetched = True
        else:
            days_month = self.data.days_month if self.data else ()

        # Commit gate timestamps only once the whole update succeeded,
        # so a failed sibling fetch cannot suppress the next refetch.
        if hour_fetched:
            self._last_hour_fetch = now
        if day_fetched:
            self._last_day_fetch = now
        return UsageData(hours_today=hours_today, days_month=days_month, latest=latest)
