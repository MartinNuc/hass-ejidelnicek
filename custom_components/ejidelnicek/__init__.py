"""The E-jídelníček integration (read-only Czech school canteen menus)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import issue_registry as ir

from .api import EjidelnicekClient, async_new_session, menu_is_empty
from .const import CONF_BASE_URL, DOMAIN, PLATFORMS
from .coordinator import EjidelnicekCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import EjidelnicekConfigEntry


def _empty_menu_issue_id(entry: EjidelnicekConfigEntry) -> str:
    """Return the Repairs issue id for one entry.

    Keyed on ``entry_id``, not on ``unique_id``: the unique_id encodes the
    username, so re-adding the same canteen with credentials would orphan an
    issue raised under the anonymous unique_id, leaving a warning in Settings
    that nothing could ever clear.
    """
    return f"empty_public_menu_{entry.entry_id}"


def _async_update_empty_menu_issue(
    hass: HomeAssistant, entry: EjidelnicekConfigEntry, coordinator: EjidelnicekCoordinator
) -> None:
    """Raise or clear the "this canteen publishes nothing publicly" warning.

    Evaluated here, on every setup, rather than once in the config flow: an
    issue created during the wizard is never re-examined, so it would outlive
    the condition -- surviving the canteen starting to publish, and (because
    the wizard's issue id was derived from the unique_id) being orphaned
    outright if the user re-added the entry with credentials. Deciding it from
    the current snapshot means a reload is all it takes to clear.
    """
    issue_id = _empty_menu_issue_id(entry)
    if coordinator.client.has_credentials or not menu_is_empty(coordinator.data.canteen):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="empty_public_menu",
        translation_placeholders={
            "host": urlparse(entry.data[CONF_BASE_URL]).hostname or entry.title
        },
    )


async def async_setup_entry(hass: HomeAssistant, entry: EjidelnicekConfigEntry) -> bool:
    """Set up E-jídelníček from a config entry."""
    # A session of this entry's own, never the instance-wide shared one --
    # see ``async_new_session`` for why that distinction is load-bearing.
    client = EjidelnicekClient(
        async_new_session(hass),
        entry.data[CONF_BASE_URL],
        entry.data.get(CONF_USERNAME),
        entry.data.get(CONF_PASSWORD),
    )
    coordinator = EjidelnicekCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    _async_update_empty_menu_issue(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: EjidelnicekConfigEntry) -> bool:
    """Unload a config entry, taking its Repairs issue down with it."""
    ir.async_delete_issue(hass, DOMAIN, _empty_menu_issue_id(entry))
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: EjidelnicekConfigEntry) -> None:
    """Reload a config entry after its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
