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

# A distinctive sentinel -- not "u" or anything that could collide with
# ordinary text elsewhere in the payload (unlike a real username, this must
# never appear ANYWHERE in the serialised diagnostics, unique_id included).
SENTINEL_USERNAME = "zzz_sentinel_diner_username_zzz"

# No freezer here: the diagnostics content asserted below (redaction, meal
# type names, day counts, the static date range) does not depend on "today",
# and freezing time after `hass_client`'s access token is minted (during
# fixture setup, at the real wall-clock time) would move the clock far
# enough past the token's 30-minute lifetime to make the API call 401.


async def _setup_with_credentials(hass: HomeAssistant) -> MockConfigEntry:
    """Set up a credentialed config entry against the authenticated fixture."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_BASE_URL: BASE,
            CONF_USERNAME: SENTINEL_USERNAME,
            CONF_PASSWORD: "sup3rsecret",
        },
        unique_id=f"{BASE}|{SENTINEL_USERNAME}",
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
    """Neither the password nor the username may leak, anywhere in the payload.

    This is the invariant a prior version of this test got wrong: it's not
    enough for ``entry.data.username``/``entry.data.password`` to come back
    redacted -- ``entry.unique_id`` is built by ``config_flow.py`` as
    ``f"{base_url}|{username}"``, so a diagnostics implementation that dumps
    the whole config entry (even through ``async_redact_data``, which
    matches by *key*, not by scanning string values) would still leak the
    username in cleartext there. ``diagnostics.py`` avoids this by never
    including ``unique_id`` (or ``entry_id``) at all -- so this test checks
    the full serialised blob, not just the ``data`` sub-dict.
    """
    entry = await _setup_with_credentials(hass)
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert data["entry"]["data"]["password"] == "**REDACTED**"
    assert data["entry"]["data"]["username"] == "**REDACTED**"
    serialised = json.dumps(data, default=str)
    assert "sup3rsecret" not in serialised
    assert SENTINEL_USERNAME not in serialised


async def test_diagnostics_entry_omits_unique_id_and_entry_id(hass: HomeAssistant, hass_client):
    """The entry dict is a curated allowlist, not an ``entry.as_dict()`` dump.

    ``unique_id`` and ``entry_id`` are the two identifiers that would let a
    diagnostics dump be linked back to a specific diner/entry; neither earns
    its place for debugging, so both are left out entirely rather than
    redacted-in-place.
    """
    entry = await _setup_with_credentials(hass)
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert set(data["entry"]) == {"title", "version", "source", "options", "data"}


async def test_diagnostics_never_leak_the_diners_balance(hass: HomeAssistant, hass_client):
    """The real balance figure must not appear anywhere in the output."""
    entry = await _setup_with_credentials(hass)
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert data["diner"]["present"] is True
    assert data["diner"]["balance"] == "**REDACTED**"
    assert data["diner"]["balance_meals"] == "**REDACTED**"
    assert data["diner"]["balance_tuition"] == "**REDACTED**"
    # The real balance in ajax_authenticated.json is 297,00 CZK. Scoped to the
    # diner sub-dict on purpose: asserting over the whole document would also
    # trip on an unrelated dbId or day count that happened to contain "297",
    # which is a false failure, not a leak.
    assert "297" not in json.dumps(data["diner"], default=str)


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
