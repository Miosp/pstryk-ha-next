"""Config and options flow tests."""
import hashlib

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from custom_components.pstryk_energy.const import (
    BASE_URL,
    CONF_API_KEY,
    CONF_POLL_MINUTES,
    CONF_PRICE_BASIS,
    CONF_WINDOW_HOURS,
    DOMAIN,
)

USER_INPUT = {CONF_API_KEY: "test-key-123"}


def mock_latest_ok(aioclient_mock):
    """Serve latest-shaped body for latest calls, empty range body otherwise."""

    async def dispatch(method, url, data):
        if url.query.get("temporal") != "latest":
            body = {"frames": []}
        else:
            body = {
                "frames": {
                    "meter_values": {"as_of": "2026-09-16T11:14:00Z"},
                    "cost": {"as_of": "2026-09-16T11:00:00Z"},
                    "pricing": {"as_of": "2026-09-16T11:00:00Z"},
                }
            }
        return AiohttpClientMockResponse(method=method, url=url, status=200, json=body)

    aioclient_mock.get(BASE_URL, side_effect=dispatch)


async def test_form_creates_entry(hass: HomeAssistant, aioclient_mock):
    mock_latest_ok(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Pstryk Energy"
    assert result["data"][CONF_API_KEY] == "test-key-123"
    await hass.async_block_till_done()
    stored = hass.config_entries.async_entries(DOMAIN)[0]
    assert stored.state is config_entries.ConfigEntryState.LOADED
    # unique_id is a SHA-256 of the key, never the raw key
    assert stored.unique_id == hashlib.sha256(b"test-key-123").hexdigest()
    assert hass.data[DOMAIN][result["result"].entry_id]["client"] is not None


async def test_invalid_key_shows_error(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(BASE_URL, status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_updates_key_and_reloads(hass: HomeAssistant, aioclient_mock):
    mock_latest_ok(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "old-key"},
        entry_id="reauth-entry",
        unique_id=hashlib.sha256(b"old-key").hexdigest(),
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED

    entry.async_start_reauth(hass)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    result = flows[0]
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key"
    assert entry.state is config_entries.ConfigEntryState.LOADED


async def test_reauth_invalid_key_shows_error(hass: HomeAssistant, aioclient_mock):
    mock_latest_ok(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "old-key"},
        entry_id="reauth-entry-bad",
        unique_id=hashlib.sha256(b"old-key").hexdigest(),
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entry.async_start_reauth(hass)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    result = flows[0]
    aioclient_mock.clear_requests()
    aioclient_mock.get(BASE_URL, status=401)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "still-bad"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_API_KEY] == "old-key"


async def test_options_flow_roundtrip(hass: HomeAssistant, aioclient_mock):
    mock_latest_ok(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT,
        options={},
        entry_id="test-entry",
        unique_id=hashlib.sha256(b"test-key-123").hexdigest(),
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is config_entries.ConfigEntryState.LOADED

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_WINDOW_HOURS: 4, CONF_PRICE_BASIS: "net", CONF_POLL_MINUTES: 15},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_WINDOW_HOURS] == 4
    assert entry.options[CONF_PRICE_BASIS] == "net"
    assert entry.options[CONF_POLL_MINUTES] == 15
    # options change reloads the entry
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
