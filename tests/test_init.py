"""Tests for config entry setup/unload and coordinator error mapping.

One piece of this integration does not exist yet and is explicitly out of
scope for Task 8:

* ``binary_sensor.py``/``calendar.py``/``sensor.py`` (Tasks 10-12) -- but
  ``const.PLATFORMS`` already lists all three, and ``async_setup_entry``
  correctly forwards to them.

It is stood in for using ``pytest_homeassistant_custom_component``'s own
``mock_platform`` test helper -- the sanctioned way to tell Home Assistant's
loader "this platform exists but is out of scope for this test" without
touching the real, already reviewed ``__init__``/``api``/``coordinator``
modules, which load and run for real, or the real ``manifest.json``/
``const.PLATFORMS``, which stay production-accurate. Tasks 10-12 replace this
stand-in with the genuine modules.

The config flow itself (Task 9) is real here: ``config_flow.py`` exists and
is registered normally, so the reauth-flow assertion below exercises the
actual ``EjidelnicekConfigFlow``, not a stand-in.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from aioresponses import aioresponses
from homeassistant import loader
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockPlatform,
    mock_platform,
)

from custom_components.ejidelnicek.const import (
    CONF_BASE_URL,
    CONF_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    PLATFORMS,
)
from tests.fixture_loader import load

# Neutral test host -- never a real school hostname.
BASE = "https://school.example.cz/ejidelnicek/"
MENU = BASE + "menu/"
AJAX_RE = re.compile(r".*get-jidelnicek.*")


@pytest.fixture(autouse=True)
async def _stub_entity_platforms_from_later_tasks(hass: HomeAssistant):
    """Stand in for the entity platforms Tasks 10-12 add.

    Resolves the real integration first so ``mock_platform`` augments it in
    place (adding each missing file to its known platform list and seeding
    the loader's module cache) instead of replacing it with a fully mocked
    integration, which would also shadow the real ``__init__.py``.
    """
    await loader.async_get_integration(hass, DOMAIN)
    for platform in PLATFORMS:
        mock_platform(hass, f"{DOMAIN}.{platform}", MockPlatform())


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
