"""Thin async client for the Pstryk unified-metrics endpoint."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aiohttp

from .const import BASE_URL

_LOGGER = logging.getLogger(__name__)

RETRY_BACKOFF_S = (2, 4, 8)
DEFAULT_RETRY_AFTER = 60.0


class PstrykAPIError(Exception):
    """Base error talking to the Pstryk API."""


class PstrykAuthError(PstrykAPIError):
    """Key invalid, revoked, meter missing or no active contract (401/403/404)."""


class PstrykRateLimited(PstrykAPIError):
    """HTTP 429. `retry_after` in seconds (from Retry-After when present)."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"Rate limited, retry after {retry_after:.0f}s")
        self.retry_after = retry_after


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class PstrykApiClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def async_get(self, params: dict[str, str]) -> dict:
        """GET unified-metrics with retries. Returns parsed JSON dict."""
        last_error: Exception | None = None
        for attempt in range(len(RETRY_BACKOFF_S) + 1):
            if attempt:
                await asyncio.sleep(RETRY_BACKOFF_S[attempt - 1])
            try:
                async with self._session.get(
                    BASE_URL, params=params, headers={"Authorization": self._api_key}
                ) as resp:
                    if resp.status in (200, 201):
                        return await resp.json()
                    if resp.status in (401, 403, 404):
                        raise PstrykAuthError(f"HTTP {resp.status}")
                    if resp.status == 429:
                        retry_after = DEFAULT_RETRY_AFTER
                        if raw := resp.headers.get("Retry-After"):
                            try:
                                retry_after = float(raw)
                            except ValueError:
                                pass
                        raise PstrykRateLimited(retry_after)
                    body = (await resp.text())[:200]
                    if resp.status >= 500:
                        last_error = PstrykAPIError(f"HTTP {resp.status}: {body}")
                        _LOGGER.warning(
                            "Pstryk request failed (attempt %d): HTTP %d",
                            attempt + 1,
                            resp.status,
                        )
                        continue
                    raise PstrykAPIError(f"HTTP {resp.status}: {body}")
            except (PstrykAuthError, PstrykRateLimited):
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last_error = err
                _LOGGER.warning(
                    "Pstryk request failed (attempt %d): %s", attempt + 1, err
                )
        raise PstrykAPIError(f"Request failed after retries: {last_error}")

    async def async_latest(self) -> dict:
        return await self.async_get(
            {
                "metrics": "meter_values,cost,pricing",
                "temporal": "latest",
                "resolution": "hour",
            }
        )

    async def async_pricing_range(self, start_utc: datetime, end_utc: datetime) -> dict:
        return await self.async_get(
            {
                "metrics": "pricing",
                "resolution": "hour",
                "window_start": _iso(start_utc),
                "window_end": _iso(end_utc),
            }
        )

    async def async_usage_hourly(self, start_utc: datetime, end_utc: datetime) -> dict:
        return await self.async_get(
            {
                "metrics": "meter_values,cost",
                "resolution": "hour",
                "window_start": _iso(start_utc),
                "window_end": _iso(end_utc),
            }
        )

    async def async_usage_daily(self, start_utc: datetime, end_utc: datetime) -> dict:
        return await self.async_get(
            {
                "metrics": "meter_values,cost",
                "resolution": "day",
                "for_tz": "Europe/Warsaw",
                "window_start": _iso(start_utc),
                "window_end": _iso(end_utc),
            }
        )
