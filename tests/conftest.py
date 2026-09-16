"""Shared fixtures and helpers for pstryk_energy tests."""
import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from custom_components.pstryk_energy.const import CONF_API_KEY, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://api.pstryk.pl/integrations/meter-data/unified-metrics/"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _mock_api(aioclient_mock) -> None:
    """Dispatch by query: latest=dict-frames, pricing/hourly/daily=list-frames."""

    async def dispatch(method, url, data):
        if url.query.get("metrics") == "pricing":
            body = _fixture("pricing.json")
        elif url.query.get("temporal") == "latest":
            body = _fixture("latest.json")
        elif url.query.get("resolution") == "day":
            body = _fixture("daily.json")
        else:
            body = _fixture("hourly.json")
        return AiohttpClientMockResponse(method=method, url=url, status=200, json=body)

    aioclient_mock.get(BASE, side_effect=dispatch)


async def setup_entry(hass: HomeAssistant, aioclient_mock) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "k"},
                            entry_id="pt1", version=1, minor_version=1)
    entry.add_to_hass(hass)
    _mock_api(aioclient_mock)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
