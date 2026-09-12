"""Sensor platform for the E-jídelníček integration.

Two families of sensor live here:

* ``EjidelnicekDaySensor`` (Task 10) -- "today" and "next serving day", for
  every entry, credentialed or not.
* ``EjidelnicekOrderedSensor`` and ``EjidelnicekBalanceSensor`` (Task 11) --
  credential-only, gated on ``coordinator.client.has_credentials``. An
  anonymous entry never has real order or account data to report, so these
  are never created for one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.util import dt as dt_util

from .entity import EjidelnicekEntity
from .models import DayMenu, MenuOption

if TYPE_CHECKING:
    from decimal import Decimal

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EjidelnicekConfigEntry, EjidelnicekCoordinator

_STATE_MAX_LENGTH = 255

Which = Literal["today", "next_serving_day"]

# The ordered-option sensor's state when nothing has been ordered for the
# relevant day -- a plain string, not Python's None/"unknown", so an
# automation can reliably branch on "did I order something" vs. a real label.
NOTHING_ORDERED = "none"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EjidelnicekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up day sensors for every meal type, plus credential-only sensors."""
    coordinator = entry.runtime_data
    entities: list[EjidelnicekEntity] = []
    for meal_type in coordinator.data.canteen.meal_types:
        entities.append(EjidelnicekDaySensor(coordinator, entry, meal_type.index, "today"))
        entities.append(
            EjidelnicekDaySensor(coordinator, entry, meal_type.index, "next_serving_day")
        )
        if coordinator.client.has_credentials:
            entities.append(EjidelnicekOrderedSensor(coordinator, entry, meal_type.index))
    if coordinator.client.has_credentials:
        entities.append(EjidelnicekBalanceSensor(coordinator, entry))
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


class EjidelnicekOrderedSensor(EjidelnicekEntity, SensorEntity):
    """Reports what has been ordered for one meal type's next serving day.

    Credential-only: only a logged-in session sees real order data (see
    ``EjidelnicekClient.async_fetch_snapshot``), so this is only created when
    ``coordinator.client.has_credentials`` is true.

    ``native_value`` and ``extra_state_attributes`` are computed fresh from
    ``self.coordinator.data`` and ``dt_util.now()`` on every access, never
    cached -- same reasoning as ``EjidelnicekDaySensor``.
    """

    _attr_translation_key = "ordered_next_serving_day"

    def __init__(
        self,
        coordinator: EjidelnicekCoordinator,
        entry: EjidelnicekConfigEntry,
        meal_index: str,
    ) -> None:
        """Initialize the sensor for one meal type."""
        super().__init__(coordinator, entry)
        self._meal_index = meal_index
        self._attr_unique_id = f"{entry.entry_id}_{meal_index}_ordered_next_serving_day"
        meal_type = coordinator.data.canteen.meal_type_by_index(meal_index)
        meal_name = meal_type.name if meal_type is not None else meal_index
        self._attr_translation_placeholders = {"meal_type": meal_name}

    def _day(self) -> DayMenu | None:
        """Return this sensor's meal type's next known serving day, or None."""
        meal_type = self.coordinator.data.canteen.meal_type_by_index(self._meal_index)
        if meal_type is None:
            return None
        return meal_type.next_serving_day(dt_util.now().date())

    @property
    def native_value(self) -> str:
        """Return the ordered option's label, or NOTHING_ORDERED if none."""
        day = self._day()
        ordered_option = day.ordered_option if day is not None else None
        if ordered_option is None:
            return NOTHING_ORDERED
        return ordered_option.label[:_STATE_MAX_LENGTH]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return day details -- including ``options_count`` and ``options``.

        These let an automation tell a genuine choice (multiple options,
        only one of which was ordered) apart from a single-option day where
        "ordering" is a formality.
        """
        day = self._day()
        if day is None:
            return {}
        days_ahead = (day.date - dt_util.now().date()).days
        return _day_attributes(day, days_ahead=days_ahead)


class EjidelnicekBalanceSensor(EjidelnicekEntity, SensorEntity):
    """Reports the diner's account balance. One per config entry.

    Credential-only: the balance is only known once logged in, so this is
    only created when ``coordinator.client.has_credentials`` is true.

    ``state_class`` is ``TOTAL``, not ``MEASUREMENT`` or ``TOTAL_INCREASING``:
    a canteen account balance goes up (top-ups) and down (meals debited), so
    it is not monotonic like ``TOTAL_INCREASING``. Home Assistant's own
    ``DEVICE_CLASS_STATE_CLASSES`` table pairs ``SensorDeviceClass.MONETARY``
    with ``SensorStateClass.TOTAL`` alone, and this is exactly the same
    "bank account balance" shape used as canonical examples by other core
    integrations that expose a fluctuating monetary balance (for example
    ``firefly_iii`` and ``simplefin``).
    """

    _attr_translation_key = "balance"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "CZK"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: EjidelnicekCoordinator,
        entry: EjidelnicekConfigEntry,
    ) -> None:
        """Initialize the sensor for the config entry's diner."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_balance"

    @property
    def native_value(self) -> Decimal | None:
        """Return the diner's balance, or None if diner data did not arrive."""
        diner = self.coordinator.data.diner
        if diner is None:
            return None
        return diner.balance
