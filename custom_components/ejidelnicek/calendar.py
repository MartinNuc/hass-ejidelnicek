"""Calendar platform for the E-jídelníček integration.

One ``EjidelnicekCalendar`` per meal type, mirroring the day sensors: each
known day becomes an all-day ``CalendarEvent`` running from that date to the
following date -- Home Assistant treats a ``CalendarEvent``'s ``end`` as
exclusive, so this is a single-day event, not a two-day one.

Like the sensors in ``sensor.py``, everything here is computed fresh from
``self.coordinator.data`` (and, for ``event``, ``dt_util.now()``) on every
access -- never cached into ``_attr_*`` -- so the midnight rollover trigger
inherited from ``EjidelnicekEntity`` is enough to roll "today" over.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import dt as dt_util

from .entity import EjidelnicekEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EjidelnicekConfigEntry, EjidelnicekCoordinator
    from .models import DayMenu

# See ``_summarize``: intentionally not translated.
_BLOCKED_PREFIX = "Blocked: "


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EjidelnicekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one calendar entity per meal type."""
    coordinator = entry.runtime_data
    async_add_entities(
        EjidelnicekCalendar(coordinator, entry, meal_type.index)
        for meal_type in coordinator.data.canteen.meal_types
    )


def _describe(day: DayMenu) -> str:
    """Build the multi-line event description.

    Lists the soup(s), then every option as ``"<label>: <name>"``, then the
    dessert, the drink and finally the allergens -- collected across the
    soups and every option, deduplicated and sorted for a stable rendering.
    """
    lines: list[str] = [soup.name for soup in day.soups]
    lines.extend(f"{option.label}: {option.name}" for option in day.options)
    if day.dessert:
        lines.append(day.dessert)
    if day.drink:
        lines.append(day.drink)
    allergens = {allergen for soup in day.soups for allergen in soup.allergens}
    for option in day.options:
        allergens.update(option.allergens)
    if allergens:
        lines.append(", ".join(sorted(allergens)))
    return "\n".join(lines)


def _summarize(day: DayMenu) -> str:
    """Return the event summary: the primary dish, flagged when blocked.

    The "Blocked: " prefix is deliberately untranslated English. A calendar
    event's summary is plain data written into the event, not entity state, so
    Home Assistant's translation machinery never reaches it: translating it
    would mean picking a language at fetch time and baking it into events that
    persist, and the dish name it prefixes is Czech either way. The
    machine-readable form of the same fact is the ``is_blocked`` attribute on
    the day sensors, which is what an automation should branch on.
    """
    name = day.primary.name if day.primary is not None else "?"
    return f"{_BLOCKED_PREFIX}{name}" if day.is_blocked else name


def _event_for(day: DayMenu) -> CalendarEvent:
    """Build the all-day ``CalendarEvent`` for one known day."""
    return CalendarEvent(
        start=day.date,
        end=day.date + datetime.timedelta(days=1),
        summary=_summarize(day),
        description=_describe(day),
    )


class EjidelnicekCalendar(EjidelnicekEntity, CalendarEntity):
    """A calendar of one meal type's daily menu, as all-day events."""

    _attr_translation_key = "menu"

    def __init__(
        self,
        coordinator: EjidelnicekCoordinator,
        entry: EjidelnicekConfigEntry,
        meal_index: str,
    ) -> None:
        """Initialize the calendar for one meal type."""
        super().__init__(coordinator, entry)
        self._meal_index = meal_index
        self._attr_unique_id = f"{entry.entry_id}_{meal_index}_menu"
        meal_type = coordinator.data.canteen.meal_type_by_index(meal_index)
        meal_name = meal_type.name if meal_type is not None else meal_index
        self._attr_translation_placeholders = {"meal_type": meal_name}

    @property
    def event(self) -> CalendarEvent | None:
        """Return today's event if known, else the next known upcoming one."""
        meal_type = self.coordinator.data.canteen.meal_type_by_index(self._meal_index)
        if meal_type is None:
            return None
        today = dt_util.now().date()
        for value in meal_type.sorted_dates:
            if value >= today:
                return _event_for(meal_type.days[value])
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return known days whose all-day event overlaps the given window.

        Always returned sorted by start -- ``sorted_dates`` is already
        ascending -- because Home Assistant enforces that invariant on
        whatever a calendar entity returns here.
        """
        meal_type = self.coordinator.data.canteen.meal_type_by_index(self._meal_index)
        if meal_type is None:
            return []
        events = []
        for value in meal_type.sorted_dates:
            day_start = dt_util.start_of_local_day(value)
            day_end = day_start + datetime.timedelta(days=1)
            if day_start < end_date and day_end > start_date:
                events.append(_event_for(meal_type.days[value]))
        return events
