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
from homeassistant.helpers import issue_registry as ir
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


def _map_error(err: Exception) -> str:
    """Map a validation exception to a translation error key.

    Shared between ``async_step_user`` and ``async_step_reauth_confirm`` so
    the two never drift out of lockstep. Anything that is not one of this
    integration's own known error types is logged here (without credentials
    -- only the exception itself, never the values that produced it) and
    reported as ``unknown``.
    """
    if isinstance(err, CannotConnect):
        return "cannot_connect"
    if isinstance(err, InvalidAuth):
        return "invalid_auth"
    if isinstance(err, UnsupportedSite):
        return "unsupported_site"
    _LOGGER.exception("Unexpected error validating the E-jídelníček configuration")
    return "unknown"


class EjidelnicekConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for E-jídelníček."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step: base URL plus optional credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input.get(CONF_USERNAME) or None
            password = user_input.get(CONF_PASSWORD) or None

            if bool(username) != bool(password):
                # Exactly one of the two was given. Storing that would create
                # an entry that behaves as anonymous under a user-specific
                # unique_id, silently discarding the typed username -- reject
                # it instead of guessing what the user meant.
                errors["base"] = "incomplete_credentials"
            else:
                try:
                    result = await async_validate(
                        async_get_clientsession(self.hass),
                        user_input[CONF_BASE_URL],
                        username,
                        password,
                    )
                except Exception as err:  # classified by _map_error
                    errors["base"] = _map_error(err)
                else:
                    # `username` is truthy here iff both credentials were
                    # given (the mismatch case above already returned) --
                    # the same single condition drives the unique_id, the
                    # stored credentials and the empty-menu check below, so
                    # they cannot diverge from one another.
                    await self.async_set_unique_id(f"{result.base_url}|{username or 'public'}")
                    self._abort_if_unique_id_configured()

                    # The title is the host alone, never a meal type: one
                    # entry's device can carry several meal types (a
                    # kindergarten typically has breakfast, lunch and snack
                    # all under one login), so the device must identify the
                    # canteen, not any single meal. Per-meal-type entities
                    # instead carry their meal type in their own name -- see
                    # ``_attr_translation_placeholders`` in sensor.py and
                    # calendar.py.
                    host = urlparse(result.base_url).hostname or result.base_url
                    title = host

                    data: dict[str, Any] = {CONF_BASE_URL: result.base_url}
                    if username:
                        data[CONF_USERNAME] = username
                        data[CONF_PASSWORD] = password

                    if result.menu_is_empty and not username:
                        # Some canteens (typically kindergartens) publish
                        # nothing on the public menu at all -- the entry is
                        # still created (it may start showing data once
                        # credentials are added), but a log line alone is
                        # invisible to someone completing the wizard, so
                        # raise a persistent Repairs issue instead.
                        ir.async_create_issue(
                            self.hass,
                            DOMAIN,
                            f"empty_public_menu_{self.unique_id}",
                            is_fixable=False,
                            severity=ir.IssueSeverity.WARNING,
                            translation_key="empty_public_menu",
                            translation_placeholders={"host": host},
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
            except Exception as err:  # classified by _map_error
                errors["base"] = _map_error(err)
            else:
                # Defence-in-depth, not currently reachable: this step never
                # recomputes a unique_id from the validated result -- it
                # always reuses the stored username -- so self.unique_id can
                # never diverge from reauth_entry.unique_id today. The guard
                # only becomes live if this step ever grows a username field
                # that lets a submission repoint the entry at a different
                # account; reauth must never silently allow that (that is
                # reconfigure's job), so the call stays.
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
