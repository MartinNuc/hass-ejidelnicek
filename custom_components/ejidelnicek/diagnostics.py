"""Diagnostics support for the E-jídelníček integration.

Redacts the config entry's username and password via Home Assistant's own
``async_redact_data``. The ``Diner`` model (see ``models.py``) deliberately
carries no name, account number, payment symbol or email, so there is no
identity of that kind to leak here -- but the balance figures themselves are
still withheld: a diagnostics dump is routinely pasted into a public GitHub
issue, and a family's account balance is not needed to debug this
integration, so it is reported as redacted rather than as a real number.

The config entry itself is deliberately NOT dumped via ``entry.as_dict()``:
that includes a top-level ``unique_id``, which ``config_flow.py`` builds as
``f"{base_url}|{username}"`` specifically so two diners at one school can
each get their own entry -- a decision about entry identity, never reviewed
for what belongs in a diagnostics dump. Passing that whole dict through
``async_redact_data`` would NOT catch it either: redaction there matches by
*key* (``username``/``password``), not by scanning string values, so the
username would still leak in cleartext inside ``unique_id``. ``entry_id`` is
dropped for the same reason (one more identifier that helps nothing). Instead
a curated allowlist is returned below -- the same approach already used for
``canteen`` and ``diner`` -- so a future field HA adds to ``ConfigEntry``
cannot silently reappear here unreviewed.
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

    Includes the base URL, when the snapshot was fetched, whether credentials
    are configured (a bool, never the values), the poll interval, each meal
    type's name and known-day count, the overall published date range, and the
    diner's debt/ordering flags -- but never the diner's balance, the entry's
    ``unique_id`` or ``entry_id``, or any other field that could identify the
    diner.
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

    entry_diagnostics = {
        "title": entry.title,
        "version": entry.version,
        "source": entry.source,
        "options": dict(entry.options),
        "data": async_redact_data(dict(entry.data), TO_REDACT),
    }

    return {
        "entry": entry_diagnostics,
        "base_url": client.base_url,
        "fetched_at": snapshot.fetched_at.isoformat(),
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
