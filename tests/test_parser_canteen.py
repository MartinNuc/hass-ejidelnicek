import datetime
import json
from decimal import Decimal

import pytest

from custom_components.ejidelnicek.parser import (
    extract_payload,
    parse_canteen,
    parse_decimal_cz,
    resolve_allergens,
)
from tests.fixture_loader import PUBLIC_FIXTURES, load

# Fixture-shape mapping (fixtures are named by payload shape, not school):
#   letohrad_public.html   -> canteen_two_options.html
#   jakutska_public.html   -> canteen_long_window.html
#   betlemska_public.html  -> canteen_three_options.html
#   msjesenice_public.html -> canteen_placeholder.html
_FIXTURES = {
    "letohrad_public.html": "canteen_two_options.html",
    "jakutska_public.html": "canteen_long_window.html",
    "betlemska_public.html": "canteen_three_options.html",
    "msjesenice_public.html": "canteen_placeholder.html",
}


def _canteen(name, **kwargs):
    return parse_canteen(extract_payload(load(_FIXTURES.get(name, name))), **kwargs)


def test_allergen_codes_are_single_characters_not_integers():
    """'17' means codes 1 and 7. int('17') would silently pick the wrong allergen."""
    legend = {"1": "Obilniny", "7": "Mleko", "17": "Jecmen"}
    names, codes = resolve_allergens("17", legend)
    assert codes == ("1", "7")
    assert names == ("Obilniny", "Mleko")


def test_unknown_allergen_code_is_kept_as_a_code_without_a_name():
    names, codes = resolve_allergens("9", {"1": "Obilniny"})
    assert codes == ("9",)
    assert names == ()


def test_empty_allergens():
    assert resolve_allergens("", {"1": "x"}) == ((), ())
    assert resolve_allergens(None, {"1": "x"}) == ((), ())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("297,00", Decimal("297.00")),
        ("37.00", Decimal("37.00")),
        ("0,00", Decimal("0.00")),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_czech_decimal_comma(raw, expected):
    assert parse_decimal_cz(raw) == expected


@pytest.mark.parametrize("name", PUBLIC_FIXTURES)
def test_every_deployment_parses_into_at_least_one_meal_type(name):
    canteen = _canteen(name)
    assert canteen.meal_types
    assert canteen.allergens


def test_letohrad_parses_a_known_day():
    meal = _canteen("letohrad_public.html").meal_types[0]
    assert meal.name == "Oběd"
    assert meal.strava_id == 1
    assert meal.order_day_offset == 2
    day = meal.day_for(datetime.date(2026, 9, 14))
    assert day.soups[0].name == "Dýňový krém se semínky"
    assert day.dessert == "Salát bar / ovoce"
    assert {o.label for o in day.options} == {"1", "D"}
    assert day.primary.name == "Květák s vejci, brambory s pažitkou"


def test_public_view_reports_price_and_remaining_as_unknown_not_zero():
    day = _canteen("letohrad_public.html").meal_types[0].day_for(datetime.date(2026, 9, 14))
    assert day.primary.price is None
    assert day.primary.remaining is None
    assert day.primary.ordered == 0


def test_per_school_meal_ids_are_not_hardcoded():
    assert _canteen("jakutska_public.html").meal_types[0].strava_id == 2
    assert _canteen("betlemska_public.html").meal_types[0].strava_id == 3


def test_kindergarten_with_no_published_menu_parses_without_crashing():
    """msjesenice publishes empty soup/dessert/drink on every day."""
    meal = _canteen("msjesenice_public.html").meal_types[0]
    day = meal.day_for(meal.sorted_dates[0])
    assert day.soups == ()
    assert day.dessert is None
    assert day.drink is None
    assert day.options  # a single placeholder option


def test_allergen_letters_are_base36_against_real_fixture_data():
    """Real deployment data: alerg 'F79A' -> codes 15,7,9,10 (not dropped/misread).

    Confirmed against the fixture's own alergZobr rendering:
    'F79A' -> "obsahuje alergeny:1a,7,9,10", and alergenyMap["15"] == "1a - ...".
    """
    canteen = _canteen("jakutska_public.html")
    day = canteen.meal_types[0].day_for(datetime.date(2026, 9, 8))
    option = next(o for o in day.options if o.key == "1")
    assert option.allergen_codes == ("15", "7", "9", "10")
    assert option.allergens == tuple(canteen.allergens[code] for code in option.allergen_codes)
    assert all(option.allergens)  # every decoded code has a legend entry here


def test_authoritative_view_maps_real_price_ordered_and_remaining():
    payload = json.loads(load("ajax_authenticated.json"))["jidelnicek"]
    canteen = parse_canteen(payload, authoritative=True)
    day = canteen.meal_types[0].day_for(datetime.date(2026, 9, 14))

    option1 = next(o for o in day.options if o.key == "1")
    assert option1.ordered == 1
    assert option1.price == Decimal("37.00")
    assert option1.remaining is None  # zbyva: -1 means "not tracked"

    option2 = next(o for o in day.options if o.key == "2")
    assert option2.ordered == 0
    assert option2.remaining is None

    # barva: "A" means "ordered", not "blocked".
    assert day.is_blocked is False


def _minimal_payload(barva, extra_days=None):
    """Build a minimal synthetic payload for one meal type, one day."""
    day = {
        "datumden": "pondělí 14.9.2026",
        "polevka": [],
        "zakusek": "",
        "napoj": "",
        "barva": barva,
        "menuMap": {
            "1": {
                "dbId": 1,
                "nazev": "Test menu",
                "dMenu": "1",
                "alerg": "",
                "dieta": "",
                "isFirst": True,
                "cena": "0.00",
                "objednavka": 0,
                "zbyva": 0,
            }
        },
    }
    den_map = {"2026-09-14": day}
    if extra_days:
        den_map.update(extra_days)
    return {
        "alergenyMap": {},
        "dietyMap": {},
        "stravaMap": {
            "0": {
                "id": 1,
                "nazev": "Oběd",
                "posunDne": 0,
                "denMap": den_map,
            }
        },
    }


@pytest.mark.parametrize(
    ("barva", "expected"),
    [("B", True), ("A", False), (None, False)],
)
def test_is_blocked_is_true_only_for_barva_b(barva, expected):
    """barva 'A' means ordered, not blocked -- mistaking it would wrongly hide a menu."""
    payload = _minimal_payload(barva)
    day = parse_canteen(payload).meal_types[0].day_for(datetime.date(2026, 9, 14))
    assert day.is_blocked is expected


def test_invalid_iso_date_key_is_skipped_not_raised():
    valid_day = _minimal_payload(None)["stravaMap"]["0"]["denMap"]["2026-09-14"]
    payload = _minimal_payload(None, extra_days={"not-a-date": valid_day})
    meal = parse_canteen(payload).meal_types[0]
    assert meal.sorted_dates == (datetime.date(2026, 9, 14),)
