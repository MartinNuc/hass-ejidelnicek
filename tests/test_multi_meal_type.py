"""Tests for canteens that publish more than one meal type under one login.

Every fixture on disk carries exactly one ``stravaMap`` entry, which left the
whole multi-meal-type path -- the per-meal-type entity loops in ``sensor.py``
and ``calendar.py``, ``api._dates_to_fetch``'s dedup across meal types,
``api._merge_canteen``'s index matching, and the ``{meal_type}`` entity naming
-- entirely unexercised. Kindergartens in this system routinely publish
breakfast, lunch and a snack under one login (spec §3.3), so it is the most
likely real-world shape to break.

The payload here is synthesised in-test from ``canteen_two_options.html``
rather than captured: a second real deployment would be another school whose
identity must not be committed, and a derived payload keeps the two meal types
differing in exactly the dimensions under test (``id``, ``nazev``,
``posunDne``, and a partly disjoint ``denMap``).
"""

from __future__ import annotations

import copy
import datetime
import json
import re

from aioresponses import aioresponses
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ejidelnicek.api import _dates_to_fetch, _merge_canteen
from custom_components.ejidelnicek.const import CONF_BASE_URL, DOMAIN
from custom_components.ejidelnicek.parser import extract_payload, parse_canteen
from tests.fixture_loader import load

# Neutral test host -- never a real school hostname.
BASE = "https://school.example.cz/ejidelnicek/"
MENU = BASE + "menu/"
AJAX_RE = re.compile(r".*get-jidelnicek.*")

MONDAY = datetime.datetime(2026, 9, 14, 12, 0, tzinfo=datetime.UTC)

# The base fixture publishes 2026-09-14 .. 09-25 (Mon .. Fri, two weeks). The
# second meal type drops Tuesday 09-15 so the two meal types' "next serving
# day" genuinely differ from a Monday -- which is what makes the dedup in
# _dates_to_fetch observable rather than incidental.
DROPPED_FROM_SNACK = "2026-09-15"


def _two_meal_type_payload() -> dict:
    """Return a payload with a second meal type derived from the first."""
    payload = copy.deepcopy(extract_payload(load("canteen_two_options.html")))
    snack = copy.deepcopy(payload["stravaMap"]["0"])
    snack["id"] = 7
    snack["nazev"] = "Svačina"
    snack["posunDne"] = 1
    del snack["denMap"][DROPPED_FROM_SNACK]
    payload["stravaMap"]["1"] = snack
    return payload


def _two_meal_type_html() -> str:
    """Wrap the synthetic payload the way the public menu page does."""
    return f"<script>ejidelnicek.setJidelnicek({json.dumps(_two_meal_type_payload())});</script>"


def test_both_meal_types_parse_with_their_own_id_name_and_day_set():
    canteen = parse_canteen(_two_meal_type_payload())
    assert len(canteen.meal_types) == 2

    lunch = canteen.meal_type_by_index("0")
    snack = canteen.meal_type_by_index("1")
    assert (lunch.name, lunch.strava_id, lunch.order_day_offset) == ("Oběd", 1, 2)
    assert (snack.name, snack.strava_id, snack.order_day_offset) == ("Svačina", 7, 1)

    # The day sets really are disjoint in one day, not silently shared.
    dropped = datetime.date.fromisoformat(DROPPED_FROM_SNACK)
    assert lunch.day_for(dropped) is not None
    assert snack.day_for(dropped) is None
    assert len(snack.days) == len(lunch.days) - 1


def test_dates_to_fetch_deduplicates_and_unions_across_meal_types():
    """One date shared by both meal types is fetched once; a date only one of
    them serves is still fetched.
    """
    canteen = parse_canteen(_two_meal_type_payload())
    monday = datetime.date(2026, 9, 14)

    # Monday is published by both. Lunch's next serving day is Tuesday 09-15;
    # the snack skips it, so the snack's next serving day is Wednesday 09-16.
    assert _dates_to_fetch(canteen, monday) == (
        monday,
        datetime.date(2026, 9, 15),
        datetime.date(2026, 9, 16),
    )

    # From Sunday, today is unpublished and both meal types agree on Monday --
    # one date, not two.
    assert _dates_to_fetch(canteen, datetime.date(2026, 9, 13)) == (monday,)


def test_merge_canteen_matches_meal_types_by_index_not_by_position():
    """An authoritative payload carrying only the *second* meal type must land
    on that meal type, never on the first.
    """
    base = parse_canteen(_two_meal_type_payload())
    auth_payload = _two_meal_type_payload()
    del auth_payload["stravaMap"]["0"]
    authoritative = parse_canteen(auth_payload, authoritative=True)

    merged = _merge_canteen(base, authoritative)
    day = datetime.date(2026, 9, 14)
    # The snack's day came from the authoritative payload (prices resolved)...
    assert merged.meal_type_by_index("1").day_for(day).primary.price is not None
    # ...and the lunch, which the authoritative payload never mentioned, is
    # untouched (public payloads carry no price).
    assert merged.meal_type_by_index("0").day_for(day).primary.price is None


async def test_each_meal_type_gets_its_own_named_day_sensors(hass: HomeAssistant, freezer):
    """Four day sensors, with distinct entity ids and distinct friendly names.

    The meal type reaches the name through ``_attr_translation_placeholders``,
    so a bug that shared one placeholder across meal types would collapse all
    four into two colliding entity ids.
    """
    freezer.move_to(MONDAY)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: BASE},
        unique_id=f"{BASE}|public",
        title="school.example.cz",
    )
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(MENU, status=200, body=_two_meal_type_html(), repeat=True)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    expected = {
        "sensor.school_example_cz_obed_today": "Oběd today",
        "sensor.school_example_cz_obed_next_serving_day": "Oběd next serving day",
        "sensor.school_example_cz_svacina_today": "Svačina today",
        "sensor.school_example_cz_svacina_next_serving_day": "Svačina next serving day",
    }
    for entity_id, friendly_name in expected.items():
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.attributes["friendly_name"] == f"school.example.cz {friendly_name}"

    # Each meal type also gets its own calendar.
    assert hass.states.get("calendar.school_example_cz_obed_menu") is not None
    assert hass.states.get("calendar.school_example_cz_svacina_menu") is not None

    # The snack skips Tuesday, so its "next serving day" is Wednesday while
    # the lunch's is Tuesday -- the two meal types are genuinely independent.
    assert (
        hass.states.get("sensor.school_example_cz_obed_next_serving_day").attributes["date"]
        == "2026-09-15"
    )
    assert (
        hass.states.get("sensor.school_example_cz_svacina_next_serving_day").attributes["date"]
        == "2026-09-16"
    )


async def test_a_credentialed_entry_gets_an_ordered_sensor_per_meal_type(
    hass: HomeAssistant, freezer
):
    freezer.move_to(MONDAY)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: BASE, CONF_USERNAME: "u", CONF_PASSWORD: "p"},
        unique_id=f"{BASE}|u",
        title="school.example.cz",
    )
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(BASE, status=200, body="<form id='loginForm'></form>", repeat=True)
        mocked.post(
            BASE + "logincheck", status=200, body="ejidelnicek.setJidelnicek({})", repeat=True
        )
        mocked.get(MENU, status=200, body=_two_meal_type_html(), repeat=True)
        mocked.get(AJAX_RE, status=200, body=load("ajax_authenticated.json"), repeat=True)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.school_example_cz_obed_ordered_next_serving_day") is not None
    assert hass.states.get("sensor.school_example_cz_svacina_ordered_next_serving_day") is not None
    # One balance and one debt sensor for the entry, not one per meal type.
    assert hass.states.get("sensor.school_example_cz_balance") is not None
    assert hass.states.get("binary_sensor.school_example_cz_debt") is not None
