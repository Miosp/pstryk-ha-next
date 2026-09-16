"""Config flow for Pstryk Energy."""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Mapping

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    PstrykAPIError,
    PstrykApiClient,
    PstrykAuthError,
    PstrykRateLimited,
)
from .const import (
    CONF_API_KEY,
    CONF_POLL_MINUTES,
    CONF_PRICE_BASIS,
    CONF_WINDOW_HOURS,
    DEFAULT_POLL_MINUTES,
    DEFAULT_PRICE_BASIS,
    DEFAULT_WINDOW_HOURS,
    DOMAIN,
    PRICE_BASIS_GROSS,
    PRICE_BASIS_NET,
)

_LOGGER = logging.getLogger(__name__)


class PstrykConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Pstryk Energy config flow."""

    VERSION = 1

    async def _async_validate_key(self, api_key: str) -> str | None:
        """Return an error key, or None when the key is valid."""
        try:
            client = PstrykApiClient(async_get_clientsession(self.hass), api_key)
            await client.async_latest()
        except PstrykAuthError:
            return "invalid_auth"
        except PstrykRateLimited:
            return "rate_limited"
        except PstrykAPIError:
            return "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Pstryk API key")
            return "unknown"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle API key entry with live validation."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := await self._async_validate_key(user_input[CONF_API_KEY]):
                errors["base"] = error
            else:
                # Hash the key: the unique_id must never carry key material.
                await self.async_set_unique_id(
                    hashlib.sha256(user_input[CONF_API_KEY].encode()).hexdigest()
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Pstryk Energy", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Start reauth after ConfigEntryAuthFailed from a coordinator."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for a fresh API key and validate it live."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := await self._async_validate_key(user_input[CONF_API_KEY]):
                errors["base"] = error
            else:
                entry = self._get_reauth_entry()
                # Re-derive unique_id from the NEW key: a key configured on
                # another entry must abort here (the framework excludes the
                # entry being reauthenticated).
                new_unique_id = hashlib.sha256(
                    user_input[CONF_API_KEY].encode()
                ).hexdigest()
                await self.async_set_unique_id(new_unique_id)
                self._abort_if_unique_id_configured()
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_API_KEY: user_input[CONF_API_KEY]},
                    unique_id=new_unique_id,
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> PstrykOptionsFlowHandler:
        """Create the options flow."""
        return PstrykOptionsFlowHandler()


class PstrykOptionsFlowHandler(config_entries.OptionsFlow):
    """Options: window hours, price basis, usage poll interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_WINDOW_HOURS,
                        default=self.config_entry.options.get(
                            CONF_WINDOW_HOURS, DEFAULT_WINDOW_HOURS
                        ),
                    ): vol.All(int, vol.Range(min=1, max=8)),
                    vol.Required(
                        CONF_PRICE_BASIS,
                        default=self.config_entry.options.get(
                            CONF_PRICE_BASIS, DEFAULT_PRICE_BASIS
                        ),
                    ): vol.In({PRICE_BASIS_GROSS: "Gross", PRICE_BASIS_NET: "Net"}),
                    vol.Required(
                        CONF_POLL_MINUTES,
                        default=self.config_entry.options.get(
                            CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES
                        ),
                    ): vol.All(int, vol.Range(min=5, max=30)),
                }
            ),
        )
