"""Tests for the frozen data models."""

import datetime
from decimal import Decimal

from custom_components.ejidelnicek.models import (
    Canteen,
    DayMenu,
    MealType,
    MenuOption,
    Snapshot,
)


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


def test_next_serving_day_is_strictly_after_the_given_date():
    """Strictly after, so it never duplicates ``day_for(today)``.

    ``day_for`` already answers "what is on the plate today". If
    ``next_serving_day`` were on-or-after, it would return today on every
    serving day -- five days out of seven -- and an automation asking on a
    Monday evening what tomorrow's lunch is would get Monday's.
    """
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
    # Asked on Friday itself, Friday does NOT count -- Monday is next.
    assert meal.next_serving_day(friday).date == monday


def test_next_serving_day_is_none_when_the_menu_has_run_out():
    friday = datetime.date(2026, 9, 18)
    meal = MealType(
        index="0", strava_id=1, name="Oběd", order_day_offset=2, days={friday: _day(friday)}
    )
    assert meal.next_serving_day(datetime.date(2026, 9, 19)) is None
    # Asked *on* the last published day, there is no day after it either.
    assert meal.next_serving_day(friday) is None


def test_two_snapshots_that_differ_only_in_fetched_at_are_equal():
    """``fetched_at`` must not defeat the coordinator's ``always_update=False``.

    Home Assistant skips writing entity state when the new coordinator data
    equals the previous data. A timestamp that changes on every poll would make
    ``Snapshot.__eq__`` unconditionally false, so every poll would churn every
    entity -- nullifying the reason these models are frozen and comparable at
    all.
    """
    canteen = Canteen(allergens={}, diets={}, meal_types=())
    first = Snapshot(
        canteen=canteen,
        diner=None,
        fetched_at=datetime.datetime(2026, 9, 14, 6, 0, tzinfo=datetime.UTC),
    )
    second = Snapshot(
        canteen=canteen,
        diner=None,
        fetched_at=datetime.datetime(2026, 9, 14, 12, 0, tzinfo=datetime.UTC),
    )
    assert first == second
    # ...but a real difference still compares unequal.
    other = Snapshot(
        canteen=Canteen(allergens={"1": "Obilniny"}, diets={}, meal_types=()),
        diner=None,
        fetched_at=first.fetched_at,
    )
    assert first != other
