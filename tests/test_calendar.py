"""Tests for the calendar entity: all-day events and chronological ordering.

All time control uses the ``freezer`` fixture (freezegun, via
``pytest_freezer``), never ``patch("homeassistant.util.dt.now")`` -- same
reasoning as ``tests/test_sensor.py``.
"""

from __future__ import annotations

import datetime

from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ejidelnicek.const import CONF_BASE_URL, DOMAIN
from tests.fixture_loader import load

# Neutral test host -- never a real school hostname.
BASE = "https://school.example.cz/ejidelnicek/"
MENU = BASE + "menu/"

ENTITY = "calendar.obed_school_example_cz_menu"

# The fixture publishes 2026-09-14 .. 2026-09-25 (Mon .. Fri, two weeks).
MONDAY = datetime.datetime(2026, 9, 14, 12, 0, tzinfo=datetime.UTC)


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    """Set up an anonymous config entry against the two-option fixture."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: BASE},
        unique_id=f"{BASE}|public",
        title="Oběd – school.example.cz",  # noqa: RUF001
    )
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(MENU, status=200, body=load("canteen_two_options.html"), repeat=True)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_all_day_events_use_an_exclusive_end_date(hass: HomeAssistant, freezer):
    freezer.move_to(MONDAY)
    await _setup(hass)
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": ENTITY,
            "start_date_time": "2026-09-14T00:00:00",
            "end_date_time": "2026-09-15T00:00:00",
        },
        blocking=True,
        return_response=True,
    )
    found = events[ENTITY]["events"]
    assert len(found) == 1
    assert found[0]["start"] == "2026-09-14"
    assert found[0]["end"] == "2026-09-15"
    assert found[0]["summary"] == "Květák s vejci, brambory s pažitkou"
    assert "Dýňový krém se semínky" in found[0]["description"]
    assert "D: Menu 1" in found[0]["description"]


async def test_events_are_returned_in_chronological_order(hass: HomeAssistant, freezer):
    freezer.move_to(MONDAY)
    await _setup(hass)
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": ENTITY,
            "start_date_time": "2026-09-14T00:00:00",
            "end_date_time": "2026-09-26T00:00:00",
        },
        blocking=True,
        return_response=True,
    )
    starts = [e["start"] for e in events[ENTITY]["events"]]
    assert starts == sorted(starts)
    assert len(starts) == 10
