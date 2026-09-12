"""Tests for the day sensors: state, attributes, and midnight rollover.

Entity ids are asserted against what Home Assistant actually registers
(``sensor.school_example_cz_obed_today`` /
``sensor.school_example_cz_obed_next_serving_day``), derived from the entry
title ``"school.example.cz"`` (the host alone -- the device identifies the
canteen, not any one meal type) and the ``today``/``next_serving_day``
translation keys, each carrying the meal type ("Oběd") as a placeholder --
not guessed.

All time control uses the ``freezer`` fixture (freezegun, via
``pytest_freezer``), never ``patch("homeassistant.util.dt.now")``: patching
``dt.now`` directly also alters Home Assistant's own internals during setup
and yields opaque failures.
"""

from __future__ import annotations

import datetime

from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.ejidelnicek.const import CONF_BASE_URL, DOMAIN
from tests.fixture_loader import load

# Neutral test host -- never a real school hostname.
BASE = "https://school.example.cz/ejidelnicek/"
MENU = BASE + "menu/"

TODAY_ID = "sensor.school_example_cz_obed_today"
NEXT_SERVING_DAY_ID = "sensor.school_example_cz_obed_next_serving_day"

# The fixture publishes 2026-09-14 .. 2026-09-25 (Mon .. Fri, two weeks).
MONDAY = datetime.datetime(2026, 9, 14, 12, 0, tzinfo=datetime.UTC)
SATURDAY = datetime.datetime(2026, 9, 19, 12, 0, tzinfo=datetime.UTC)

# US/Pacific (the test hass's fixed time zone) is UTC-7 in September, so
# this is 2026-09-14T23:59:00 local -- one minute before local midnight, and
# well inside the default 6-hour update interval of the moment the rollover
# test moves to next, so only the midnight listener (not a coordinator
# repoll) can explain the state change.
MONDAY_NIGHT = datetime.datetime(2026, 9, 15, 6, 59, 0, tzinfo=datetime.UTC)
LOCAL_MIDNIGHT = datetime.datetime(2026, 9, 15, 7, 0, 1, tzinfo=datetime.UTC)


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    """Set up an anonymous config entry against the two-option fixture."""
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


async def test_today_sensor_reports_the_dish_on_a_serving_day(hass: HomeAssistant, freezer):
    """Monday 2026-09-14 is a known serving day with two options."""
    freezer.move_to(MONDAY)
    await _setup(hass)
    state = hass.states.get(TODAY_ID)
    assert state.state == "Květák s vejci, brambory s pažitkou"
    assert state.attributes["soup"] == "Dýňový krém se semínky"
    assert state.attributes["options_count"] == 2
    assert state.attributes["date"] == "2026-09-14"


async def test_today_sensor_is_unknown_on_a_weekend(hass: HomeAssistant, freezer):
    """Saturday has no menu at all, so the state must read unknown, not fabricated."""
    freezer.move_to(SATURDAY)
    await _setup(hass)
    assert hass.states.get(TODAY_ID).state == "unknown"


async def test_next_serving_day_points_past_the_weekend(hass: HomeAssistant, freezer):
    """From Saturday, the next known serving day is Monday 2026-09-21."""
    freezer.move_to(SATURDAY)
    await _setup(hass)
    state = hass.states.get(NEXT_SERVING_DAY_ID)
    assert state.state == "Vepřový řízeček, bramborová kaše, maštěné máslem."
    assert state.attributes["date"] == "2026-09-21"
    assert state.attributes["days_ahead"] == 2


async def test_public_view_reports_no_ordered_option(hass: HomeAssistant, freezer):
    """An anonymous entry never sees an ordered option."""
    freezer.move_to(MONDAY)
    await _setup(hass)
    assert hass.states.get(TODAY_ID).attributes["ordered_option"] is None


async def test_public_view_never_shows_a_price_or_remaining_count(hass: HomeAssistant, freezer):
    """An anonymous entry must not report a fabricated price or remaining count.

    This is currently only guaranteed transitively through ``parser.py``;
    asserting it here guards against a regression in either ``parser.py`` or
    the ``float(...)`` conversion in ``sensor.py``'s ``_option_attributes``.
    Contrast with ``tests/test_credentialed_entities.py``, where a
    credentialed entry does report a real price (``37.00``).
    """
    freezer.move_to(MONDAY)
    await _setup(hass)
    option = hass.states.get(TODAY_ID).attributes["options"][0]
    assert option["price"] is None
    assert option["remaining"] is None


async def test_credential_only_entities_are_absent_when_anonymous(hass: HomeAssistant, freezer):
    """Task 11's balance sensor and debt binary sensor do not exist yet."""
    freezer.move_to(MONDAY)
    await _setup(hass)
    assert hass.states.get("sensor.school_example_cz_balance") is None
    assert hass.states.get("binary_sensor.school_example_cz_debt") is None


async def test_midnight_rollover_updates_today_without_a_repoll(hass: HomeAssistant, freezer):
    """The midnight time-change listener rolls "today" over on its own.

    The coordinator does not re-poll here (aioresponses keeps returning the
    exact same fixture body for the whole test) -- the state change must
    come solely from the ``async_track_time_change`` callback registered in
    ``EjidelnicekEntity.async_added_to_hass`` calling ``async_write_ha_state``
    and the properties recomputing from the now-later ``dt_util.now()``.
    """
    freezer.move_to(MONDAY_NIGHT)
    await _setup(hass)
    assert hass.states.get(TODAY_ID).attributes["date"] == "2026-09-14"

    # Move just past local midnight -- one minute later, far short of the
    # 6-hour update interval -- and fire the loop's scheduled timer handles,
    # exactly as HA's own scheduler would at that instant.
    freezer.move_to(LOCAL_MIDNIGHT)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    state = hass.states.get(TODAY_ID)
    assert state.attributes["date"] == "2026-09-15"
    assert state.state == "Rizoto s vepřového masa, sýr eidam"
