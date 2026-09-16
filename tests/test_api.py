"""API client tests via aioclient_mock."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.pstryk_energy.api import (
    PstrykApiClient,
    PstrykAuthError,
    PstrykRateLimited,
)
from custom_components.pstryk_energy.const import BASE_URL

START = datetime(2026, 9, 15, 22, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 17, 22, 0, tzinfo=timezone.utc)


def make_client(hass):
    return PstrykApiClient(async_get_clientsession(hass), "secret-key")


async def test_latest_sends_raw_key_header(hass, aioclient_mock):
    client = make_client(hass)
    aioclient_mock.get(BASE_URL, json={"frames": {}})
    result = await client.async_latest()
    assert result == {"frames": {}}
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "secret-key"


async def test_pricing_range_omits_for_tz(hass, aioclient_mock):
    client = make_client(hass)
    aioclient_mock.get(BASE_URL, json={"frames": []})
    await client.async_pricing_range(START, END)
    url = str(aioclient_mock.mock_calls[0][1])
    assert "for_tz" not in url
    assert "metrics=pricing" in url
    assert "resolution=hour" in url


async def test_usage_daily_sends_for_tz(hass, aioclient_mock):
    client = make_client(hass)
    aioclient_mock.get(BASE_URL, json={"frames": []})
    await client.async_usage_daily(START, END)
    url = str(aioclient_mock.mock_calls[0][1])
    assert "for_tz=Europe%2FWarsaw" in url or "for_tz=Europe/Warsaw" in url
    assert "resolution=day" in url


async def test_usage_hourly_omits_for_tz(hass, aioclient_mock):
    client = make_client(hass)
    aioclient_mock.get(BASE_URL, json={"frames": []})
    await client.async_usage_hourly(START, END)
    url = str(aioclient_mock.mock_calls[0][1])
    assert "for_tz" not in url
    assert "resolution=hour" in url


async def test_401_raises_auth_error(hass, aioclient_mock):
    client = make_client(hass)
    aioclient_mock.get(BASE_URL, status=401)
    with pytest.raises(PstrykAuthError):
        await client.async_latest()


async def test_429_raises_rate_limited_with_retry_after(hass, aioclient_mock):
    client = make_client(hass)
    aioclient_mock.get(BASE_URL, status=429, headers={"Retry-After": "120"})
    with pytest.raises(PstrykRateLimited) as exc:
        await client.async_latest()
    assert exc.value.retry_after == 120.0


async def test_5xx_retries_then_succeeds(hass, aioclient_mock):
    client = make_client(hass)
    responses = iter(
        [
            AiohttpClientMockResponse("get", URL(BASE_URL), status=500),
            AiohttpClientMockResponse("get", URL(BASE_URL), status=502),
            AiohttpClientMockResponse("get", URL(BASE_URL), json={"frames": []}),
        ]
    )

    async def next_response(method, url, data):
        return next(responses)

    aioclient_mock.get(BASE_URL, side_effect=next_response)
    with patch("custom_components.pstryk_energy.api.RETRY_BACKOFF_S", (0, 0, 0)):
        result = await client.async_latest()
    assert result == {"frames": []}
    assert len(aioclient_mock.mock_calls) == 3
