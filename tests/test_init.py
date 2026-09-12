"""Tests for config entry setup/unload and coordinator error mapping.

``sensor.py`` (Task 10), ``binary_sensor.py`` (Task 11) and ``calendar.py``
(Task 12) are all real and forwarded to for real by
``hass.config_entries.async_setup``/``async_unload`` (``const.PLATFORMS``):
``test_setup_and_unload`` forwards to the real platforms and exercises real
entity setup/teardown as a side effect of config entry setup/unload.
Dedicated, detailed sensor behaviour (state values, attributes, midnight
rollover) lives in ``tests/test_sensor.py``; calendar behaviour lives in
``tests/test_calendar.py``.

The config flow itself (Task 9) is real here: ``config_flow.py`` exists and
is registered normally, so the reauth-flow assertion below exercises the
actual ``EjidelnicekConfigFlow``, not a stand-in.
"""

from __future__ import annotations

import re
from datetime import timedelta

import aiohttp
from aioresponses import aioresponses
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yarl import URL

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


async def test_each_entry_gets_its_own_session_with_its_own_cookie_jar(
    hass: HomeAssistant,
) -> None:
    """Two entries against one school must never share a cookie jar.

    ``api.py`` keeps its ``JSESSIONID`` in the aiohttp session's cookie jar,
    and Home Assistant's shared ``async_get_clientsession`` session has a
    single instance-wide jar. Sharing it would mean whichever entry logged in
    last owns the session cookie, so the other entry would see a *valid*
    session for the wrong diner and silently report its sibling's orders,
    balance and debt as its own -- exactly the "two children at one school"
    setup ``config_flow.py`` advertises as supported.
    """
    entries = []
    for user in ("child_one", "child_two"):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_BASE_URL: BASE},
            unique_id=f"{BASE}|{user}",
        )
        entry.add_to_hass(hass)
        entries.append(entry)

    with aioresponses() as mocked:
        mocked.get(MENU, status=200, body=load("canteen_two_options.html"), repeat=True)
        # Setting up the first entry sets up the component, which loads every
        # other not-yet-loaded entry of this domain with it.
        assert await hass.config_entries.async_setup(entries[0].entry_id)
        await hass.async_block_till_done()
    assert all(entry.state is ConfigEntryState.LOADED for entry in entries)

    first, second = (entry.runtime_data.client._session for entry in entries)
    shared = async_get_clientsession(hass)

    assert first is not second
    assert first is not shared
    assert second is not shared
    assert first.cookie_jar is not second.cookie_jar
    assert first.cookie_jar is not shared.cookie_jar
    # And each entry's jar is configured to keep cookies from IP-address
    # hosts -- see ``test_the_cookie_jar_we_configure_keeps_an_ip_hosts_cookie``.
    assert first.cookie_jar._unsafe is True
    assert second.cookie_jar._unsafe is True


async def test_the_cookie_jar_we_configure_keeps_an_ip_hosts_cookie() -> None:
    """An IP-host deployment must still be able to hold a session cookie.

    ``aiohttp.CookieJar.update_cookies`` returns early when the jar is not
    ``unsafe`` and the response host is a bare IP address, silently dropping
    the cookie. Several E-jídelníček deployments are reachable only by a LAN
    IP, and a credentialed entry there would loop login -> cookie dropped ->
    "session expired" -> re-login -> ``InvalidAuth``, opening a reauth dialog
    that not even the correct password could satisfy. The second half of this
    test pins down that the default jar really does behave that way, so this
    is a regression test for the cause, not just for the fix.
    """
    url = URL("http://192.168.10.233/ejidelnicek/")

    ours = aiohttp.CookieJar(unsafe=True)
    ours.update_cookies({"JSESSIONID": "kept"}, url)
    assert ours.filter_cookies(url)["JSESSIONID"].value == "kept"

    default = aiohttp.CookieJar()
    default.update_cookies({"JSESSIONID": "dropped"}, url)
    assert "JSESSIONID" not in default.filter_cookies(url)
