# E-jídelníček Home Assistant integration — design

- **Date:** 2026-09-12
- **Status:** approved design, ready for implementation planning
- **Repo:** `git@github.com:MartinNuc/hass-ejidelnicek.git`
- **Integration domain:** `ejidelnicek`

## 1. Purpose

Expose Czech school canteen menus from the **E-jídelníček** system
(`e-jidelnicek.eu`, by LÁF Electronics) to Home Assistant, so a household can
see what lunch is being served and automate around it.

The integration is **generic across schools**: nothing about any one canteen is
hardcoded. It is validated against five independent deployments.

### Phase 1 (this spec) — read only

Publish the menu, and — when credentials are supplied — the authoritative order
status and account balance. No writes of any kind.

### Phase 2 (later, explicitly out of scope)

Place and cancel orders, enabling automations such as picking tomorrow's lunch
over Telegram. Phase 1 deliberately captures the identifiers phase 2 needs
(`strava_id`, menu key, `db_id`, `order_day_offset`) so that phase 2 is additive.

## 2. Non-goals

- No ordering, cancelling, or "burza" (meal exchange) writes.
- No Telegram- or notifier-specific code. The integration exposes data; automations live in the user's own config.
- No support for the unrelated systems `skolnijidelna.online` or `e-jidelnicek.cz`. They are different products that will never parse; they must fail with a clear message.
- No multi-child (parent) account selection. Fields are captured, entities are not built.
- No HA core upstreaming. HACS custom integration only. (See §4.)

## 3. Verified upstream behaviour

Everything here was confirmed live on 2026-09-12, not inferred. This section is
the contract the implementation codes against.

### 3.1 Deployment shape

Each canteen is its own host serving the app under a common path:

```
https://<host>/ejidelnicek/
```

Hosts vary far more than the paths do. The official directory
(`e-jidelnicek.eu/main/down.php`, region → city → canteen) resolves canteen IDs
to base URLs, and those include plain `http`, non-standard ports, and even a LAN
address (`http://192.168.10.233/ejidelnicek` for ZŠ Korunovační). **This is why
setup takes a URL rather than offering a built-in school picker** — a picker
would confidently hand out unreachable addresses.

### 3.2 The menu payload

Both the public page and the authenticated pages embed the whole menu as a JSON
argument to an inline JavaScript call:

```js
ejidelnicek.setJidelnicek({"dietyMap":{...},"alergenyMap":{...},"stravaMap":{...},"denSet":{...}});
```

Structure:

| Path | Meaning |
| --- | --- |
| `alergenyMap` | code → allergen name (28 entries) |
| `dietyMap` | code → diet note (3 entries) |
| `denSet` | date → human label; the set of published days |
| `stravaMap` | index → meal type |
| `stravaMap[i].id` | **per-school** numeric meal-type id (seen: 1, 2, 3) |
| `stravaMap[i].nazev` | meal type name (`"Oběd"`, `"Oběd menu"`, `"Mš celý den"`) |
| `stravaMap[i].posunDne` | ordering lead time in days (seen: 0, 1, 2) |
| `stravaMap[i].denMap` | ISO date → day |
| `…denMap[d].polevka[]` | soups; each `{polevka, alerg}`. **May be empty.** |
| `…denMap[d].zakusek` / `.napoj` | dessert / drink. **May be `""`.** |
| `…denMap[d].barva` | `"B"` = blocked; `"A"` = ordered; `null` = neither |
| `…denMap[d].menuMap` | option key → option |
| `…menuMap[k].nazev` | dish name |
| `…menuMap[k].dMenu` | display label (`"1"`, `"2"`, `"D"`, `"B"`) |
| `…menuMap[k].alerg` | allergen codes, **digit-wise** (see below) |
| `…menuMap[k].objednavka` | ordered count — authoritative only via AJAX (§3.4) |
| `…menuMap[k].cena` | price; `"0.00"` in public view |
| `…menuMap[k].zbyva` | portions left; `-1` = untracked, `0` in public view |
| `…menuMap[k].dbId` | option id (needed for phase 2 ordering) |
| `…menuMap[k].isFirst` | marks the primary option |

**Allergen codes are concatenated base-36 characters, not integers.** Each
character is one code: `'1'`-`'9'` are codes 1-9, `'A'`-`'S'` are codes 10-28.
So `alerg: "17"` means codes `1` and `7`, not `17` — while `alerg: "1F"` means
codes `1` and `15`. Confirmed against the site's own `alergZobr` rendering:
`"17"` → `(obsahuje alergeny:1,7)`, `"1379AC"` → `1,3,7,9,10,12`, and `"1F"` →
`1,1a` where `alergenyMap["15"]` is `"1a - Obilniny obsahující lepek - pšenice."`.

Two traps live here and both are allergy-safety relevant. A naive `int()` of the
whole string yields the wrong allergen — but so does a plain digit-wise split,
which silently drops every letter-coded allergen: mustard (10), sesame (11),
sulfites (12), lupin (13), molluscs (14) and all the gluten and nut sub-codes
(15-28). Decode with `int(ch, 36)` and expose the decoded numeric code, so
`allergen_codes` matches both the legend keys and what the site shows a parent.
A code decoding to a value absent from the legend is kept without a name — real
payloads contain `"17T"`, which the site itself renders with a trailing empty
entry. This must be covered by a test against real payload data, not only a
synthetic legend: a synthetic-only test is what allowed the digit-wise bug
through during implementation.

Extraction requires a **balanced-brace scan** that respects string literals and
escapes. A regex to the final `}` is wrong, because dish names contain braces
and the payload is followed by more JavaScript.

### 3.3 Not every canteen publishes publicly

Verified on `msjesenice.e-jidelnicek.eu` (a kindergarten): all 35 published days
have empty `polevka`, empty `zakusek`, empty `napoj`, and a single option whose
`nazev` is literally `"Přihlásit"` ("Log in"). The public view is a placeholder;
the real menu is behind login.

Consequences: the parser must tolerate empty collections everywhere, and setup
should warn when a parse succeeds but every day is devoid of content.

### 3.4 Authentication, and which source is authoritative

Login is plain Spring Security form login:

```
POST {base}/logincheck    j_username=…&j_password=…
```

Session is a `JSESSIONID` cookie; success redirects to `/visitor/index?firstLogin=1`.

Read sources compared on one account (all days actually had a standing order for
Menu 1):

| Source | Days returned | Order data |
| --- | --- | --- |
| `GET /menu/` | all published days | none (public view; `objednavka` always 0) |
| `GET /visitor/index` | all published days | **only for the one day its UI has selected**; every other day is a placeholder with `objednavka=0`, `cena=0.00`, `barva=null` |
| `GET /ajax/get-jidelnicek?datum=<ISO>` | exactly one day | **authoritative** — real `objednavka`, `cena`, `zbyva`, `barva` |

**`/visitor/index` must not be trusted for order status.** Its placeholder days
are indistinguishable from "not ordered", so an integration built on it would
report "lunch not picked" every day while lunch was in fact booked. The real web
UI avoids this by re-fetching each day over AJAX as the user navigates.

`datum` must be a published serving day; other values return zero days, and an
absent `datum` returns HTTP 400.

### 3.5 The diner object

Every AJAX response also carries `stravnik`, which supplies personal data as
clean JSON — no HTML scraping needed:

| Field | Use |
| --- | --- |
| `konto` | balance, Czech decimal comma (`"297,00"`) |
| `kontoStravne` / `kontoSkolne` | meal / tuition sub-accounts |
| `dluh`, `dluhStravne`, `dluhSkolne` | debt booleans |
| `bezObjednavani` | ordering disabled for this diner (phase 2) |
| `deti`, `pocetDeti`, `rodicovskyPristup` | parent access with several children (out of scope) |
| `jmeno`, `cislo`, `vs`, `loginEmail` | personal identifiers — see §10 |

## 4. Architecture

```
                    ┌──────────────┐
   HTTP ───────────►│   api.py     │  all I/O, session, login, retries
                    └──────┬───────┘
                           │ raw html / json
                    ┌──────▼───────┐
                    │  parser.py   │  PURE. no I/O, no HA imports
                    └──────┬───────┘
                           │ frozen dataclasses (models.py)
                    ┌──────▼───────┐
                    │coordinator.py│  polling, midnight rollover, auth errors
                    └──────┬───────┘
                           │ Snapshot
              ┌────────────┴────────────┐
        ┌─────▼─────┐            ┌──────▼──────┐
        │calendar.py│            │  sensor.py  │  binary_sensor.py
        └───────────┘            └─────────────┘
```

The load-bearing boundary is **`parser.py` being pure**: HTML or JSON text in,
frozen dataclasses out, with no network, no clock, and no `homeassistant`
imports. That makes the five real-world payloads offline fixtures, so all the
gnarly variation (empty soups, digit-wise allergens, per-school ids, placeholder
kindergartens) is tested without touching the network — and it keeps the door
open to extracting a standalone PyPI package later, should upstreaming to HA core
ever be wanted, as a mechanical move.

## 5. Data model (`models.py`)

Frozen dataclasses, so `always_update=False` on the coordinator works by value
equality and entities don't churn on unchanged data.

```python
@dataclass(frozen=True)
class Dish:
    name: str
    allergens: tuple[str, ...]        # resolved names
    allergen_codes: tuple[str, ...]

@dataclass(frozen=True)
class MenuOption:
    key: str                          # menuMap key; phase 2 order target
    label: str                        # dMenu: "1" | "2" | "D" | "B"
    name: str
    allergens: tuple[str, ...]
    allergen_codes: tuple[str, ...]
    diet: str | None
    price: Decimal | None             # None in public view, never a bogus 0
    ordered: int                      # 0 unless authoritative source used
    remaining: int | None             # None when untracked (-1) or public
    db_id: int
    is_primary: bool                  # isFirst

@dataclass(frozen=True)
class DayMenu:
    date: datetime.date
    weekday_label: str                # "pondělí 14.9.2026"
    soups: tuple[Dish, ...]           # may be empty
    dessert: str | None
    drink: str | None
    options: tuple[MenuOption, ...]
    is_blocked: bool                  # barva == "B"
    @property
    def primary(self) -> MenuOption | None
    @property
    def ordered_option(self) -> MenuOption | None

@dataclass(frozen=True)
class MealType:
    index: str
    strava_id: int                    # per-school
    name: str
    order_day_offset: int             # posunDne
    days: Mapping[datetime.date, DayMenu]

@dataclass(frozen=True)
class Diner:                          # from `stravnik`
    balance: Decimal | None
    balance_meals: Decimal | None
    balance_tuition: Decimal | None
    in_debt: bool | None
    ordering_disabled: bool | None

@dataclass(frozen=True)
class Canteen:
    allergens: Mapping[str, str]
    diets: Mapping[str, str]
    meal_types: tuple[MealType, ...]

@dataclass(frozen=True)
class Snapshot:                       # coordinator payload
    canteen: Canteen
    diner: Diner | None               # None when anonymous
    fetched_at: datetime.datetime
```

`Diner` intentionally omits `jmeno`, `cislo`, `vs` and `loginEmail`. The
integration has no use for them, and not modelling them means they cannot leak
into attributes, diagnostics or logs (§10).

## 6. Transport and authentication (`api.py`)

All requests go through Home Assistant's shared `aiohttp` session.

**URL normalisation.** Accept a bare host, `…/ejidelnicek/`, or
`…/ejidelnicek/menu/`. Add a scheme when missing, trying `https` first and
falling back to `http` (several canteens are http-only). Reduce to the base
`<origin>/ejidelnicek/`.

**Anonymous refresh** — 1 request:

1. `GET {base}menu/` → parse → `Canteen`, `diner=None`.

**Authenticated refresh** — 3 requests, by design:

1. `GET {base}menu/` → full menu text for every published day.
2. For *today* and the *next serving day* only:
   `GET {base}ajax/get-jidelnicek?datum=<ISO>` → authoritative option data for
   that day, merged over the day from step 1; last response also yields `Diner`.

Order status for all days was considered and rejected: it costs one request per
published day (10–35), and some canteens are a single PC on a school LAN. Only
two days are needed for the intended automations. If the calendar should ever
mark ordered meals on every day, that becomes an opt-in option, off by default.

**Login** is attempted lazily — on first authenticated need and again after a
session expires. Expiry appears as a redirect to the login page or a 400/302 from
the AJAX call; the client then re-logs-in **once** and retries **once**. Success
is detected *positively* (payload present / login form absent) rather than by
matching a failure URL, so no bad-password probe against a live account is
needed. A failed login raises `InvalidAuth`, which the coordinator turns into
`ConfigEntryAuthFailed` so HA opens its reauth dialog.

Values parse defensively: Czech decimal commas (`"297,00"` → `Decimal("297.00")`),
`zbyva == -1` → `None`, `cena == "0.00"` in a public payload → `None`.

## 7. Coordinator (`coordinator.py`)

One `DataUpdateCoordinator[Snapshot]` per config entry, so a single fetch feeds
every entity. `always_update=False`, relying on dataclass equality.

**Interval: 6 hours**, adjustable via the options flow (minimum 1 hour). The
original request was a daily pull; 6 hours is the deliberate deviation because a
refresh is ~25 KB, canteens do amend menus mid-week, and on a 24-hour cycle a
single failed request leaves the data stale for a full day.

**Midnight rollover.** "Today" and "next serving day" must change at local
midnight even when no fetch happens then. Entities therefore also subscribe to
`async_track_time_change(hour=0, minute=0, second=0)` and recompute from the
cached snapshot. Without this, `_today` keeps showing yesterday's lunch until the
next poll lands — up to six hours late.

Failures raise `UpdateFailed` (entities go unavailable) except authentication
failures, which raise `ConfigEntryAuthFailed`.

## 8. Entities

One HA device per config entry (the canteen). Entities use
`has_entity_name = True` with translation keys. `<meal>` is the slugified meal
type name, iterated from `stravaMap`, so multi-meal canteens work.

Always:

| Entity | State | Notes |
| --- | --- | --- |
| `calendar.<slug>_<meal>` | current/next event | one all-day event per serving day |
| `sensor.<slug>_<meal>_today` | primary dish, else `unknown` | full day in attributes |
| `sensor.<slug>_<meal>_next_serving_day` | primary dish | adds `date`, `days_ahead` |

Only with credentials:

| Entity | State | Notes |
| --- | --- | --- |
| `sensor.<slug>_<meal>_ordered_next_serving_day` | option label, else `none` | authoritative (§3.4) |
| `sensor.<slug>_balance` | `Decimal` | `device_class: monetary`, CZK, entry-level |
| `binary_sensor.<slug>_debt` | `dluh` | `device_class: problem` |

There is no `_tomorrow` sensor. On a Friday, "tomorrow" is a Saturday with no
menu, which makes the entity useless exactly when it matters;
`_next_serving_day` carries a `date` attribute and points at Monday instead.
There is likewise no `_ordered_today` — that is already an attribute of `_today`.

**Sensor attributes** (both day sensors): `date`, `weekday_label`, `soup`,
`soups`, `dessert`, `drink`, `options` (each with `label`, `name`, `allergens`,
`allergen_codes`, `diet`, `price`, `ordered`, `remaining`), `options_count`,
`ordered_option`, `is_blocked`; plus `days_ahead` on `_next_serving_day`.
`options_count` is included because it is free and lets an automation tell a real
choice from a single-option day.

State strings are clamped to HA's 255-character limit.

**Calendar.** All-day events: `start = day`, `end = day + 1` (exclusive), as HA
requires, returned in chronological order from `async_get_events`, with all-day
ordering evaluated in HA local time via `homeassistant.util.dt`. Summary is the
primary dish; description lists soup, every option with its label, dessert,
drink and allergens. Blocked days are marked in the summary.

## 9. Config flow, options, errors

**Single `user` step:** URL (required), username and password (both optional,
labelled "leave blank for public menu only"). Validation performs a real fetch
and parse, and the created entry is titled with the canteen's meal-type name and
host.

**`unique_id` = `<normalised base url>|<username or "public">`.** Including the
username means two children at the same school are two valid entries rather than
a duplicate-abort.

**Reauth** via `async_step_reauth` / `async_step_reauth_confirm`, using
`_get_reauth_entry()`, `_abort_if_unique_id_mismatch("wrong_account")` and
`async_update_reload_and_abort(...)`.

**Options flow:** update interval only.

Errors are distinguished because the remedies differ:

| Condition | Error key | Message intent |
| --- | --- | --- |
| host unreachable, timeout, TLS failure | `cannot_connect` | check URL/network |
| login rejected | `invalid_auth` | check username/password |
| page loads, no `setJidelnicek` payload | `unsupported_site` | "this is not an E-jídelníček canteen" — names `skolnijidelna.online` / `e-jidelnicek.cz` as different systems |
| parses, but every day empty | warning, not an error | "this canteen does not publish its menu publicly; add credentials" |

`unsupported_site` matters: without it, pointing the integration at a
superficially similar Czech canteen site looks like a bug in the integration.

## 10. Privacy and secret handling

The user's explicit requirement was that no private information be published.

- Credentials live only in HA's config entry store. They appear in no file in this repo, and are passed to probe scripts via environment variables only.
- `.gitignore` blocks `.env*`, `credentials*`, `secrets.yaml`, and `auth_*.html` / `auth_*.json` captures of authenticated pages (which contain a diner's name, account number and balance).
- **Fixtures for authenticated behaviour are synthetic**: built by taking a public payload and injecting `objednavka`, `cena`, `barva` and a `stravnik` block with invented values. No captured personal data is committed.
- Public-view fixtures carry no personal fields (`objednavka` is always `0`, `cena` `"0.00"`), and are trimmed to a few days.
- `README` examples use a placeholder host, not the author's school, so the repo does not advertise which school the family attends.
- `Diner` models only balances and flags — never `jmeno`, `cislo`, `vs`, `loginEmail` (§5).
- Credentials must never be logged. Diagnostics output is redacted.
- CI runs a secret scan so a future accidental credential commit fails the build.

## 11. Testing

Test-driven, parser first, and **entirely offline**.

- **Parser unit tests** over fixtures from five real deployments — `letohrad.zs-stross.cz`, `stross.zs-stross.cz`, `jidelna.betlemska.cz`, `jidelnajakutska.sjp10.cz`, `msjesenice.e-jidelnicek.eu` — covering: per-school `strava_id` (1/2/3), option label variants (`1`,`2`,`D`,`B`), `posunDne` variants (0/1/2), empty soups/dessert/drink, and the placeholder kindergarten.
- A dedicated test that `alerg: "17"` resolves to codes `1` and `7` (§3.2).
- Balanced-brace extraction tests: braces inside dish names, trailing JavaScript, and a page with no payload → `unsupported_site`.
- Czech decimal comma parsing; `zbyva == -1` → `None`.
- **Transport tests** with mocked HTTP: anonymous 1-request path; authenticated 3-request path; AJAX data overriding page placeholders; session expiry → one re-login and one retry; login failure → `InvalidAuth`.
- **Config flow tests**: success anonymous, success authenticated, each error key, `unique_id` collision, two-children case, reauth.
- **Entity tests** via `pytest-homeassistant-custom-component`: next-serving-day selection across a weekend, midnight rollover, all-day calendar event boundaries and ordering, unknown states on non-serving days, absence of credential-only entities when anonymous.

CI (GitHub Actions): `hassfest`, HACS validation, `ruff`, `mypy`, `pytest`, secret scan.

## 12. Repository layout

```
custom_components/ejidelnicek/
  __init__.py          async_setup_entry, typed ConfigEntry, runtime_data
  api.py               HTTP, login, session, URL normalisation
  parser.py            PURE payload → models
  models.py            frozen dataclasses
  coordinator.py       DataUpdateCoordinator[Snapshot]
  config_flow.py       user / reauth / options
  calendar.py  sensor.py  binary_sensor.py
  const.py  diagnostics.py
  manifest.json  strings.json  translations/{en,cs}.json
tests/
  fixtures/            real public payloads + synthetic authenticated one
  test_parser.py  test_api.py  test_config_flow.py
  test_sensor.py  test_calendar.py  test_binary_sensor.py
.github/workflows/{validate.yml,test.yml}
hacs.json  pyproject.toml  README.md  LICENSE  .gitignore
docs/superpowers/specs/
```

`manifest.json`: `domain: ejidelnicek`, `config_flow: true`,
`iot_class: cloud_polling`, `integration_type: service`, no `requirements`
(HA already ships `aiohttp`). MIT licence. `en` and `cs` translations, since the
menu content is Czech.

## 13. Phase 2 readiness

Captured now, unused in phase 1: `MealType.strava_id`, `MenuOption.key`,
`MenuOption.db_id`, `MealType.order_day_offset`, `Diner.ordering_disabled`.

Phase 2 will add `api.async_set_order(date, meal_type, option, count)` against
`ajax/menu-update?datum=&stravaId=&menuId=&vydejnaId=&burza=&ordered=` (verified
to exist, deliberately never called during research), exposed as
`ejidelnicek.order_meal` / `cancel_meal` services, with `order_day_offset`
enforced as the cut-off. No part of phase 1 needs to change for this.
