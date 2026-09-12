"""Shared test fixtures."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.const import Platform

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of this custom integration in every test."""
    return


# ``const.PLATFORMS`` already lists every platform this integration will
# eventually ship -- that constant stays production-accurate -- but
# forwarding a config entry to a platform module that is not on disk yet
# raises ModuleNotFoundError. So this list tracks only the platforms that
# genuinely exist so far: Task 11 added ``binary_sensor.py`` (widening this
# from ``[Platform.SENSOR]``), Task 12 will append ``Platform.CALENDAR``, and
# once this list equals ``const.PLATFORMS`` this fixture (and its patch)
# should be deleted entirely.
_EXISTING_PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


@pytest.fixture(autouse=True)
def _only_forward_to_existing_platforms():
    """Limit config entry setup/unload to platforms that actually exist on disk."""
    with patch("custom_components.ejidelnicek.PLATFORMS", _EXISTING_PLATFORMS):
        yield
