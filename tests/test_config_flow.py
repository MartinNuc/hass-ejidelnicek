"""Tests for the config, reauth and options flows."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ejidelnicek.api import (
    CannotConnect,
    InvalidAuth,
    UnsupportedSite,
    ValidationResult,
)
from custom_components.ejidelnicek.const import (
    CONF_BASE_URL,
    CONF_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    MIN_UPDATE_INTERVAL_HOURS,
)
from custom_components.ejidelnicek.parser import extract_payload, parse_canteen
from tests.fixture_loader import load

# Neutral test host -- never a real school hostname.
BASE = "https://school.example.cz/ejidelnicek/"
VALIDATE = "custom_components.ejidelnicek.config_flow.async_validate"


def _result(**kwargs):
    canteen = parse_canteen(extract_payload(load("canteen_two_options.html")))
    defaults = {
        "base_url": BASE,
        "canteen": canteen,
        "diner": None,
        "menu_is_empty": False,
    }
    return ValidationResult(**{**defaults, **kwargs})


async def _submit(hass, user_input):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def test_anonymous_setup_creates_an_entry(hass: HomeAssistant):
    with patch(VALIDATE, return_value=_result()):
        result = await _submit(hass, {CONF_BASE_URL: "school.example.cz"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_BASE_URL: BASE}
    assert result["result"].unique_id == f"{BASE}|public"
    assert result["title"] == "Oběd – school.example.cz"  # noqa: RUF001


async def test_credentials_are_stored_and_change_the_unique_id(hass: HomeAssistant):
    with patch(VALIDATE, return_value=_result()):
        result = await _submit(hass, {CONF_BASE_URL: BASE, CONF_USERNAME: "u", CONF_PASSWORD: "p"})
    assert result["data"][CONF_USERNAME] == "u"
    assert result["data"][CONF_PASSWORD] == "p"
    assert result["result"].unique_id == f"{BASE}|u"


async def test_anonymous_entry_has_no_credential_keys(hass: HomeAssistant):
    with patch(VALIDATE, return_value=_result()):
        result = await _submit(hass, {CONF_BASE_URL: BASE})
    assert CONF_USERNAME not in result["data"]
    assert CONF_PASSWORD not in result["data"]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (CannotConnect, "cannot_connect"),
        (InvalidAuth, "invalid_auth"),
        (UnsupportedSite, "unsupported_site"),
        (Exception, "unknown"),
    ],
)
async def test_errors_are_reported_distinctly(hass: HomeAssistant, error, expected):
    with patch(VALIDATE, side_effect=error):
        result = await _submit(hass, {CONF_BASE_URL: BASE})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_the_same_school_and_user_cannot_be_added_twice(hass: HomeAssistant):
    MockConfigEntry(domain=DOMAIN, unique_id=f"{BASE}|u", data={CONF_BASE_URL: BASE}).add_to_hass(
        hass
    )
    with patch(VALIDATE, return_value=_result()):
        result = await _submit(hass, {CONF_BASE_URL: BASE, CONF_USERNAME: "u", CONF_PASSWORD: "p"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_two_children_at_the_same_school_are_both_allowed(hass: HomeAssistant):
    MockConfigEntry(
        domain=DOMAIN, unique_id=f"{BASE}|child_one", data={CONF_BASE_URL: BASE}
    ).add_to_hass(hass)
    with patch(VALIDATE, return_value=_result()):
        result = await _submit(
            hass, {CONF_BASE_URL: BASE, CONF_USERNAME: "child_two", CONF_PASSWORD: "p"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_empty_public_menu_still_creates_an_entry(hass: HomeAssistant, caplog):
    with patch(VALIDATE, return_value=_result(menu_is_empty=True)):
        result = await _submit(hass, {CONF_BASE_URL: BASE})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "probably required" in caplog.text


async def test_reauth_updates_the_password(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{BASE}|u",
        data={CONF_BASE_URL: BASE, CONF_USERNAME: "u", CONF_PASSWORD: "old"},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    with patch(VALIDATE, return_value=_result()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"


async def test_reauth_reports_invalid_auth(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{BASE}|u",
        data={CONF_BASE_URL: BASE, CONF_USERNAME: "u", CONF_PASSWORD: "old"},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    with patch(VALIDATE, side_effect=InvalidAuth):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "still-wrong"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_PASSWORD] == "old"


async def test_options_flow_updates_the_interval(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{BASE}|public", data={CONF_BASE_URL: BASE})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_UPDATE_INTERVAL_HOURS: 12}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_UPDATE_INTERVAL_HOURS] == 12


async def test_options_flow_rejects_values_below_the_minimum(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{BASE}|public", data={CONF_BASE_URL: BASE})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_UPDATE_INTERVAL_HOURS: MIN_UPDATE_INTERVAL_HOURS - 1}
        )
