<img src="brands/custom_integrations/ejidelnicek/logo.png" alt="E-jídelníček" height="72">

# E-jídelníček for Home Assistant

A Home Assistant custom integration that reads Czech school canteen menus
published by the **E-jídelníček** system, at any deployment of the form
`https://your-school.example.cz/ejidelnicek/`. It is generic across schools
-- it was validated against five real, independent E-jídelníček deployments
-- and read-only: it never places or cancels an order.

> **Not compatible** with `skolnijidelna.online` or `e-jidelnicek.cz`. Despite
> the similar name, those are different products with a different API; this
> integration does not support them.

## A note on the icon

HACS reads brand assets shipped inside the integration, at
`custom_components/ejidelnicek/brand/`, so the icon shows up in HACS as soon
as the integration is installed.

Home Assistant's own *Devices & Services* page is separate: it takes icons
from the central [home-assistant/brands](https://github.com/home-assistant/brands)
repository, so it shows a placeholder there until this artwork is accepted
upstream. That is expected and does not indicate a broken install. The same
assets, laid out the way that repository expects, plus submission
instructions, are in [`brands/`](brands/).

## What you get

For each **meal type** the canteen publishes (a school canteen typically has
one -- lunch -- but a kindergarten often publishes breakfast, a snack and
lunch, all under one login), the integration creates:

| Entity | Description |
| --- | --- |
| `calendar.<host>_<meal>_menu` | One all-day calendar event per known serving day |
| `sensor.<host>_<meal>_today` | Today's primary dish, or `unknown` if nothing is served today |
| `sensor.<host>_<meal>_next_serving_day` | The primary dish on the next known serving day (e.g. on a Friday, this already points at Monday) |
| `sensor.<host>_<meal>_soup_today` | Today's soup, or `unknown` if nothing is served today |
| `sensor.<host>_<meal>_soup_next_serving_day` | The soup on the next known serving day |

If you provide credentials, you additionally get, per meal type or account:

| Entity | Description |
| --- | --- |
| `sensor.<host>_<meal>_ordered_next_serving_day` | The label of the option you booked for the next serving day, or the literal string `none` |
| `sensor.<host>_balance` | The account balance, in CZK |
| `binary_sensor.<host>_debt` | `on` when the account is in debt (device class `problem`) |

`<host>` is the canteen's hostname, slugified (e.g. `your_school_example_cz`);
`<meal>` is the meal type's own name, slugified (e.g. `obed`).

### Attributes

Both the "today" and "next serving day" sensors carry the full menu for that
day as attributes:

- `date`, `weekday_label`
- `soup` (the first soup's name) and `soups` (all of them) — also available
  as a state of its own on the `_soup_*` sensors above, since Home Assistant
  shows entity states rather than attributes on device pages and cards
- `dessert`, `drink`
- `options` -- a list, each with `label`, `name`, `allergens`,
  `allergen_codes`, `diet`, `price`, `ordered`, `remaining`
- `options_count`
- `ordered_option` -- the label of the booked option, if any
- `is_blocked` -- true if the canteen has blocked ordering for that day
- `days_ahead` -- only on the "next serving day" sensors

Without credentials, `price` and `remaining` are always `None`. The public
menu payload reports both as `0`, and showing that verbatim would misread as
"this meal is free" or "sold out" -- so the integration deliberately hides
them rather than publish a wrong number.

## Installation

### HACS (recommended)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add this repository's URL, category **Integration**.
3. Search for "E-jídelníček" in HACS and install it.
4. Restart Home Assistant.

### Manual

1. Copy the `custom_components/ejidelnicek` folder from this repository into
   your Home Assistant config's `custom_components` folder.
2. Restart Home Assistant.

## Setup

Go to **Settings → Devices & services → Add integration**, search for
"E-jídelníček", and enter:

- **Canteen address** -- any of the following are accepted:
  - a bare host, e.g. `your-school.example.cz`
  - `https://your-school.example.cz/ejidelnicek/`
  - `https://your-school.example.cz/ejidelnicek/menu/`

  If you omit the scheme, `https` is tried first and `http` second, since a
  few real deployments are still http-only.
- **Username** / **Password** -- both optional. Leave both blank for
  public-menu-only access (no orders, no balance). If you enter one, you
  must enter both.

Each (school, account) pair becomes its own config entry, so two children at
the same school -- with two different logins -- are two separate, independent
entries, not a conflict.

### Some canteens publish nothing publicly

A few canteens, mostly kindergartens, don't put anything on the public menu
page at all -- one real deployment shows a single menu option literally named
*"Přihlásit"* ("Log in"). The entry is still created, but a Repairs issue in
Home Assistant tells you that credentials will likely fix it: remove the entry
and add it again with a username and password.

The issue is re-evaluated every time the entry loads, so it clears itself if
the canteen starts publishing, and it disappears when you remove the entry.

### Troubleshooting `unsupported_site`

This error means the address you entered does not look like an
E-jídelníček site at all. The most common cause is pointing this integration
at a *different* Czech canteen system that happens to have a similar name:
**`skolnijidelna.online`** and **`e-jidelnicek.cz`** are both unrelated
products this integration does not support. Double-check with your school
which system they actually use.

## Polling

The menu and order data are refreshed every **6 hours** by default; this is
configurable (down to a minimum of 1 hour) from the integration's **Configure**
button. Independently of polling, all "today"-based state re-renders at local
midnight, so "today" rolls over to the next day without waiting for the next
poll.

## Automation example

This automation notifies you every weekday evening with tomorrow's (or, on a
Friday, Monday's) lunch, using the day sensor's attributes directly -- no
template sensor needed:

```yaml
automation:
  - alias: "Tell me tomorrow's school lunch"
    trigger:
      - trigger: time
        at: "19:00:00"
    condition:
      - condition: time
        weekday: [mon, tue, wed, thu, fri]
    action:
      - action: notify.mobile_app_your_phone
        data:
          title: >-
            Lunch for {{ state_attr('sensor.your_school_example_cz_obed_next_serving_day', 'weekday_label') }}
          message: >-
            {{ states('sensor.your_school_example_cz_obed_next_serving_day') }}
            {%- set soup = state_attr('sensor.your_school_example_cz_obed_next_serving_day', 'soup') %}
            {%- if soup %} (soup: {{ soup }}){% endif %}
```

## Diagnostics

From the integration's device page, **Download diagnostics** produces a
redacted snapshot useful for bug reports: the base URL, whether credentials
are configured, the poll interval, each meal type's name and known-day count,
and the published date range. It never includes your username, password, or
account balance -- those are always redacted before the file is generated, so
it is safe to attach to a GitHub issue.

## Development

```bash
python -m venv .venv
.venv/bin/pip install --group dev
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check custom_components tests
.venv/bin/python -m ruff format --check custom_components tests
```

## Roadmap (phase 2, not implemented)

This release is strictly read-only. A planned phase 2 would add ordering and
cancelling meals -- for example, letting a chat-based automation pick
tomorrow's lunch option for you.

## License

See [LICENSE](LICENSE).
