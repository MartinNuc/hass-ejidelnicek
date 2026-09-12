"""The E-jídelníček integration (read-only Czech school canteen menus)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EjidelnicekClient
from .const import CONF_BASE_URL, PLATFORMS
from .coordinator import EjidelnicekCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import EjidelnicekConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: EjidelnicekConfigEntry) -> bool:
    """Set up E-jídelníček from a config entry."""
    client = EjidelnicekClient(
        async_get_clientsession(hass),
        entry.data[CONF_BASE_URL],
        entry.data.get(CONF_USERNAME),
        entry.data.get(CONF_PASSWORD),
    )
    coordinator = EjidelnicekCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: EjidelnicekConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: EjidelnicekConfigEntry) -> None:
    """Reload a config entry after its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
