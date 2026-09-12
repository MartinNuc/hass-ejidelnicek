"""Shared base entity for the E-jídelníček integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import EjidelnicekCoordinator

if TYPE_CHECKING:
    from .coordinator import EjidelnicekConfigEntry


class EjidelnicekEntity(CoordinatorEntity[EjidelnicekCoordinator]):
    """Base entity sharing device info and a midnight rollover trigger.

    Subclasses must compute their state and attributes from
    ``self.coordinator.data`` and the current time on every access -- never
    cache a day into ``_attr_*`` -- so the midnight state write below is
    enough to roll "today" over without waiting for the next poll.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EjidelnicekCoordinator,
        entry: EjidelnicekConfigEntry,
    ) -> None:
        """Initialize the entity with device info tied to the config entry."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=coordinator.client.base_url,
        )

    async def async_added_to_hass(self) -> None:
        """Register a midnight callback so day-based state rolls over."""
        await super().async_added_to_hass()

        async def _midnight(_now) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_change(self.hass, _midnight, hour=0, minute=0, second=0)
        )
