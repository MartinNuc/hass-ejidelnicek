"""Tests for config entry diagnostics: credential and balance redaction.

Uses the real ``ajax_authenticated.json`` fixture, whose diner balance is the
Czech-comma ``"297,00"`` (parsed to the Decimal ``297.00``) -- the tests
assert that number never reaches the serialised diagnostics output.
"""

from __future__ import annotations

import json
import re

from aioresponses import aioresponses
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.ejidelnicek.const import CONF_BASE_URL, DOMAIN
from tests.fixture_loader import load

# Neutral test host -- never a real school hostname.
BASE = "https://school.example.cz/ejidelnicek/"
MENU = BASE + "menu/"
AJAX_RE = re.compile(r".*get-jidelnicek.*")

_LOGIN_FORM = "<form id='loginForm'></form>"
_LOGIN_OK = "ejidelnicek.setJidelnicek({})"

# No freezer here: the diagnostics content asserted below (redaction, meal
# type names, day counts, the static date range) does not depend on "today",
# and freezing time after `hass_client`'s access token is minted (during
# fixture setup, at the real wall-clock time) would move the clock far
# enough past the token's 30-minute lifetime to make the API call 401.


async def _setup_with_credentials(hass: HomeAssistant) -> MockConfigEntry:
    """Set up a credentialed config entry against the authenticated fixture."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: BASE, CONF_USERNAME: "diner_u", CONF_PASSWORD: "sup3rsecret"},
        unique_id=f"{BASE}|diner_u",
        title="school.example.cz",
    )
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(BASE, status=200, body=_LOGIN_FORM, repeat=True)
        mocked.post(BASE + "logincheck", status=200, body=_LOGIN_OK, repeat=True)
        mocked.get(MENU, status=200, body=load("canteen_two_options.html"), repeat=True)
        mocked.get(AJAX_RE, status=200, body=load("ajax_authenticated.json"), repeat=True)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _setup_anonymous(hass: HomeAssistant) -> MockConfigEntry:
    """Set up an anonymous config entry against the public two-option fixture."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: BASE},
        unique_id=f"{BASE}|public",
        title="school.example.cz",
    )
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(MENU, status=200, body=load("canteen_two_options.html"), repeat=True)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_diagnostics_redact_credentials(hass: HomeAssistant, hass_client):
    """A diagnostics download must never leak the canteen password.

    The username also comes back redacted from ``entry.data`` -- but it is
    not scrubbed from ``entry.unique_id`` (which structurally embeds it, by
    the Task 9 config-flow design, to tell two diners at the same school
    apart); that is a pre-existing, reviewed choice this test does not
    relitigate. The password never appears anywhere, unique_id included.
    """
    entry = await _setup_with_credentials(hass)
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert data["entry"]["data"]["password"] == "**REDACTED**"
    assert data["entry"]["data"]["username"] == "**REDACTED**"
    serialised = json.dumps(data, default=str)
    assert "sup3rsecret" not in serialised


async def test_diagnostics_never_leak_the_diners_balance(hass: HomeAssistant, hass_client):
    """The real balance figure must not appear anywhere in the output."""
    entry = await _setup_with_credentials(hass)
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert data["diner"]["present"] is True
    assert data["diner"]["balance"] == "**REDACTED**"
    assert data["diner"]["balance_meals"] == "**REDACTED**"
    assert data["diner"]["balance_tuition"] == "**REDACTED**"
    # The real balance in ajax_authenticated.json is 297,00 CZK.
    serialised = json.dumps(data, default=str)
    assert "297" not in serialised


async def test_diagnostics_never_include_diner_identity_fields(hass: HomeAssistant, hass_client):
    """No name, account number, payment symbol or email may appear anywhere."""
    entry = await _setup_with_credentials(hass)
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert set(data["diner"]) == {
        "present",
        "balance",
        "balance_meals",
        "balance_tuition",
        "in_debt",
        "ordering_disabled",
    }


async def test_diagnostics_include_non_sensitive_context(hass: HomeAssistant, hass_client):
    """Base URL, credential presence, interval, meal types and counts are useful."""
    entry = await _setup_anonymous(hass)
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert data["base_url"] == BASE
    assert data["has_credentials"] is False
    assert data["update_interval_hours"] == 6
    assert data["canteen"]["meal_types"] == [{"name": "Oběd", "day_count": 10}]
    assert data["canteen"]["date_range"] == {"first": "2026-09-14", "last": "2026-09-25"}
    assert data["diner"] == {"present": False}


async def test_diagnostics_report_has_credentials_true_when_credentialed(
    hass: HomeAssistant, hass_client
):
    entry = await _setup_with_credentials(hass)
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert data["has_credentials"] is True
