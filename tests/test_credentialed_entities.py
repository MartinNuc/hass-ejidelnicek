"""Tests for the credential-only entities: ordered, balance and debt.

All time control uses the ``freezer`` fixture (freezegun, via
``pytest_freezer``), never ``patch("homeassistant.util.dt.now")`` -- same
reasoning as ``tests/test_sensor.py``. Frozen to 2026-09-14, the one day the
``ajax_authenticated.json`` fixture covers.
"""

from __future__ import annotations

import datetime
import json
import re

from aioresponses import aioresponses
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ejidelnicek.const import CONF_BASE_URL, DOMAIN
from tests.fixture_loader import load

# Neutral test host -- never a real school hostname.
BASE = "https://school.example.cz/ejidelnicek/"
MENU = BASE + "menu/"
AJAX_RE = re.compile(r".*get-jidelnicek.*")

# The authenticated fixture covers exactly this one day.
MONDAY = datetime.datetime(2026, 9, 14, 12, 0, tzinfo=datetime.UTC)

BALANCE_ID = "sensor.obed_school_example_cz_balance"
DEBT_ID = "binary_sensor.obed_school_example_cz_debt"
ORDERED_ID = "sensor.obed_school_example_cz_obed_ordered_next_serving_day"

_LOGIN_FORM = "<form id='loginForm'></form>"
_LOGIN_OK = "ejidelnicek.setJidelnicek({})"


def _ajax_body_with_nothing_ordered() -> str:
    """Return the authenticated fixture with option "1" un-ordered.

    Constructs the "nothing ordered" case from the real fixture (rather than
    hand-writing a second one) by flipping the one ``objednavka: 1`` to 0, so
    every other field -- including ``dbId``, ``zbyva`` and ``stravnik`` --
    still comes from the same authoritative payload.
    """
    payload = json.loads(load("ajax_authenticated.json"))
    day = payload["jidelnicek"]["stravaMap"]["0"]["denMap"]["2026-09-14"]
    day["menuMap"]["1"]["objednavka"] = 0
    return json.dumps(payload)


async def _setup(hass: HomeAssistant, *, ajax_body: str | None = None) -> MockConfigEntry:
    """Set up a credentialed config entry against the two-option fixture."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: BASE, CONF_USERNAME: "u", CONF_PASSWORD: "p"},
        unique_id=f"{BASE}|u",
        title="Oběd – school.example.cz",  # noqa: RUF001
    )
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(BASE, status=200, body=_LOGIN_FORM, repeat=True)
        mocked.post(BASE + "logincheck", status=200, body=_LOGIN_OK, repeat=True)
        mocked.get(MENU, status=200, body=load("canteen_two_options.html"), repeat=True)
        mocked.get(
            AJAX_RE,
            status=200,
            body=ajax_body if ajax_body is not None else load("ajax_authenticated.json"),
            repeat=True,
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_balance_sensor_reports_the_diners_balance(hass: HomeAssistant, freezer):
    """konto "297,00" (Czech comma) must parse to the Decimal 297.00."""
    freezer.move_to(MONDAY)
    await _setup(hass)
    assert hass.states.get(BALANCE_ID).state == "297.00"


async def test_debt_binary_sensor_is_off_when_not_in_debt(hass: HomeAssistant, freezer):
    """dluh is false in the fixture."""
    freezer.move_to(MONDAY)
    await _setup(hass)
    assert hass.states.get(DEBT_ID).state == "off"


async def test_ordered_sensor_reports_the_booked_options_label(hass: HomeAssistant, freezer):
    """Option "1" is ordered (objednavka: 1) -- its label is the state."""
    freezer.move_to(MONDAY)
    await _setup(hass)
    state = hass.states.get(ORDERED_ID)
    assert state.state == "1"
    assert state.attributes["options_count"] == 2
    assert state.attributes["date"] == "2026-09-14"


async def test_ordered_sensor_reports_none_when_nothing_is_ordered(hass: HomeAssistant, freezer):
    """No option ordered -> the literal string "none", not unknown/None."""
    freezer.move_to(MONDAY)
    await _setup(hass, ajax_body=_ajax_body_with_nothing_ordered())
    state = hass.states.get(ORDERED_ID)
    assert state.state == "none"
    assert state.attributes["options_count"] == 2


async def test_authenticated_option_reports_a_real_price(hass: HomeAssistant, freezer):
    """Contrast with the anonymous case: a credentialed entry sees a real price."""
    freezer.move_to(MONDAY)
    await _setup(hass)
    state = hass.states.get(ORDERED_ID)
    ordered_option = next(o for o in state.attributes["options"] if o["label"] == "1")
    assert ordered_option["price"] == 37.00
    assert ordered_option["remaining"] is None  # zbyva -1 means "not tracked"


async def test_credentialed_entry_with_no_diner_data_does_not_raise(hass: HomeAssistant, freezer):
    """A credentialed entry whose diner is None (no ``stravnik`` object) must
    degrade to unknown, not raise.
    """
    freezer.move_to(MONDAY)
    payload = json.loads(load("ajax_authenticated.json"))
    del payload["stravnik"]
    await _setup(hass, ajax_body=json.dumps(payload))
    assert hass.states.get(BALANCE_ID).state == "unknown"
    assert hass.states.get(DEBT_ID).state == "unknown"
