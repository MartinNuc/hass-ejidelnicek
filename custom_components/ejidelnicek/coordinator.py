"""Data update coordinator for the E-jídelníček integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EjidelnicekError, InvalidAuth
from .const import (
    CONF_UPDATE_INTERVAL_HOURS,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    MIN_UPDATE_INTERVAL_HOURS,
)
from .models import Snapshot

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .api import EjidelnicekClient

_LOGGER = logging.getLogger(__name__)

type EjidelnicekConfigEntry = ConfigEntry[EjidelnicekCoordinator]


class EjidelnicekCoordinator(DataUpdateCoordinator[Snapshot]):
    """Fetch and cache a Snapshot for one E-jídelníček config entry."""

    config_entry: EjidelnicekConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: EjidelnicekConfigEntry,
        client: EjidelnicekClient,
    ) -> None:
        """Initialize the coordinator."""
        hours = entry.options.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)
        hours = max(hours, MIN_UPDATE_INTERVAL_HOURS)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(hours=hours),
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> Snapshot:
        """Fetch a fresh Snapshot, translating client errors for HA."""
        try:
            return await self.client.async_fetch_snapshot(today=dt_util.now().date())
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EjidelnicekError as err:
            raise UpdateFailed(str(err)) from err
