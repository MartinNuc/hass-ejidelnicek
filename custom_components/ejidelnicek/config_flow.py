"""Config, reauth and options flows for the E-jídelníček integration.

The user step accepts a base URL/host and optional credentials, validates
them against the real site via :func:`custom_components.ejidelnicek.api.
async_validate`, and creates one config entry per (school, diner) pair -- the
unique ID deliberately includes the username so two children at the same
school are two legitimate entries, not a duplicate. Reauth re-validates a new
password (and, implicitly, the stored username) for an existing entry. The
options flow exposes the single update-interval setting.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import CannotConnect, InvalidAuth, UnsupportedSite, async_validate
from .const import (
    CONF_BASE_URL,
    CONF_UPDATE_INTERVAL_HOURS,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    MIN_UPDATE_INTERVAL_HOURS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL): str,
        vol.Optional(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class EjidelnicekConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for E-jídelníček."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step: base URL plus optional credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input.get(CONF_USERNAME) or None
            password = user_input.get(CONF_PASSWORD) or None
            try:
                result = await async_validate(
                    async_get_clientsession(self.hass),
                    user_input[CONF_BASE_URL],
                    username,
                    password,
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except UnsupportedSite:
                errors["base"] = "unsupported_site"
            except Exception:
                _LOGGER.exception("Unexpected error validating the E-jídelníček configuration")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"{result.base_url}|{username or 'public'}")
                self._abort_if_unique_id_configured()

                host = urlparse(result.base_url).hostname or result.base_url
                if result.canteen.meal_types:
                    title = f"{result.canteen.meal_types[0].name} – {host}"  # noqa: RUF001
                else:
                    title = host

                data: dict[str, Any] = {CONF_BASE_URL: result.base_url}
                if username and password:
                    data[CONF_USERNAME] = username
                    data[CONF_PASSWORD] = password

                if result.menu_is_empty and not username:
                    # Some canteens (typically kindergartens) publish nothing
                    # on the public menu at all -- the entry is still created
                    # (it may start showing data once credentials are added
                    # via reconfigure), but this is worth flagging loudly
                    # since otherwise it looks like the integration is broken.
                    _LOGGER.warning(
                        "The public menu at %s appears to be empty; a username "
                        "and password are probably required to see any menu data",
                        host,
                    )

                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Handle reauth triggered by rejected credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password and re-validate it."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            username = reauth_entry.data.get(CONF_USERNAME)
            password = user_input[CONF_PASSWORD]
            try:
                await async_validate(
                    async_get_clientsession(self.hass),
                    reauth_entry.data[CONF_BASE_URL],
                    username,
                    password,
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except UnsupportedSite:
                errors["base"] = "unsupported_site"
            except Exception:
                _LOGGER.exception("Unexpected error validating reauth credentials")
                errors["base"] = "unknown"
            else:
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: password},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EjidelnicekOptionsFlow:
        """Return the options flow for this handler."""
        return EjidelnicekOptionsFlow()


class EjidelnicekOptionsFlow(OptionsFlow):
    """Handle the options flow: the poll interval, in hours."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the update-interval option."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL_HOURS, default=current): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_UPDATE_INTERVAL_HOURS,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
