"""Tests for the frozen data models."""

import datetime
from decimal import Decimal

from custom_components.ejidelnicek.models import DayMenu, MealType, MenuOption


def _option(key: str, *, ordered: int = 0, primary: bool = False) -> MenuOption:
    return MenuOption(
        key=key,
        label=key,
        name=f"Dish {key}",
        allergens=(),
        allergen_codes=(),
        diet=None,
        price=Decimal("37.00"),
        ordered=ordered,
        remaining=None,
        db_id=int(key),
        is_primary=primary,
    )


def _day(value: datetime.date, *options: MenuOption) -> DayMenu:
    return DayMenu(
        date=value,
        weekday_label="",
        soups=(),
        dessert=None,
        drink=None,
        options=options,
        is_blocked=False,
    )


def test_primary_prefers_the_is_primary_option():
    day = _day(datetime.date(2026, 9, 14), _option("3"), _option("1", primary=True))
    assert day.primary.key == "1"


def test_primary_falls_back_to_first_option_when_none_marked():
    day = _day(datetime.date(2026, 9, 14), _option("3"), _option("1"))
    assert day.primary.key == "3"


def test_primary_is_none_for_a_day_with_no_options():
    assert _day(datetime.date(2026, 9, 14)).primary is None


def test_ordered_option_finds_the_booked_option():
    day = _day(datetime.date(2026, 9, 14), _option("1"), _option("2", ordered=1))
    assert day.ordered_option.key == "2"


def test_next_serving_day_skips_a_weekend():
    friday, monday = datetime.date(2026, 9, 18), datetime.date(2026, 9, 21)
    meal = MealType(
        index="0",
        strava_id=1,
        name="Oběd",
        order_day_offset=2,
        days={friday: _day(friday), monday: _day(monday)},
    )
    # Asked on Saturday, the next serving day is Monday.
    assert meal.next_serving_day(datetime.date(2026, 9, 19)).date == monday
    # Asked on Friday itself, Friday still counts.
    assert meal.next_serving_day(friday).date == friday


def test_next_serving_day_is_none_when_the_menu_has_run_out():
    friday = datetime.date(2026, 9, 18)
    meal = MealType(
        index="0", strava_id=1, name="Oběd", order_day_offset=2, days={friday: _day(friday)}
    )
    assert meal.next_serving_day(datetime.date(2026, 9, 19)) is None


def test_slug_is_ascii_and_snake_case():
    meal = MealType(index="0", strava_id=2, name="Oběd menu", order_day_offset=2, days={})
    assert meal.slug == "obed_menu"
