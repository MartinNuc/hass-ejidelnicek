"""Frozen data models for the E-jídelníček integration.

These dataclasses are the shared vocabulary between the parser, the API
client, the coordinator and the entities. They hold no behaviour beyond pure,
in-memory lookups and are never mutated once built, so the coordinator can
rely on value equality (``always_update=False``) to avoid churning entity
state when a fetch returns unchanged data.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from homeassistant.util import slugify


@dataclass(frozen=True)
class Dish:
    """A single dish (for example a soup) with its allergen information."""

    name: str
    allergens: tuple[str, ...]
    allergen_codes: tuple[str, ...]


@dataclass(frozen=True)
class MenuOption:
    """One selectable main-course option offered for a given day."""

    key: str
    label: str
    name: str
    allergens: tuple[str, ...]
    allergen_codes: tuple[str, ...]
    diet: str | None
    price: Decimal | None
    ordered: int
    remaining: int | None
    db_id: int
    is_primary: bool


@dataclass(frozen=True)
class DayMenu:
    """The full menu for one meal type on one day."""

    date: datetime.date
    weekday_label: str
    soups: tuple[Dish, ...]
    dessert: str | None
    drink: str | None
    options: tuple[MenuOption, ...]
    is_blocked: bool

    @property
    def primary(self) -> MenuOption | None:
        """Return the option marked as primary, else the first option, else None."""
        if not self.options:
            return None
        for option in self.options:
            if option.is_primary:
                return option
        return self.options[0]

    @property
    def ordered_option(self) -> MenuOption | None:
        """Return the first option that has been ordered, else None."""
        for option in self.options:
            if option.ordered > 0:
                return option
        return None


@dataclass(frozen=True)
class MealType:
    """A meal type (for example lunch) with its menu across known days."""

    index: str
    strava_id: int
    name: str
    order_day_offset: int
    days: Mapping[datetime.date, DayMenu]

    @property
    def sorted_dates(self) -> tuple[datetime.date, ...]:
        """Return the known dates for this meal type, sorted ascending."""
        return tuple(sorted(self.days))

    def day_for(self, value: datetime.date) -> DayMenu | None:
        """Return the menu for the given date, or None if it is not known."""
        return self.days.get(value)

    def next_serving_day(self, on_or_after: datetime.date) -> DayMenu | None:
        """Return the earliest known day whose date is on or after the given date.

        Returns None if no known day qualifies.
        """
        for value in self.sorted_dates:
            if value >= on_or_after:
                return self.days[value]
        return None

    @property
    def slug(self) -> str:
        """Return an ASCII, snake_case slug of the meal type's name."""
        return slugify(self.name)


@dataclass(frozen=True)
class Diner:
    """Account balance and ordering status for the logged-in diner.

    Deliberately does not model the diner's name, account number, payment
    symbol or login email: the integration has no use for them, and keeping
    them out of this model keeps them from leaking into entity attributes,
    diagnostics or logs.
    """

    balance: Decimal | None
    balance_meals: Decimal | None
    balance_tuition: Decimal | None
    in_debt: bool | None
    ordering_disabled: bool | None


@dataclass(frozen=True)
class Canteen:
    """The canteen's legends (allergens, diets) and its meal types."""

    allergens: Mapping[str, str]
    diets: Mapping[str, str]
    meal_types: tuple[MealType, ...]

    def meal_type_by_index(self, index: str) -> MealType | None:
        """Return the meal type with the given index, or None if not found."""
        for meal_type in self.meal_types:
            if meal_type.index == index:
                return meal_type
        return None


@dataclass(frozen=True)
class Snapshot:
    """A single fetched, self-consistent view of the canteen and diner."""

    canteen: Canteen
    diner: Diner | None
    fetched_at: datetime.datetime
