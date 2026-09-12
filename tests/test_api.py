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
    async_validate,
    candidate_base_urls,
)
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
            snapshot = await client.async_fetch_snapshot()
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
    assert result.menu_is_empty is True
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
    assert result.menu_is_empty is False


async def test_validate_reraises_the_last_error_when_no_candidate_works():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get("https://y.example.cz/ejidelnicek/menu/", status=500)
            mocked.get("http://y.example.cz/ejidelnicek/menu/", status=500)
            with pytest.raises(CannotConnect):
                await async_validate(session, "y.example.cz", None, None)
