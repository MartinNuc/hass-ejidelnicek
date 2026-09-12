"""Constants for the E-jídelníček integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ejidelnicek"

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]

CONF_BASE_URL = "base_url"

DEFAULT_UPDATE_INTERVAL_HOURS = 6
MIN_UPDATE_INTERVAL_HOURS = 1
CONF_UPDATE_INTERVAL_HOURS = "update_interval_hours"

MANUFACTURER = "LÁF Electronics"
MODEL = "E-jídelníček"
