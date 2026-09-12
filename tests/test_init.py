"""Tests for config entry setup/unload and coordinator error mapping.

Two platforms do not exist yet: ``binary_sensor.py`` and ``calendar.py``
(Tasks 11-12). ``const.PLATFORMS`` already lists all three -- that constant
stays production-accurate -- but forwarding to a platform module that is not
on disk raises ``ModuleNotFoundError``, so the tests below patch
``custom_components.ejidelnicek.PLATFORMS`` down to the platforms that
genuinely exist yet. Task 11 adds ``Platform.BINARY_SENSOR`` to
``_EXISTING_PLATFORMS``, Task 12 adds ``Platform.CALENDAR``, and once the
list matches ``const.PLATFORMS`` the patch is deleted entirely.

``sensor.py`` (Task 10) is real and genuinely exercised here:
``test_setup_and_unload`` forwards to the real platform and exercises real
sensor entity setup/teardown as a side effect of config entry setup/unload.
Dedicated, detailed sensor behaviour (state values, attributes, midnight
rollover) lives in ``tests/test_sensor.py``.

The config flow itself (Task 9) is real here: ``config_flow.py`` exists and
is registered normally, so the reauth-flow assertion below exercises the
actual ``EjidelnicekConfigFlow``, not a stand-in.
"""

from __future__ import annotations

import re
from datetime import timedelta
from unittest.mock import patch

import pytest
from aioresponses import aioresponses
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ejidelnicek.const import CONF_BASE_URL, CONF_UPDATE_INTERVAL_HOURS, DOMAIN
from tests.fixture_loader import load

# Neutral test host -- never a real school hostname.
BASE = "https://school.example.cz/ejidelnicek/"
MENU = BASE + "menu/"
AJAX_RE = re.compile(r".*get-jidelnicek.*")

# See the module docstring: widen this as Tasks 11-12 add the remaining
# platforms, then delete the patch once it matches const.PLATFORMS.
_EXISTING_PLATFORMS = [Platform.SENSOR]


@pytest.fixture(autouse=True)
def _only_forward_to_existing_platforms():
    """Limit config entry setup to platforms that actually exist on disk."""
    with patch("custom_components.ejidelnicek.PLATFORMS", _EXISTING_PLATFORMS):
        yield


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    """A reachable anonymous canteen loads and unloads cleanly."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_BASE_URL: BASE}, unique_id=f"{BASE}|public")
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(MENU, status=200, body=load("canteen_two_options.html"), repeat=True)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_the_canteen_is_unreachable(hass: HomeAssistant) -> None:
    """An unreachable canteen yields SETUP_RETRY, not a hard failure."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_BASE_URL: BASE}, unique_id=f"{BASE}|public")
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(MENU, status=500, repeat=True)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_starts_reauth_when_credentials_are_rejected(hass: HomeAssistant) -> None:
    """Rejected credentials must trigger reauth, not an endless retry loop."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: BASE, CONF_USERNAME: "u", CONF_PASSWORD: "p"},
        unique_id=f"{BASE}|u",
    )
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(MENU, status=200, body=load("canteen_two_options.html"), repeat=True)
        # The authenticated day fetch looks like an expired session, which
        # triggers a re-login -- and the site keeps returning the login form:
        # the credentials are rejected.
        mocked.get(AJAX_RE, status=302, repeat=True)
        mocked.get(BASE, status=200, body="<form id='loginForm'></form>", repeat=True)
        mocked.post(
            BASE + "logincheck",
            status=200,
            body="<form id='loginForm'>bad</form>",
            repeat=True,
        )
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"].get("source") == "reauth" for flow in flows)


async def test_update_interval_is_clamped_to_the_minimum(hass: HomeAssistant) -> None:
    """A stored option below the minimum must be clamped up, not down."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: BASE},
        options={CONF_UPDATE_INTERVAL_HOURS: 0},
        unique_id=f"{BASE}|public",
    )
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(MENU, status=200, body=load("canteen_two_options.html"), repeat=True)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.update_interval == timedelta(hours=1)
