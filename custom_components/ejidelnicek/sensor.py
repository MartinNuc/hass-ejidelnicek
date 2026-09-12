"""Sensor platform for the E-jídelníček integration: the day sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from homeassistant.components.sensor import SensorEntity
from homeassistant.util import dt as dt_util

from .entity import EjidelnicekEntity
from .models import DayMenu, MenuOption

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EjidelnicekConfigEntry, EjidelnicekCoordinator

_STATE_MAX_LENGTH = 255

Which = Literal["today", "next_serving_day"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EjidelnicekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up "today" and "next serving day" sensors for every meal type."""
    coordinator = entry.runtime_data
    entities: list[EjidelnicekDaySensor] = []
    for meal_type in coordinator.data.canteen.meal_types:
        entities.append(EjidelnicekDaySensor(coordinator, entry, meal_type.index, "today"))
        entities.append(
            EjidelnicekDaySensor(coordinator, entry, meal_type.index, "next_serving_day")
        )
    async_add_entities(entities)


def _option_attributes(option: MenuOption) -> dict[str, Any]:
    """Return a plain-dict representation of a menu option for attributes.

    ``price`` is converted from ``Decimal`` to ``float`` because HA state
    attributes must be JSON-serializable; it (like ``remaining``) is ``None``
    for anonymous entries by design -- the public payload zeroes both, and
    reporting ``0`` would misleadingly read as "free" or "sold out".
    """
    return {
        "label": option.label,
        "name": option.name,
        "allergens": option.allergens,
        "allergen_codes": option.allergen_codes,
        "diet": option.diet,
        "price": float(option.price) if option.price is not None else None,
        "ordered": option.ordered,
        "remaining": option.remaining,
    }


def _day_attributes(day: DayMenu, *, days_ahead: int | None = None) -> dict[str, Any]:
    """Return the full extra-state-attributes dict for a known day."""
    soups = tuple(soup.name for soup in day.soups)
    ordered_option = day.ordered_option
    attributes: dict[str, Any] = {
        "date": day.date.isoformat(),
        "weekday_label": day.weekday_label,
        "soup": soups[0] if soups else None,
        "soups": soups,
        "dessert": day.dessert,
        "drink": day.drink,
        "options": [_option_attributes(option) for option in day.options],
        "options_count": len(day.options),
        "ordered_option": ordered_option.label if ordered_option is not None else None,
        "is_blocked": day.is_blocked,
    }
    if days_ahead is not None:
        attributes["days_ahead"] = days_ahead
    return attributes


class EjidelnicekDaySensor(EjidelnicekEntity, SensorEntity):
    """Reports the primary dish for "today" or the next known serving day.

    ``native_value`` and ``extra_state_attributes`` are computed fresh from
    ``self.coordinator.data`` and ``dt_util.now()`` on every access, never
    cached -- see ``EjidelnicekEntity`` for why that is what makes the
    midnight rollover work.
    """

    def __init__(
        self,
        coordinator: EjidelnicekCoordinator,
        entry: EjidelnicekConfigEntry,
        meal_index: str,
        which: Which,
    ) -> None:
        """Initialize the sensor for one meal type and one day selection."""
        super().__init__(coordinator, entry)
        self._meal_index = meal_index
        self._which = which
        self._attr_translation_key = which
        self._attr_unique_id = f"{entry.entry_id}_{meal_index}_{which}"

    def _day(self) -> DayMenu | None:
        """Return the relevant DayMenu for this sensor's meal type, or None."""
        meal_type = self.coordinator.data.canteen.meal_type_by_index(self._meal_index)
        if meal_type is None:
            return None
        today = dt_util.now().date()
        if self._which == "today":
            return meal_type.day_for(today)
        return meal_type.next_serving_day(today)

    @property
    def native_value(self) -> str | None:
        """Return the primary dish's name, clamped to HA's 255-char state limit."""
        day = self._day()
        if day is None or day.primary is None:
            return None
        return day.primary.name[:_STATE_MAX_LENGTH]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return day details. Minimal (empty) when no day is known at all."""
        day = self._day()
        if day is None:
            return {}
        if self._which == "next_serving_day":
            days_ahead = (day.date - dt_util.now().date()).days
            return _day_attributes(day, days_ahead=days_ahead)
        return _day_attributes(day)
