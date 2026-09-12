"""Binary sensor platform for the E-jídelníček integration: the debt alert.

Credential-only: whether the diner is in debt is only known once logged in
(see ``Diner.in_debt``), so ``EjidelnicekDebtBinarySensor`` is only created
when ``coordinator.client.has_credentials`` is true. When the meal account
runs dry, the school silently stops issuing meals -- surfacing that as a
``problem`` binary sensor lets a parent build an automation on it instead of
discovering it at the till.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import EjidelnicekEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EjidelnicekConfigEntry, EjidelnicekCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EjidelnicekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the debt binary sensor for a credentialed config entry."""
    coordinator = entry.runtime_data
    if coordinator.client.has_credentials:
        async_add_entities([EjidelnicekDebtBinarySensor(coordinator, entry)])


class EjidelnicekDebtBinarySensor(EjidelnicekEntity, BinarySensorEntity):
    """Reports whether the diner's account is in debt. One per config entry."""

    _attr_translation_key = "debt"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: EjidelnicekCoordinator,
        entry: EjidelnicekConfigEntry,
    ) -> None:
        """Initialize the binary sensor for the config entry's diner."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_debt"

    @property
    def is_on(self) -> bool | None:
        """Return True if in debt, or None if diner data did not arrive."""
        diner = self.coordinator.data.diner
        if diner is None:
            return None
        return diner.in_debt
