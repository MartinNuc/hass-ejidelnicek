import datetime
from decimal import Decimal

from custom_components.ejidelnicek.models import DayMenu, MenuOption
from custom_components.ejidelnicek.parser import (
    extract_payload,
    merge_day,
    parse_ajax,
    parse_canteen,
    parse_diner,
)
from tests.fixture_loader import load

DAY = datetime.date(2026, 9, 14)


def _option(key, *, ordered=0, price=None, remaining=None, name=None):
    return MenuOption(
        key=key,
        label=key,
        name=name or f"Dish {key}",
        allergens=(),
        allergen_codes=(),
        diet=None,
        price=price,
        ordered=ordered,
        remaining=remaining,
        db_id=int(key),
        is_primary=key == "1",
    )


def test_merge_overlays_order_data_onto_the_public_day():
    base = DayMenu(
        date=DAY,
        weekday_label="pondělí",
        soups=(),
        dessert="Ovoce",
        drink="Voda",
        options=(_option("1"), _option("3")),
        is_blocked=False,
    )
    auth = DayMenu(
        date=DAY,
        weekday_label="",
        soups=(),
        dessert=None,
        drink=None,
        options=(_option("1", ordered=1, price=Decimal("37.00")),),
        is_blocked=False,
    )
    merged = merge_day(base, auth)
    assert merged.ordered_option.key == "1"
    assert merged.options[0].price == Decimal("37.00")
    # Menu text from the public page survives.
    assert merged.dessert == "Ovoce"
    # An option the AJAX response omitted is kept, not dropped.
    assert {o.key for o in merged.options} == {"1", "3"}
    assert merged.options[1].ordered == 0


def test_merge_takes_blocked_state_from_the_authoritative_day():
    base = DayMenu(
        date=DAY,
        weekday_label="",
        soups=(),
        dessert=None,
        drink=None,
        options=(_option("1"),),
        is_blocked=False,
    )
    auth = DayMenu(
        date=DAY,
        weekday_label="",
        soups=(),
        dessert=None,
        drink=None,
        options=(_option("1"),),
        is_blocked=True,
    )
    assert merge_day(base, auth).is_blocked is True


def test_merge_does_not_mutate_its_inputs():
    base = DayMenu(
        date=DAY,
        weekday_label="pondělí",
        soups=(),
        dessert="Ovoce",
        drink="Voda",
        options=(_option("1"), _option("3")),
        is_blocked=False,
    )
    auth = DayMenu(
        date=DAY,
        weekday_label="",
        soups=(),
        dessert=None,
        drink=None,
        options=(_option("1", ordered=1, price=Decimal("37.00")),),
        is_blocked=True,
    )
    base_options_before = base.options
    auth_options_before = auth.options
    merge_day(base, auth)
    assert base.options == base_options_before
    assert base.options[0].ordered == 0
    assert base.options[0].price is None
    assert base.is_blocked is False
    assert base.dessert == "Ovoce"
    assert auth.options == auth_options_before


def test_parse_ajax_reads_orders_balance_and_debt():
    canteen, diner = parse_ajax(load("ajax_authenticated.json"))
    meal = canteen.meal_types[0]
    day = meal.day_for(meal.sorted_dates[0])
    assert day.ordered_option.key == "1"
    assert day.ordered_option.price == Decimal("37.00")
    # zbyva of -1 means untracked, not "none left".
    assert day.ordered_option.remaining is None
    assert diner.balance == Decimal("297.00")
    assert diner.in_debt is False


def test_diner_never_exposes_identifying_fields():
    _, diner = parse_ajax(load("ajax_authenticated.json"))
    for forbidden in ("jmeno", "cislo", "vs", "loginEmail", "name"):
        assert not hasattr(diner, forbidden)


def test_parse_diner_maps_fields_with_czech_decimal_commas():
    diner = parse_diner(
        {
            "konto": "297,00",
            "kontoStravne": "150,50",
            "kontoSkolne": "0,00",
            "dluh": True,
            "bezObjednavani": True,
        }
    )
    assert diner.balance == Decimal("297.00")
    assert diner.balance_meals == Decimal("150.50")
    assert diner.balance_tuition == Decimal("0.00")
    assert diner.in_debt is True
    assert diner.ordering_disabled is True


def test_parse_diner_missing_keys_yield_none():
    diner = parse_diner({})
    assert diner.balance is None
    assert diner.balance_meals is None
    assert diner.balance_tuition is None
    assert diner.in_debt is None
    assert diner.ordering_disabled is None


def test_parse_ajax_returns_none_diner_when_stravnik_missing():
    import json

    payload = json.loads(load("ajax_authenticated.json"))
    del payload["stravnik"]
    canteen, diner = parse_ajax(json.dumps(payload))
    assert diner is None
    assert canteen.meal_types


def test_parse_ajax_returns_none_diner_when_stravnik_not_a_dict():
    import json

    payload = json.loads(load("ajax_authenticated.json"))
    payload["stravnik"] = None
    _, diner = parse_ajax(json.dumps(payload))
    assert diner is None


def test_parse_ajax_raises_on_invalid_json():
    from custom_components.ejidelnicek.parser import PayloadNotFound

    try:
        parse_ajax("not json")
        raise AssertionError("expected PayloadNotFound")
    except PayloadNotFound:
        pass


def test_parse_ajax_raises_when_no_jidelnicek_key():
    from custom_components.ejidelnicek.parser import PayloadNotFound

    try:
        parse_ajax('{"stravnik": {}}')
        raise AssertionError("expected PayloadNotFound")
    except PayloadNotFound:
        pass


def test_parse_ajax_uses_authoritative_parsing_directly_matches_parse_canteen():
    # Sanity check that parse_ajax's canteen matches parse_canteen(..., authoritative=True)
    import json

    payload = json.loads(load("ajax_authenticated.json"))
    expected = parse_canteen(payload["jidelnicek"], authoritative=True)
    canteen, _ = parse_ajax(load("ajax_authenticated.json"))
    assert canteen == expected


def test_extract_payload_still_importable():
    # Guard against accidental removal of existing exports while editing parser.py.
    assert extract_payload is not None
