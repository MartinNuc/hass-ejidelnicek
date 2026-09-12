import datetime
import re
from decimal import Decimal

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.ejidelnicek.api import (
    CannotConnect,
    EjidelnicekClient,
    InvalidAuth,
    UnsupportedSite,
    _dates_to_fetch,
    async_validate,
    candidate_base_urls,
    menu_is_empty,
)
from custom_components.ejidelnicek.parser import extract_payload, parse_canteen
from tests.fixture_loader import load

# Neutral test host -- never a real school hostname.
BASE = "https://school.example.cz/ejidelnicek/"
MENU = BASE + "menu/"
AJAX_RE = re.compile(r".*get-jidelnicek.*")


@pytest.mark.parametrize(
    ("raw", "expected_first"),
    [
        ("https://x.cz", "https://x.cz/ejidelnicek/"),
        ("https://x.cz/ejidelnicek", "https://x.cz/ejidelnicek/"),
        ("https://x.cz/ejidelnicek/", "https://x.cz/ejidelnicek/"),
        ("https://x.cz/ejidelnicek/menu/", "https://x.cz/ejidelnicek/"),
        ("http://x.cz:8080/ejidelnicek/", "http://x.cz:8080/ejidelnicek/"),
        ("  x.cz  ", "https://x.cz/ejidelnicek/"),
    ],
)
def test_url_normalisation(raw, expected_first):
    assert candidate_base_urls(raw)[0] == expected_first


def test_scheme_is_only_guessed_when_absent():
    # No scheme given: try https, then fall back to http (several canteens are http-only).
    assert candidate_base_urls("x.cz") == (
        "https://x.cz/ejidelnicek/",
        "http://x.cz/ejidelnicek/",
    )
    # Scheme given: respect it, do not silently try the other one.
    assert candidate_base_urls("http://x.cz") == ("http://x.cz/ejidelnicek/",)


async def test_anonymous_fetch_uses_a_single_request():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(MENU, status=200, body=load("canteen_two_options.html"))
            client = EjidelnicekClient(session, BASE)
            snapshot = await client.async_fetch_snapshot()
    assert snapshot.diner is None
    assert snapshot.canteen.meal_types[0].name == "Oběd"


def test_has_credentials():
    session = object()  # never touched by has_credentials
    assert EjidelnicekClient(session, BASE).has_credentials is False
    assert EjidelnicekClient(session, BASE, "u", None).has_credentials is False
    assert EjidelnicekClient(session, BASE, None, "p").has_credentials is False
    assert EjidelnicekClient(session, BASE, "u", "p").has_credentials is True


async def test_a_page_without_a_payload_is_reported_as_an_unsupported_site():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(MENU, status=200, body=load("not_ejidelnicek.html"))
            with pytest.raises(UnsupportedSite):
                await EjidelnicekClient(session, BASE).async_fetch_public()


async def test_connection_errors_surface_as_cannot_connect():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(MENU, status=500)
            with pytest.raises(CannotConnect):
                await EjidelnicekClient(session, BASE).async_fetch_public()


async def test_failed_login_raises_invalid_auth():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(BASE, status=200, body="<form id='loginForm'></form>")
            mocked.post(
                BASE + "logincheck",
                status=200,
                body="<form id='loginForm'>bad</form>",
            )
            client = EjidelnicekClient(session, BASE, "u", "p")
            with pytest.raises(InvalidAuth):
                await client.async_login()


async def test_authenticated_snapshot_merges_order_data_over_the_public_menu():
    # ``today`` is passed explicitly: the set of days worth fetching is
    # derived from it, so letting it default to the real current date would
    # make this test's behaviour drift with the wall clock and break outright
    # once the fixture's published window (2026-09-14 .. 09-25) is in the past.
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(BASE, status=200, body="<form id='loginForm'></form>")
            mocked.post(BASE + "logincheck", status=200, body="ejidelnicek.setJidelnicek({})")
            mocked.get(MENU, status=200, body=load("canteen_two_options.html"))
            # Any datum the client asks for returns the synthetic authenticated day.
            mocked.get(
                AJAX_RE,
                status=200,
                body=load("ajax_authenticated.json"),
                repeat=True,
            )
            client = EjidelnicekClient(session, BASE, "u", "p")
            snapshot = await client.async_fetch_snapshot(today=datetime.date(2026, 9, 13))
    assert snapshot.diner.balance == Decimal("297.00")
    meal = snapshot.canteen.meal_types[0]
    # The ordered day merged the authoritative order data in.
    ordered_day = meal.day_for(datetime.date(2026, 9, 14))
    assert ordered_day.ordered_option.key == "1"
    # Public menu text is still present for days we did not fetch authoritatively.
    assert meal.day_for(datetime.date(2026, 9, 25)) is not None


async def test_session_expiry_triggers_one_relogin_and_one_retry():
    day = datetime.date(2026, 9, 14)
    async with ClientSession() as session:
        with aioresponses() as mocked:
            # First attempt: session looks expired (redirect back to login).
            mocked.get(AJAX_RE, status=302)
            # Recovery: re-login...
            mocked.get(BASE, status=200, body="<form id='loginForm'></form>")
            mocked.post(BASE + "logincheck", status=200, body="ejidelnicek.setJidelnicek({})")
            # ...then the retry succeeds.
            mocked.get(AJAX_RE, status=200, body=load("ajax_authenticated.json"))
            client = EjidelnicekClient(session, BASE, "u", "p")
            canteen, diner = await client.async_fetch_day(day)
    assert diner.balance == Decimal("297.00")
    assert canteen.meal_types[0].day_for(day).ordered_option.key == "1"


async def test_session_recovery_gives_up_after_one_retry():
    day = datetime.date(2026, 9, 14)
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(AJAX_RE, status=302, repeat=True)
            mocked.get(BASE, status=200, body="<form id='loginForm'></form>", repeat=True)
            mocked.post(
                BASE + "logincheck",
                status=200,
                body="ejidelnicek.setJidelnicek({})",
                repeat=True,
            )
            client = EjidelnicekClient(session, BASE, "u", "p")
            with pytest.raises(InvalidAuth):
                await client.async_fetch_day(day)


async def test_validate_flags_a_canteen_that_publishes_no_menu_publicly():
    base = "https://kindergarten.example.cz/ejidelnicek/"
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(base + "menu/", status=200, body=load("canteen_placeholder.html"))
            result = await async_validate(session, base, None, None)
    assert menu_is_empty(result.canteen) is True
    assert result.base_url == base


async def test_validate_falls_back_from_https_to_http_candidate():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get("https://x.example.cz/ejidelnicek/menu/", status=500)
            mocked.get(
                "http://x.example.cz/ejidelnicek/menu/",
                status=200,
                body=load("canteen_two_options.html"),
            )
            result = await async_validate(session, "x.example.cz", None, None)
    assert result.base_url == "http://x.example.cz/ejidelnicek/"
    assert menu_is_empty(result.canteen) is False


async def test_validate_reraises_the_last_error_when_no_candidate_works():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get("https://y.example.cz/ejidelnicek/menu/", status=500)
            mocked.get("http://y.example.cz/ejidelnicek/menu/", status=500)
            with pytest.raises(CannotConnect):
                await async_validate(session, "y.example.cz", None, None)


def _two_options_canteen():
    return parse_canteen(extract_payload(load("canteen_two_options.html")))


def test_dates_to_fetch_covers_today_and_the_next_serving_day():
    """The documented steady-state budget is three requests, so two AJAX days.

    ``next_serving_day`` is strictly forward, so on a published day the set is
    {today, the day after it} -- which is what restores the three-request
    budget ``api.py``'s header documents (one ``menu/`` plus one AJAX call per
    distinct date).
    """
    canteen = _two_options_canteen()
    assert _dates_to_fetch(canteen, datetime.date(2026, 9, 14)) == (
        datetime.date(2026, 9, 14),
        datetime.date(2026, 9, 15),
    )


def test_dates_to_fetch_skips_an_unpublished_today():
    """From a weekend, only the next published day is worth an AJAX call."""
    canteen = _two_options_canteen()
    assert _dates_to_fetch(canteen, datetime.date(2026, 9, 19)) == (datetime.date(2026, 9, 21),)


def test_dates_to_fetch_is_empty_once_the_published_window_has_passed():
    canteen = _two_options_canteen()
    assert _dates_to_fetch(canteen, datetime.date(2026, 10, 1)) == ()


@pytest.mark.parametrize(
    "raw",
    ["HTTPS://X.CZ/EJIDELNICEK/", "https://x.cz/EJidelnicek", "https://x.cz/EJIDELNICEK/MENU/"],
)
def test_the_ejidelnicek_path_segment_is_matched_case_insensitively(raw):
    """A URL pasted out of a browser bar must not gain a second path segment."""
    (candidate,) = candidate_base_urls(raw)
    assert candidate.lower() == "https://x.cz/ejidelnicek/"


def test_a_canteen_serving_only_a_main_course_is_not_reported_as_empty():
    """Missing soup, dessert and drink alone is not the placeholder signal.

    A canteen that genuinely serves nothing but a main course would otherwise
    get the "publishes nothing publicly" Repairs issue. Only a canteen whose
    every day is a *single* option with no other content qualifies.
    """
    assert menu_is_empty(parse_canteen(extract_payload(load("canteen_long_window.html")))) is False
    assert menu_is_empty(parse_canteen(extract_payload(load("canteen_placeholder.html")))) is True
