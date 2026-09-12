"""Diagnostics support for the E-jídelníček integration.

Redacts the config entry's username and password via Home Assistant's own
``async_redact_data``. The ``Diner`` model (see ``models.py``) deliberately
carries no name, account number, payment symbol or email, so there is no
identity of that kind to leak here -- but the balance figures themselves are
still withheld: a diagnostics dump is routinely pasted into a public GitHub
issue, and a family's account balance is not needed to debug this
integration, so it is reported as redacted rather than as a real number.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import EjidelnicekConfigEntry

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EjidelnicekConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Includes the base URL, whether credentials are configured (a bool, never
    the values), the poll interval, each meal type's name and known-day
    count, the overall published date range, and the diner's debt/ordering
    flags -- but never the diner's balance or any field that could identify
    them.
    """
    coordinator = entry.runtime_data
    client = coordinator.client
    snapshot = coordinator.data
    canteen = snapshot.canteen
    diner = snapshot.diner

    all_dates = {date for meal_type in canteen.meal_types for date in meal_type.days}
    date_range = (
        {"first": min(all_dates).isoformat(), "last": max(all_dates).isoformat()}
        if all_dates
        else None
    )

    update_interval = coordinator.update_interval
    update_interval_hours = (
        update_interval.total_seconds() / 3600 if update_interval is not None else None
    )

    if diner is None:
        diner_diagnostics: dict[str, Any] = {"present": False}
    else:
        diner_diagnostics = {
            "present": True,
            "balance": REDACTED,
            "balance_meals": REDACTED,
            "balance_tuition": REDACTED,
            "in_debt": diner.in_debt,
            "ordering_disabled": diner.ordering_disabled,
        }

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "base_url": client.base_url,
        "has_credentials": client.has_credentials,
        "update_interval_hours": update_interval_hours,
        "canteen": {
            "meal_types": [
                {"name": meal_type.name, "day_count": len(meal_type.days)}
                for meal_type in canteen.meal_types
            ],
            "date_range": date_range,
            "allergen_legend_count": len(canteen.allergens),
            "diet_legend_count": len(canteen.diets),
        },
        "diner": diner_diagnostics,
    }
