"""Diagnostics redaction test."""
from custom_components.pstryk_energy.const import CONF_API_KEY
from custom_components.pstryk_energy.diagnostics import async_get_config_entry_diagnostics

from tests.conftest import setup_entry


async def test_diagnostics_redacts_key(hass, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["config"]["data"][CONF_API_KEY] == "**REDACTED**"
    assert "pricing" in diag
    assert "coordinators" in diag
    assert diag["coordinators"]["pricing"]["last_update_success"] is True
    assert diag["coordinators"]["usage"]["last_update_success"] is True
    assert diag["coordinators"]["pricing"]["last_exception"] is None
    assert "options" in diag
    for frame in diag["pricing"]["frames"]:
        assert isinstance(frame["start"], str) and frame["start"].endswith("+00:00")
