"""Tests for config entry setup/unload and coordinator error mapping.

``calendar.py`` does not exist yet (Task 12). Config entry setup is limited
to the platforms that genuinely exist on disk by the shared
``_only_forward_to_existing_platforms`` autouse fixture in
``tests/conftest.py`` -- see its docstring for why, and what Task 12 needs to
do to it.

``sensor.py`` (Task 10) and ``binary_sensor.py`` (Task 11) are real and
genuinely exercised here:
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

from aioresponses import aioresponses
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ejidelnicek.const import CONF_BASE_URL, CONF_UPDATE_INTERVAL_HOURS, DOMAIN
from tests.fixture_loader import load

# Neutral test host -- never a real school hostname.
BASE = "https://school.example.cz/ejidelnicek/"
MENU = BASE + "menu/"
AJAX_RE = re.compile(r".*get-jidelnicek.*")


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
