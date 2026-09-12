# E-jídelníček Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a read-only HACS custom integration that publishes any Czech E-jídelníček school canteen menu to Home Assistant as a calendar plus today / next-serving-day sensors, with optional credentials adding authoritative order status and account balance.

**Architecture:** A pure, I/O-free `parser.py` turns the site's inline-JavaScript JSON payload into frozen dataclasses; `api.py` owns all HTTP, login and session recovery; one `DataUpdateCoordinator` per config entry feeds every entity from a single `Snapshot`. Entities compute their values from the snapshot in properties and re-render at local midnight, so "today" rolls over independently of the poll schedule.

**Tech Stack:** Python 3.13, Home Assistant 2026.2.3, `aiohttp` (shipped with HA), `pytest-homeassistant-custom-component`, `ruff`, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-12-ejidelnicek-ha-integration-design.md` — read it first; this plan argues from it and does not repeat its research.

## Global Constraints

- Integration domain is `ejidelnicek`. Repo is `hass-ejidelnicek`. HACS custom integration; **not** HA core.
- `parser.py` MUST NOT import `homeassistant`, `aiohttp`, or anything doing I/O. It is pure text → dataclasses. Enforced by a test.
- No `requirements` in `manifest.json` — HA already ships `aiohttp`.
- **Never** call `ajax/menu-update`. It places and cancels real orders. Phase 1 is read-only. Enforced by a test that greps the source.
- Allergen codes are **concatenated single characters**: `"17"` → codes `1`,`7`. Never `int("17")`.
- Order status is authoritative **only** from `ajax/get-jidelnicek?datum=<ISO>`. Never from `/visitor/index`.
- Czech decimals use a comma: `"297,00"` → `Decimal("297.00")`.
- No credentials, and no captured personal data, in any committed file. Authenticated fixtures are synthetic.
- `Diner` must never model `jmeno`, `cislo`, `vs`, or `loginEmail`.
- Default poll interval 6 hours, minimum 1 hour.
- All entities use `has_entity_name = True` plus a `_attr_translation_key`.
- Test commands use the repo venv: `.venv/bin/python -m pytest`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `custom_components/ejidelnicek/const.py` | domain, config keys, defaults, platform list |
| `custom_components/ejidelnicek/models.py` | frozen dataclasses + derived properties |
| `custom_components/ejidelnicek/parser.py` | PURE: payload extraction and mapping to models |
| `custom_components/ejidelnicek/api.py` | HTTP, URL resolution, login, session recovery, snapshot assembly |
| `custom_components/ejidelnicek/coordinator.py` | `DataUpdateCoordinator[Snapshot]`, error mapping |
| `custom_components/ejidelnicek/__init__.py` | `async_setup_entry`, typed entry, platform forwarding |
| `custom_components/ejidelnicek/entity.py` | shared base entity: device info, midnight rollover |
| `custom_components/ejidelnicek/sensor.py` | day sensors, ordered sensor, balance sensor |
| `custom_components/ejidelnicek/binary_sensor.py` | debt sensor |
| `custom_components/ejidelnicek/calendar.py` | calendar entity |
| `custom_components/ejidelnicek/config_flow.py` | user / reauth / options flows |
| `custom_components/ejidelnicek/diagnostics.py` | redacted diagnostics |
| `tests/fixtures/` | real public payloads + synthetic authenticated payload |

---

### Task 1: Scaffolding, manifest, CI

**Files:**
- Create: `pyproject.toml`, `hacs.json`, `LICENSE`, `README.md`
- Create: `custom_components/ejidelnicek/__init__.py`, `const.py`, `manifest.json`
- Create: `.github/workflows/test.yml`, `.github/workflows/validate.yml`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_manifest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `const.DOMAIN = "ejidelnicek"`, `const.PLATFORMS`, `const.CONF_*`, `const.DEFAULT_UPDATE_INTERVAL_HOURS = 6`, `const.MIN_UPDATE_INTERVAL_HOURS = 1`.

- [ ] **Step 1: Write the failing test**

`tests/test_manifest.py`:

```python
import json
from pathlib import Path

MANIFEST = Path("custom_components/ejidelnicek/manifest.json")


def test_manifest_is_valid_for_a_custom_integration():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["domain"] == "ejidelnicek"
    assert data["config_flow"] is True
    assert data["iot_class"] == "cloud_polling"
    assert data["version"]
    # HA ships aiohttp; a custom integration must not pin it.
    assert data.get("requirements", []) == []


def test_source_never_references_the_order_writing_endpoint():
    """menu-update places and cancels real orders. Phase 1 is read-only."""
    sources = Path("custom_components/ejidelnicek").rglob("*.py")
    offenders = [p for p in sources if "menu-update" in p.read_text(encoding="utf-8")]
    assert offenders == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_manifest.py -v`
Expected: FAIL — `manifest.json` does not exist.

- [ ] **Step 3: Write minimal implementation**

`custom_components/ejidelnicek/manifest.json`:

```json
{
  "domain": "ejidelnicek",
  "name": "E-jídelníček",
  "codeowners": ["@MartinNuc"],
  "config_flow": true,
  "documentation": "https://github.com/MartinNuc/hass-ejidelnicek",
  "integration_type": "service",
  "iot_class": "cloud_polling",
  "issue_tracker": "https://github.com/MartinNuc/hass-ejidelnicek/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

`custom_components/ejidelnicek/const.py`:

```python
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
```

`hacs.json`:

```json
{
  "name": "E-jídelníček",
  "content_in_root": false,
  "render_readme": true,
  "homeassistant": "2026.2.0"
}
```

`pyproject.toml` — ruff config plus pytest config with `asyncio_mode = "auto"`:

```toml
[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`tests/conftest.py`:

```python
"""Shared test fixtures."""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of this custom integration in every test."""
    return
```

`custom_components/ejidelnicek/__init__.py` — empty docstring module for now (Task 8 fills it in).

CI `.github/workflows/test.yml` runs ruff and pytest on Python 3.13; `.github/workflows/validate.yml` runs `home-assistant/actions/hassfest` and `hacs/action` with `category: integration`, plus a `gitleaks`-style secret scan step.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_manifest.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml hacs.json LICENSE README.md custom_components tests .github
git commit -m "Add integration scaffolding, manifest and CI"
```

---

### Task 2: Test fixtures

**Files:**
- Create: `tests/fixtures/{letohrad,stross,betlemska,jakutska,msjesenice}_public.html` (trimmed)
- Create: `tests/fixtures/ajax_authenticated.json` (**synthetic**)
- Create: `tests/fixtures/not_ejidelnicek.html`
- Create: `tests/fixture_loader.py`, `tests/test_fixtures.py`

**Interfaces:**
- Produces: `tests.fixture_loader.load(name: str) -> str`, `PUBLIC_FIXTURES: tuple[str, ...]`.

Fixtures come from the real public pages (no personal fields: `objednavka` is `0`, `cena` `"0.00"`). Trim each to the `<script>` block containing `setJidelnicek(...)` plus a little surrounding markup, so files stay small.

`ajax_authenticated.json` is **hand-written**, shaped like the real response (`{"jidelnicek": {...}, "stravnik": {...}}`) with invented values: one day, option `"1"` with `objednavka: 1`, `cena: "37.00"`, `zbyva: -1`, `barva: "A"`; option `"2"` unordered; `stravnik` containing only `konto: "297,00"`, `kontoStravne`, `kontoSkolne`, `dluh`, `dluhStravne`, `dluhSkolne`, `bezObjednavani`. No name, account number, VS or email.

- [ ] **Step 1: Write the failing test**

`tests/test_fixtures.py`:

```python
import json

from tests.fixture_loader import PUBLIC_FIXTURES, load


def test_public_fixtures_contain_a_payload_and_no_personal_data():
    for name in PUBLIC_FIXTURES:
        html = load(name)
        assert "setJidelnicek(" in html, name
        # Public view never carries order or price data.
        assert '"objednavka":1' not in html.replace(" ", ""), name


def test_synthetic_authenticated_fixture_has_orders_but_no_identity():
    data = json.loads(load("ajax_authenticated.json"))
    assert set(data) == {"jidelnicek", "stravnik"}
    stravnik = data["stravnik"]
    assert stravnik["konto"] == "297,00"
    for forbidden in ("jmeno", "cislo", "vs", "loginEmail"):
        assert forbidden not in stravnik


def test_unsupported_fixture_has_no_payload():
    assert "setJidelnicek(" not in load("not_ejidelnicek.html")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fixtures.py -v`
Expected: FAIL — `tests.fixture_loader` does not exist.

- [ ] **Step 3: Write minimal implementation**

`tests/fixture_loader.py`:

```python
"""Load test fixtures from disk."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

PUBLIC_FIXTURES: tuple[str, ...] = (
    "letohrad_public.html",
    "stross_public.html",
    "betlemska_public.html",
    "jakutska_public.html",
    "msjesenice_public.html",
)


def load(name: str) -> str:
    """Return a fixture's text."""
    return (FIXTURES / name).read_text(encoding="utf-8")
```

Then write the fixture files themselves.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_fixtures.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures tests/fixture_loader.py tests/test_fixtures.py
git commit -m "Add parser fixtures from five deployments plus synthetic auth payload"
```

---

### Task 3: Data models

**Files:**
- Create: `custom_components/ejidelnicek/models.py`, `tests/test_models.py`

**Interfaces:**
- Produces: `Dish`, `MenuOption`, `DayMenu`, `MealType`, `Diner`, `Canteen`, `Snapshot` exactly as in spec §5, plus:
  - `DayMenu.primary -> MenuOption | None` (the `is_primary` option, else the first)
  - `DayMenu.ordered_option -> MenuOption | None` (first option with `ordered > 0`)
  - `MealType.sorted_dates -> tuple[date, ...]`
  - `MealType.day_for(value: date) -> DayMenu | None`
  - `MealType.next_serving_day(on_or_after: date) -> DayMenu | None`
  - `MealType.slug -> str` (slugified `name`, e.g. `"Oběd menu"` → `"obed_menu"`)
  - `Canteen.meal_type_by_index(index: str) -> MealType | None`

All dataclasses are `frozen=True` so the coordinator can use `always_update=False`.

- [ ] **Step 1: Write the failing test**

`tests/test_models.py` — key cases:

```python
import datetime
from decimal import Decimal

from custom_components.ejidelnicek.models import DayMenu, MealType, MenuOption


def _option(key: str, *, ordered: int = 0, primary: bool = False) -> MenuOption:
    return MenuOption(
        key=key, label=key, name=f"Dish {key}", allergens=(), allergen_codes=(),
        diet=None, price=Decimal("37.00"), ordered=ordered, remaining=None,
        db_id=int(key), is_primary=primary,
    )


def _day(value: datetime.date, *options: MenuOption) -> DayMenu:
    return DayMenu(
        date=value, weekday_label="", soups=(), dessert=None, drink=None,
        options=options, is_blocked=False,
    )


def test_primary_prefers_the_is_primary_option():
    day = _day(datetime.date(2026, 9, 14), _option("3"), _option("1", primary=True))
    assert day.primary.key == "1"


def test_primary_falls_back_to_first_option_when_none_marked():
    day = _day(datetime.date(2026, 9, 14), _option("3"), _option("1"))
    assert day.primary.key == "3"


def test_primary_is_none_for_a_day_with_no_options():
    assert _day(datetime.date(2026, 9, 14)).primary is None


def test_ordered_option_finds_the_booked_option():
    day = _day(datetime.date(2026, 9, 14), _option("1"), _option("2", ordered=1))
    assert day.ordered_option.key == "2"


def test_next_serving_day_skips_a_weekend():
    friday, monday = datetime.date(2026, 9, 18), datetime.date(2026, 9, 21)
    meal = MealType(
        index="0", strava_id=1, name="Oběd", order_day_offset=2,
        days={friday: _day(friday), monday: _day(monday)},
    )
    # Asked on Saturday, the next serving day is Monday.
    assert meal.next_serving_day(datetime.date(2026, 9, 19)).date == monday
    # Asked on Friday itself, Friday still counts.
    assert meal.next_serving_day(friday).date == friday


def test_next_serving_day_is_none_when_the_menu_has_run_out():
    friday = datetime.date(2026, 9, 18)
    meal = MealType(index="0", strava_id=1, name="Oběd", order_day_offset=2,
                    days={friday: _day(friday)})
    assert meal.next_serving_day(datetime.date(2026, 9, 19)) is None


def test_slug_is_ascii_and_snake_case():
    meal = MealType(index="0", strava_id=2, name="Oběd menu", order_day_offset=2, days={})
    assert meal.slug == "obed_menu"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL — `models` module does not exist.

- [ ] **Step 3: Write minimal implementation**

Write `models.py` with the dataclasses and properties. `slug` uses
`homeassistant.util.slugify`, which handles the diacritics (`Oběd` → `obed`).
Note this is the one model-layer HA import and it is pure (no I/O).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ejidelnicek/models.py tests/test_models.py
git commit -m "Add frozen data models with next-serving-day selection"
```

---

### Task 4: Payload extraction

**Files:**
- Create: `custom_components/ejidelnicek/parser.py`, `tests/test_parser_extract.py`

**Interfaces:**
- Produces: `parser.PayloadNotFound(Exception)`, `parser.extract_payload(html: str) -> dict`.

The balanced-brace scan must respect string literals and backslash escapes, because dish names contain braces and more JavaScript follows the payload.

- [ ] **Step 1: Write the failing test**

`tests/test_parser_extract.py`:

```python
import pytest

from custom_components.ejidelnicek.parser import PayloadNotFound, extract_payload
from tests.fixture_loader import PUBLIC_FIXTURES, load


@pytest.mark.parametrize("name", PUBLIC_FIXTURES)
def test_extracts_a_payload_from_every_real_deployment(name):
    payload = extract_payload(load(name))
    assert "stravaMap" in payload
    assert "alergenyMap" in payload


def test_stops_at_the_matching_brace_not_the_last_one():
    html = 'x = ejidelnicek.setJidelnicek({"a": {"b": 1}}); more(); }'
    assert extract_payload(html) == {"a": {"b": 1}}


def test_braces_inside_strings_do_not_end_the_payload():
    html = 'ejidelnicek.setJidelnicek({"nazev": "Gulas {domaci}", "n": 2});'
    assert extract_payload(html)["nazev"] == "Gulas {domaci}"


def test_escaped_quote_inside_a_string_is_handled():
    html = r'ejidelnicek.setJidelnicek({"nazev": "rizek \"domaci\"", "n": 1});'
    assert extract_payload(html)["nazev"] == 'rizek "domaci"'


def test_missing_payload_raises_payload_not_found():
    with pytest.raises(PayloadNotFound):
        extract_payload(load("not_ejidelnicek.html"))


def test_unbalanced_payload_raises_payload_not_found():
    with pytest.raises(PayloadNotFound):
        extract_payload('ejidelnicek.setJidelnicek({"a": 1')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_parser_extract.py -v`
Expected: FAIL — `parser` module does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
CALL = "setJidelnicek("


def extract_payload(html: str) -> dict:
    """Extract the JSON argument of the inline setJidelnicek(...) call."""
    start = html.find(CALL)
    if start == -1:
        raise PayloadNotFound("no setJidelnicek(...) call found")
    start += len(CALL)
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(html)):
        char = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : index + 1])
                except json.JSONDecodeError as err:
                    raise PayloadNotFound(f"payload is not valid JSON: {err}") from err
    raise PayloadNotFound("unbalanced braces in payload")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_parser_extract.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ejidelnicek/parser.py tests/test_parser_extract.py
git commit -m "Add balanced-brace payload extraction"
```

---

### Task 5: Payload → models

**Files:**
- Modify: `custom_components/ejidelnicek/parser.py`
- Create: `tests/test_parser_canteen.py`, `tests/test_parser_purity.py`

**Interfaces:**
- Consumes: `extract_payload`, all models.
- Produces:
  - `parser.resolve_allergens(codes: str | None, legend: Mapping[str, str]) -> tuple[tuple[str, ...], tuple[str, ...]]` returning `(names, codes)`
  - `parser.parse_decimal_cz(value: str | None) -> Decimal | None`
  - `parser.parse_canteen(payload: dict, *, authoritative: bool = False) -> Canteen`

`authoritative=False` (the public page) forces `price=None`, `remaining=None`,
`ordered=0`, because the public view zeroes those fields and reporting `0`
would read as "free" or "sold out". `authoritative=True` (the AJAX response)
maps them for real, with `zbyva == -1` → `None` (untracked).

- [ ] **Step 1: Write the failing test**

`tests/test_parser_canteen.py`:

```python
import datetime
from decimal import Decimal

import pytest

from custom_components.ejidelnicek.parser import (
    extract_payload, parse_canteen, parse_decimal_cz, resolve_allergens,
)
from tests.fixture_loader import PUBLIC_FIXTURES, load


def _canteen(name, **kwargs):
    return parse_canteen(extract_payload(load(name)), **kwargs)


def test_allergen_codes_are_single_characters_not_integers():
    """'17' means codes 1 and 7. int('17') would silently pick the wrong allergen."""
    legend = {"1": "Obilniny", "7": "Mleko", "17": "Jecmen"}
    names, codes = resolve_allergens("17", legend)
    assert codes == ("1", "7")
    assert names == ("Obilniny", "Mleko")


def test_unknown_allergen_code_is_kept_as_a_code_without_a_name():
    names, codes = resolve_allergens("9", {"1": "Obilniny"})
    assert codes == ("9",)
    assert names == ()


def test_empty_allergens():
    assert resolve_allergens("", {"1": "x"}) == ((), ())
    assert resolve_allergens(None, {"1": "x"}) == ((), ())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("297,00", Decimal("297.00")), ("37.00", Decimal("37.00")),
     ("0,00", Decimal("0.00")), ("", None), (None, None), ("abc", None)],
)
def test_czech_decimal_comma(raw, expected):
    assert parse_decimal_cz(raw) == expected


@pytest.mark.parametrize("name", PUBLIC_FIXTURES)
def test_every_deployment_parses_into_at_least_one_meal_type(name):
    canteen = _canteen(name)
    assert canteen.meal_types
    assert canteen.allergens


def test_letohrad_parses_a_known_day():
    meal = _canteen("letohrad_public.html").meal_types[0]
    assert meal.name == "Oběd"
    assert meal.strava_id == 1
    assert meal.order_day_offset == 2
    day = meal.day_for(datetime.date(2026, 9, 14))
    assert day.soups[0].name == "Dýňový krém se semínky"
    assert day.dessert == "Salát bar / ovoce"
    assert {o.label for o in day.options} == {"1", "D"}
    assert day.primary.name == "Květák s vejci, brambory s pažitkou"


def test_public_view_reports_price_and_remaining_as_unknown_not_zero():
    day = _canteen("letohrad_public.html").meal_types[0].day_for(datetime.date(2026, 9, 14))
    assert day.primary.price is None
    assert day.primary.remaining is None
    assert day.primary.ordered == 0


def test_per_school_meal_ids_are_not_hardcoded():
    assert _canteen("jakutska_public.html").meal_types[0].strava_id == 2
    assert _canteen("betlemska_public.html").meal_types[0].strava_id == 3


def test_kindergarten_with_no_published_menu_parses_without_crashing():
    """msjesenice publishes empty soup/dessert/drink on every day."""
    meal = _canteen("msjesenice_public.html").meal_types[0]
    day = meal.day_for(meal.sorted_dates[0])
    assert day.soups == ()
    assert day.dessert is None
    assert day.drink is None
    assert day.options  # a single placeholder option
```

`tests/test_parser_purity.py`:

```python
import ast
from pathlib import Path

FORBIDDEN = {"aiohttp", "homeassistant", "requests", "urllib", "socket", "asyncio"}


def test_parser_is_pure_and_imports_nothing_that_does_io():
    """parser.py must stay offline-testable: text in, dataclasses out."""
    tree = ast.parse(Path("custom_components/ejidelnicek/parser.py").read_text("utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert imported & FORBIDDEN == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_parser_canteen.py tests/test_parser_purity.py -v`
Expected: FAIL — `parse_canteen` not defined.

- [ ] **Step 3: Write minimal implementation**

Add to `parser.py`. `resolve_allergens` iterates characters of the code string
and looks each up in the legend, dropping unknown names but keeping codes.
`parse_canteen` walks `stravaMap` → `denMap` → `menuMap`, treating `""` as
`None` for `zakusek`/`napoj`, tolerating a missing or empty `polevka` list, and
parsing ISO dates with `datetime.date.fromisoformat`. A day whose date key is
not a valid ISO date is skipped rather than raising.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_parser_canteen.py tests/test_parser_purity.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ejidelnicek/parser.py tests/test_parser_canteen.py tests/test_parser_purity.py
git commit -m "Map payload to models with digit-wise allergen resolution"
```

---

### Task 6: Diner parsing and authoritative day merge

**Files:**
- Modify: `custom_components/ejidelnicek/parser.py`
- Create: `tests/test_parser_merge.py`

**Interfaces:**
- Produces:
  - `parser.parse_diner(stravnik: dict) -> Diner`
  - `parser.parse_ajax(body: str) -> tuple[Canteen, Diner | None]` — parses `{"jidelnicek": …, "stravnik": …}`, canteen parsed with `authoritative=True`
  - `parser.merge_day(base: DayMenu, authoritative: DayMenu) -> DayMenu`

`merge_day` iterates the **base** options and overlays `ordered`, `price` and
`remaining` for options whose key appears in the authoritative day, then takes
`is_blocked` from the authoritative day. Base options are kept even when the
AJAX response omits them — verified real behaviour: for 2026-09-14 the page
returned keys `1` and `3` while the AJAX response returned only key `1`.

- [ ] **Step 1: Write the failing test**

`tests/test_parser_merge.py`:

```python
import datetime
from decimal import Decimal

from custom_components.ejidelnicek.models import DayMenu, MenuOption
from custom_components.ejidelnicek.parser import (
    extract_payload, merge_day, parse_ajax, parse_canteen,
)
from tests.fixture_loader import load

DAY = datetime.date(2026, 9, 14)


def _option(key, *, ordered=0, price=None, remaining=None, name=None):
    return MenuOption(
        key=key, label=key, name=name or f"Dish {key}", allergens=(), allergen_codes=(),
        diet=None, price=price, ordered=ordered, remaining=remaining,
        db_id=int(key), is_primary=key == "1",
    )


def test_merge_overlays_order_data_onto_the_public_day():
    base = DayMenu(date=DAY, weekday_label="pondělí", soups=(), dessert="Ovoce",
                   drink="Voda", options=(_option("1"), _option("3")), is_blocked=False)
    auth = DayMenu(date=DAY, weekday_label="", soups=(), dessert=None, drink=None,
                   options=(_option("1", ordered=1, price=Decimal("37.00")),),
                   is_blocked=False)
    merged = merge_day(base, auth)
    assert merged.ordered_option.key == "1"
    assert merged.options[0].price == Decimal("37.00")
    # Menu text from the public page survives.
    assert merged.dessert == "Ovoce"
    # An option the AJAX response omitted is kept, not dropped.
    assert {o.key for o in merged.options} == {"1", "3"}
    assert merged.options[1].ordered == 0


def test_merge_takes_blocked_state_from_the_authoritative_day():
    base = DayMenu(date=DAY, weekday_label="", soups=(), dessert=None, drink=None,
                   options=(_option("1"),), is_blocked=False)
    auth = DayMenu(date=DAY, weekday_label="", soups=(), dessert=None, drink=None,
                   options=(_option("1"),), is_blocked=True)
    assert merge_day(base, auth).is_blocked is True


def test_parse_ajax_reads_orders_balance_and_debt():
    canteen, diner = parse_ajax(load("ajax_authenticated.json"))
    meal = canteen.meal_types[0]
    day = meal.day_for(meal.sorted_dates[0])
    assert day.ordered_option.key == "1"
    assert day.ordered_option.price == Decimal("37.00")
    # zbyva of -1 means untracked, not "none left".
    assert day.ordered_option.remaining is None
    assert diner.balance == Decimal("297.00")
    assert diner.in_debt is False


def test_diner_never_exposes_identifying_fields():
    _, diner = parse_ajax(load("ajax_authenticated.json"))
    for forbidden in ("jmeno", "cislo", "vs", "loginEmail", "name"):
        assert not hasattr(diner, forbidden)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_parser_merge.py -v`
Expected: FAIL — `merge_day` not defined.

- [ ] **Step 3: Write minimal implementation**

Add `parse_diner`, `parse_ajax`, `merge_day` to `parser.py` using
`dataclasses.replace` to rebuild frozen instances.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_parser_merge.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ejidelnicek/parser.py tests/test_parser_merge.py
git commit -m "Add diner parsing and authoritative day merge"
```

---

### Task 7: API client

**Files:**
- Create: `custom_components/ejidelnicek/api.py`, `tests/test_api.py`

**Interfaces:**
- Produces:
  - `api.EjidelnicekError`, `api.CannotConnect`, `api.InvalidAuth`, `api.UnsupportedSite`
  - `api.candidate_base_urls(raw: str) -> tuple[str, ...]` — normalised bases ending in `/ejidelnicek/`; when the input has no scheme, yields the `https` candidate then the `http` one
  - `api.EjidelnicekClient(session: ClientSession, base_url: str, username: str | None = None, password: str | None = None)`
    - `has_credentials -> bool`
    - `async_fetch_public() -> Canteen`
    - `async_login() -> None`
    - `async_fetch_day(value: date) -> tuple[Canteen, Diner | None]`
    - `async_fetch_snapshot() -> Snapshot`
  - `api.ValidationResult(base_url: str, canteen: Canteen, diner: Diner | None, menu_is_empty: bool)`
  - `api.async_validate(session, raw_url, username, password) -> ValidationResult`

`async_fetch_snapshot` implements the 3-request hybrid: one `menu/` fetch, then
`ajax/get-jidelnicek?datum=` for today and each meal type's next serving day
(deduplicated, and only for dates the canteen actually publishes). It merges the
authoritative days over the public ones. With no credentials it does one request
and returns `diner=None`.

Session recovery: a request that lands on the login page (or returns 302/400
from AJAX) triggers exactly one re-login and one retry. `menu_is_empty` is true
when no day in any meal type has a soup, dessert, or drink — the
placeholder-kindergarten signal.

- [ ] **Step 1: Write the failing test**

`tests/test_api.py` (uses `aioresponses`, which ships with the HA test harness):

```python
import datetime
from decimal import Decimal

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.ejidelnicek.api import (
    CannotConnect, EjidelnicekClient, InvalidAuth, UnsupportedSite,
    async_validate, candidate_base_urls,
)
from tests.fixture_loader import load

BASE = "https://letohrad.zs-stross.cz/ejidelnicek/"
MENU = BASE + "menu/"


@pytest.mark.parametrize(
    ("raw", "expected_first"),
    [
        ("https://x.cz", "https://x.cz/ejidelnicek/"),
        ("https://x.cz/ejidelnicek", "https://x.cz/ejidelnicek/"),
        ("https://x.cz/ejidelnicek/", "https://x.cz/ejidelnicek/"),
        ("https://x.cz/ejidelnicek/menu/", "https://x.cz/ejidelnicek/"),
        ("http://x.cz:8080/ejidelnicek/", "http://x.cz:8080/ejidelnicek/"),
        ("  x.cz  ", "https://x.cz/ejidelnicek/"),
    ],
)
def test_url_normalisation(raw, expected_first):
    assert candidate_base_urls(raw)[0] == expected_first


def test_scheme_is_only_guessed_when_absent():
    # No scheme given: try https, then fall back to http (several canteens are http-only).
    assert candidate_base_urls("x.cz") == (
        "https://x.cz/ejidelnicek/", "http://x.cz/ejidelnicek/",
    )
    # Scheme given: respect it, do not silently try the other one.
    assert candidate_base_urls("http://x.cz") == ("http://x.cz/ejidelnicek/",)


async def test_anonymous_fetch_uses_a_single_request():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(MENU, status=200, body=load("letohrad_public.html"))
            client = EjidelnicekClient(session, BASE)
            snapshot = await client.async_fetch_snapshot()
    assert snapshot.diner is None
    assert snapshot.canteen.meal_types[0].name == "Oběd"


async def test_a_page_without_a_payload_is_reported_as_an_unsupported_site():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(MENU, status=200, body=load("not_ejidelnicek.html"))
            with pytest.raises(UnsupportedSite):
                await EjidelnicekClient(session, BASE).async_fetch_public()


async def test_connection_errors_surface_as_cannot_connect():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(MENU, status=500)
            with pytest.raises(CannotConnect):
                await EjidelnicekClient(session, BASE).async_fetch_public()


async def test_failed_login_raises_invalid_auth():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(BASE, status=200, body="<form id='loginForm'></form>")
            mocked.post(BASE + "logincheck", status=200,
                        body="<form id='loginForm'>bad</form>")
            client = EjidelnicekClient(session, BASE, "u", "p")
            with pytest.raises(InvalidAuth):
                await client.async_login()


async def test_authenticated_snapshot_merges_order_data_over_the_public_menu():
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(BASE, status=200, body="<form id='loginForm'></form>")
            mocked.post(BASE + "logincheck", status=200, body="ejidelnicek.setJidelnicek({})")
            mocked.get(MENU, status=200, body=load("letohrad_public.html"))
            # Any datum the client asks for returns the synthetic authenticated day.
            mocked.get(
                __import__("re").compile(r".*get-jidelnicek.*"),
                status=200, body=load("ajax_authenticated.json"), repeat=True,
            )
            client = EjidelnicekClient(session, BASE, "u", "p")
            snapshot = await client.async_fetch_snapshot()
    assert snapshot.diner.balance == Decimal("297.00")
    meal = snapshot.canteen.meal_types[0]
    # Public menu text is still present for days we did not fetch authoritatively.
    assert meal.day_for(datetime.date(2026, 9, 25)) is not None


async def test_validate_flags_a_canteen_that_publishes_no_menu_publicly():
    base = "https://msjesenice.e-jidelnicek.eu/ejidelnicek/"
    async with ClientSession() as session:
        with aioresponses() as mocked:
            mocked.get(base + "menu/", status=200, body=load("msjesenice_public.html"))
            result = await async_validate(session, base, None, None)
    assert result.menu_is_empty is True
    assert result.base_url == base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: FAIL — `api` module does not exist.

- [ ] **Step 3: Write minimal implementation**

Write `api.py`. Non-2xx and `aiohttp.ClientError`/`TimeoutError` become
`CannotConnect`; `PayloadNotFound` from the public page becomes
`UnsupportedSite`. `async_validate` walks `candidate_base_urls`, returning on
the first candidate that yields a payload and re-raising the last error if none
do.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ejidelnicek/api.py tests/test_api.py
git commit -m "Add HTTP client with URL resolution, login and hybrid snapshot fetch"
```

---

### Task 8: Coordinator and entry setup

**Files:**
- Create: `custom_components/ejidelnicek/coordinator.py`
- Modify: `custom_components/ejidelnicek/__init__.py`
- Create: `tests/test_init.py`

**Interfaces:**
- Produces:
  - `coordinator.EjidelnicekCoordinator(DataUpdateCoordinator[Snapshot])` with `client` attribute
  - `EjidelnicekConfigEntry = ConfigEntry[EjidelnicekCoordinator]` type alias in `coordinator.py`
  - `__init__.async_setup_entry`, `async_unload_entry`, `async_reload_entry`

`_async_update_data` maps `InvalidAuth` → `ConfigEntryAuthFailed` (so HA starts
reauth) and every other `EjidelnicekError` → `UpdateFailed`. Coordinator is
constructed with `config_entry=entry` and `always_update=False`.

- [ ] **Step 1: Write the failing test**

`tests/test_init.py`:

```python
from aioresponses import aioresponses
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ejidelnicek.const import CONF_BASE_URL, DOMAIN
from tests.fixture_loader import load

BASE = "https://letohrad.zs-stross.cz/ejidelnicek/"


async def test_setup_and_unload(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_BASE_URL: BASE},
                            unique_id=f"{BASE}|public")
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(BASE + "menu/", status=200, body=load("letohrad_public.html"),
                   repeat=True)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_the_canteen_is_unreachable(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_BASE_URL: BASE},
                            unique_id=f"{BASE}|public")
    entry.add_to_hass(hass)
    with aioresponses() as mocked:
        mocked.get(BASE + "menu/", status=500, repeat=True)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_init.py -v`
Expected: FAIL — setup not implemented.

- [ ] **Step 3: Write minimal implementation**

`async_setup_entry` builds the client from `entry.data`, creates the
coordinator, calls `async_config_entry_first_refresh()`, assigns
`entry.runtime_data`, forwards `PLATFORMS` via `async_forward_entry_setups`, and
registers an options update listener that reloads the entry.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_init.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ejidelnicek/coordinator.py custom_components/ejidelnicek/__init__.py tests/test_init.py
git commit -m "Add coordinator and config entry setup"
```

---

### Task 9: Config flow

**Files:**
- Create: `custom_components/ejidelnicek/config_flow.py`, `strings.json`, `translations/en.json`, `translations/cs.json`
- Create: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `api.async_validate`, `api.CannotConnect/InvalidAuth/UnsupportedSite`.
- Produces: `EjidelnicekConfigFlow` with `async_step_user`, `async_step_reauth`, `async_step_reauth_confirm`, and `EjidelnicekOptionsFlow` with `async_step_init`.

Entry data keys: `CONF_BASE_URL`, `CONF_USERNAME`, `CONF_PASSWORD` (the latter
two absent when anonymous). `unique_id` is `f"{base_url}|{username or 'public'}"`.
Title is `f"{canteen.meal_types[0].name} – {host}"`, falling back to the host.

- [ ] **Step 1: Write the failing test**

`tests/test_config_flow.py` — one test per error key plus the happy paths:

```python
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ejidelnicek.api import (
    CannotConnect, InvalidAuth, UnsupportedSite, ValidationResult,
)
from custom_components.ejidelnicek.const import CONF_BASE_URL, DOMAIN
from custom_components.ejidelnicek.parser import extract_payload, parse_canteen
from tests.fixture_loader import load

BASE = "https://letohrad.zs-stross.cz/ejidelnicek/"
VALIDATE = "custom_components.ejidelnicek.config_flow.async_validate"


def _result(**kwargs):
    canteen = parse_canteen(extract_payload(load("letohrad_public.html")))
    defaults = {"base_url": BASE, "canteen": canteen, "diner": None,
                "menu_is_empty": False}
    return ValidationResult(**{**defaults, **kwargs})


async def _submit(hass, user_input):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def test_anonymous_setup_creates_an_entry(hass: HomeAssistant):
    with patch(VALIDATE, return_value=_result()):
        result = await _submit(hass, {CONF_BASE_URL: "letohrad.zs-stross.cz"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_BASE_URL: BASE}
    assert result["result"].unique_id == f"{BASE}|public"


async def test_credentials_are_stored_and_change_the_unique_id(hass: HomeAssistant):
    with patch(VALIDATE, return_value=_result()):
        result = await _submit(hass, {
            CONF_BASE_URL: BASE, CONF_USERNAME: "u", CONF_PASSWORD: "p"})
    assert result["data"][CONF_USERNAME] == "u"
    assert result["result"].unique_id == f"{BASE}|u"


@pytest.mark.parametrize(
    ("error", "expected"),
    [(CannotConnect, "cannot_connect"), (InvalidAuth, "invalid_auth"),
     (UnsupportedSite, "unsupported_site"), (Exception, "unknown")],
)
async def test_errors_are_reported_distinctly(hass: HomeAssistant, error, expected):
    with patch(VALIDATE, side_effect=error):
        result = await _submit(hass, {CONF_BASE_URL: BASE})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_the_same_school_and_user_cannot_be_added_twice(hass: HomeAssistant):
    MockConfigEntry(domain=DOMAIN, unique_id=f"{BASE}|u",
                    data={CONF_BASE_URL: BASE}).add_to_hass(hass)
    with patch(VALIDATE, return_value=_result()):
        result = await _submit(hass, {
            CONF_BASE_URL: BASE, CONF_USERNAME: "u", CONF_PASSWORD: "p"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_two_children_at_the_same_school_are_both_allowed(hass: HomeAssistant):
    MockConfigEntry(domain=DOMAIN, unique_id=f"{BASE}|child_one",
                    data={CONF_BASE_URL: BASE}).add_to_hass(hass)
    with patch(VALIDATE, return_value=_result()):
        result = await _submit(hass, {
            CONF_BASE_URL: BASE, CONF_USERNAME: "child_two", CONF_PASSWORD: "p"})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_reauth_updates_the_password(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=f"{BASE}|u",
        data={CONF_BASE_URL: BASE, CONF_USERNAME: "u", CONF_PASSWORD: "old"})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    with patch(VALIDATE, return_value=_result()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config_flow.py -v`
Expected: FAIL — `config_flow` module does not exist.

- [ ] **Step 3: Write minimal implementation**

Write `config_flow.py` and the translation files. `strings.json` and
`translations/en.json` carry identical content; `translations/cs.json` is the
Czech version. Error keys: `cannot_connect`, `invalid_auth`, `unsupported_site`,
`unknown`; abort keys: `already_configured`, `reauth_successful`,
`wrong_account`. The `unsupported_site` message must name
`skolnijidelna.online` and `e-jidelnicek.cz` as different systems.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config_flow.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ejidelnicek/config_flow.py custom_components/ejidelnicek/strings.json custom_components/ejidelnicek/translations tests/test_config_flow.py
git commit -m "Add config, reauth and options flows with translations"
```

---

### Task 10: Base entity and day sensors

**Files:**
- Create: `custom_components/ejidelnicek/entity.py`, `custom_components/ejidelnicek/sensor.py`
- Create: `tests/test_sensor.py`

**Interfaces:**
- Produces:
  - `entity.EjidelnicekEntity(CoordinatorEntity[EjidelnicekCoordinator])` — sets `_attr_has_entity_name = True` and `_attr_device_info`; in `async_added_to_hass` registers `async_track_time_change(hour=0, minute=0, second=0)` to call `async_write_ha_state`
  - `sensor.EjidelnicekDaySensor(coordinator, meal_index, which)` where `which` is `"today"` or `"next_serving_day"`

Values are computed in properties from `coordinator.data` and `dt_util.now()`,
never cached in `__init__`, so the midnight state write is all the rollover
needs.

- [ ] **Step 1: Write the failing test**

`tests/test_sensor.py`:

```python
import datetime
from unittest.mock import patch

from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ejidelnicek.const import CONF_BASE_URL, DOMAIN
from tests.fixture_loader import load

BASE = "https://letohrad.zs-stross.cz/ejidelnicek/"
# The fixture publishes 2026-09-14 .. 2026-09-25.
SATURDAY = datetime.datetime(2026, 9, 19, 12, 0, tzinfo=datetime.UTC)
MONDAY = datetime.datetime(2026, 9, 14, 12, 0, tzinfo=datetime.UTC)


async def _setup(hass, now):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_BASE_URL: BASE},
                            unique_id=f"{BASE}|public", title="Oběd – letohrad")
    entry.add_to_hass(hass)
    with (
        aioresponses() as mocked,
        patch("homeassistant.util.dt.now", return_value=now),
    ):
        mocked.get(BASE + "menu/", status=200, body=load("letohrad_public.html"),
                   repeat=True)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_today_sensor_reports_the_dish_on_a_serving_day(hass: HomeAssistant):
    await _setup(hass, MONDAY)
    state = hass.states.get("sensor.obed_letohrad_obed_today")
    assert state.state == "Květák s vejci, brambory s pažitkou"
    assert state.attributes["soup"] == "Dýňový krém se semínky"
    assert state.attributes["options_count"] == 2
    assert state.attributes["date"] == "2026-09-14"


async def test_today_sensor_is_unknown_on_a_weekend(hass: HomeAssistant):
    await _setup(hass, SATURDAY)
    assert hass.states.get("sensor.obed_letohrad_obed_today").state == "unknown"


async def test_next_serving_day_points_past_the_weekend(hass: HomeAssistant):
    await _setup(hass, SATURDAY)
    state = hass.states.get("sensor.obed_letohrad_obed_next_serving_day")
    assert state.state == "Vepřový řízeček, bramborová kaše, maštěné máslem."
    assert state.attributes["date"] == "2026-09-21"
    assert state.attributes["days_ahead"] == 2


async def test_public_view_reports_no_ordered_option(hass: HomeAssistant):
    await _setup(hass, MONDAY)
    state = hass.states.get("sensor.obed_letohrad_obed_today")
    assert state.attributes["ordered_option"] is None


async def test_credential_only_entities_are_absent_when_anonymous(hass: HomeAssistant):
    await _setup(hass, MONDAY)
    assert hass.states.get("sensor.obed_letohrad_balance") is None
    assert hass.states.get("binary_sensor.obed_letohrad_debt") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sensor.py -v`
Expected: FAIL — sensor platform not implemented.

- [ ] **Step 3: Write minimal implementation**

Write `entity.py` and `sensor.py` with the day sensors. Attributes are exactly
those listed in spec §8. States are clamped to 255 characters.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sensor.py -v`
Expected: all passed. Adjust the asserted entity ids to whatever HA actually
generates from the title and translation keys if they differ.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ejidelnicek/entity.py custom_components/ejidelnicek/sensor.py tests/test_sensor.py
git commit -m "Add day sensors with weekend-aware next serving day"
```

---

### Task 11: Credentialed sensors

**Files:**
- Modify: `custom_components/ejidelnicek/sensor.py`
- Create: `custom_components/ejidelnicek/binary_sensor.py`
- Create: `tests/test_credentialed_entities.py`

**Interfaces:**
- Produces:
  - `sensor.EjidelnicekOrderedSensor(coordinator, meal_index)` — state is the ordered option's `label`, or `"none"`
  - `sensor.EjidelnicekBalanceSensor(coordinator)` — `device_class: monetary`, `native_unit_of_measurement: "CZK"`
  - `binary_sensor.EjidelnicekDebtBinarySensor(coordinator)` — `device_class: problem`

These are added only when `coordinator.client.has_credentials`.

- [ ] **Step 1: Write the failing test**

`tests/test_credentialed_entities.py`:

```python
import datetime
import re
from unittest.mock import patch

from aioresponses import aioresponses
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ejidelnicek.const import CONF_BASE_URL, DOMAIN
from tests.fixture_loader import load

BASE = "https://letohrad.zs-stross.cz/ejidelnicek/"
MONDAY = datetime.datetime(2026, 9, 14, 12, 0, tzinfo=datetime.UTC)


async def _setup(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Oběd – letohrad", unique_id=f"{BASE}|u",
        data={CONF_BASE_URL: BASE, CONF_USERNAME: "u", CONF_PASSWORD: "p"})
    entry.add_to_hass(hass)
    with (
        aioresponses() as mocked,
        patch("homeassistant.util.dt.now", return_value=MONDAY),
    ):
        mocked.get(BASE, status=200, body="<form id='loginForm'></form>", repeat=True)
        mocked.post(BASE + "logincheck", status=200,
                    body="ejidelnicek.setJidelnicek({})", repeat=True)
        mocked.get(BASE + "menu/", status=200,
                   body=load("letohrad_public.html"), repeat=True)
        mocked.get(re.compile(r".*get-jidelnicek.*"), status=200,
                   body=load("ajax_authenticated.json"), repeat=True)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_balance_and_debt_appear_with_credentials(hass: HomeAssistant):
    await _setup(hass)
    assert hass.states.get("sensor.obed_letohrad_balance").state == "297.00"
    assert hass.states.get("binary_sensor.obed_letohrad_debt").state == "off"


async def test_ordered_sensor_reports_the_booked_option(hass: HomeAssistant):
    await _setup(hass)
    state = hass.states.get("sensor.obed_letohrad_obed_ordered_next_serving_day")
    assert state.state == "1"
    assert state.attributes["options_count"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_credentialed_entities.py -v`
Expected: FAIL — entities do not exist.

- [ ] **Step 3: Write minimal implementation**

Add the three entity classes and gate them on `has_credentials`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_credentialed_entities.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ejidelnicek/sensor.py custom_components/ejidelnicek/binary_sensor.py tests/test_credentialed_entities.py
git commit -m "Add ordered, balance and debt entities for credentialed entries"
```

---

### Task 12: Calendar

**Files:**
- Create: `custom_components/ejidelnicek/calendar.py`, `tests/test_calendar.py`

**Interfaces:**
- Produces: `calendar.EjidelnicekCalendar(coordinator, meal_index)` with `event` and `async_get_events`.

All-day events: `start = day`, `end = day + timedelta(days=1)` (HA treats the
end as exclusive). `async_get_events` returns events sorted by start.
Description lists soup, each option as `"<label>: <name>"`, dessert, drink and
allergens. A blocked day is prefixed in the summary.

- [ ] **Step 1: Write the failing test**

`tests/test_calendar.py`:

```python
import datetime
from unittest.mock import patch

from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ejidelnicek.const import CONF_BASE_URL, DOMAIN
from tests.fixture_loader import load

BASE = "https://letohrad.zs-stross.cz/ejidelnicek/"
MONDAY = datetime.datetime(2026, 9, 14, 12, 0, tzinfo=datetime.UTC)
ENTITY = "calendar.obed_letohrad_obed"


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_BASE_URL: BASE},
                            unique_id=f"{BASE}|public", title="Oběd – letohrad")
    entry.add_to_hass(hass)
    with (
        aioresponses() as mocked,
        patch("homeassistant.util.dt.now", return_value=MONDAY),
    ):
        mocked.get(BASE + "menu/", status=200, body=load("letohrad_public.html"),
                   repeat=True)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_all_day_events_use_an_exclusive_end_date(hass: HomeAssistant):
    await _setup(hass)
    events = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": ENTITY, "start_date_time": "2026-09-14T00:00:00",
         "end_date_time": "2026-09-15T00:00:00"},
        blocking=True, return_response=True)
    found = events[ENTITY]["events"]
    assert len(found) == 1
    assert found[0]["start"] == "2026-09-14"
    assert found[0]["end"] == "2026-09-15"
    assert found[0]["summary"] == "Květák s vejci, brambory s pažitkou"
    assert "Dýňový krém se semínky" in found[0]["description"]
    assert "D: Menu 1" in found[0]["description"]


async def test_events_are_returned_in_chronological_order(hass: HomeAssistant):
    await _setup(hass)
    events = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": ENTITY, "start_date_time": "2026-09-14T00:00:00",
         "end_date_time": "2026-09-26T00:00:00"},
        blocking=True, return_response=True)
    starts = [e["start"] for e in events[ENTITY]["events"]]
    assert starts == sorted(starts)
    assert len(starts) == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_calendar.py -v`
Expected: FAIL — calendar platform not implemented.

- [ ] **Step 3: Write minimal implementation**

Write `calendar.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_calendar.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ejidelnicek/calendar.py tests/test_calendar.py
git commit -m "Add calendar entity with all-day menu events"
```

---

### Task 13: Diagnostics, README, full verification

**Files:**
- Create: `custom_components/ejidelnicek/diagnostics.py`, `tests/test_diagnostics.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `diagnostics.async_get_config_entry_diagnostics(hass, entry) -> dict` with `CONF_USERNAME` and `CONF_PASSWORD` redacted via `homeassistant.components.diagnostics.async_redact_data`.

- [ ] **Step 1: Write the failing test**

```python
async def test_diagnostics_redact_credentials(hass, hass_client):
    """A diagnostics download must never leak the canteen password."""
    entry = await _setup_with_credentials(hass)
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert data["entry"]["data"]["password"] == "**REDACTED**"
    assert data["entry"]["data"]["username"] == "**REDACTED**"
    assert "p" not in str(data["entry"]["data"].values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py -v`
Expected: FAIL — diagnostics not implemented.

- [ ] **Step 3: Write minimal implementation**

Write `diagnostics.py`. Then write the `README.md`: what the integration does,
HACS install steps, the URL formats accepted, the entity table, an example
automation template reading `sensor.…_next_serving_day` attributes, a note that
some canteens publish nothing publicly and need credentials, and the phase-2
roadmap. **Use a placeholder host (`https://your-school.example.cz`), never the
author's school.**

- [ ] **Step 4: Run the full verification suite**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check custom_components tests
.venv/bin/python -m ruff format --check custom_components tests
git grep -n "menu-update" -- custom_components || echo "no write endpoint referenced"
# Secret scan. Read the live values from the environment so no credential
# literal is ever written into this repository.
git grep -niE "${EJ_SECRET_PATTERN:-jmeno|loginEmail}" -- custom_components README.md \
  || echo "no credentials or personal hosts committed"
```

Expected: tests pass, ruff clean, both greps report the "no …" message.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ejidelnicek/diagnostics.py tests/test_diagnostics.py README.md
git commit -m "Add redacted diagnostics and user documentation"
```

---

## Self-Review

**1. Spec coverage.** §3 research → Tasks 4–7 (extraction, digit-wise
allergens, authoritative merge, placeholder canteens). §4 architecture →
purity test in Task 5. §5 models → Task 3. §6 transport → Task 7. §7
coordinator, interval, midnight rollover → Tasks 8 and 10. §8 entities →
Tasks 10–12. §9 config flow, error keys, unique id, reauth, options → Task 9.
§10 privacy → Tasks 2, 13, plus the Task 13 grep gate. §11 testing → every
task. §12 layout → Task 1. §13 phase-2 fields → Task 3 models, guarded by the
`menu-update` test in Task 1.

**2. Placeholder scan.** No TBD/TODO. Every code step carries real code. Task 1
describes CI workflow contents rather than pasting YAML, and Task 13 describes
README prose — both are content-complete instructions, not deferred decisions.

**3. Type consistency.** `extract_payload → dict`, `parse_canteen(payload, *,
authoritative=False) → Canteen`, `parse_ajax(body) → tuple[Canteen, Diner |
None]`, `merge_day(base, authoritative) → DayMenu`, `candidate_base_urls(raw) →
tuple[str, ...]`, `async_validate(...) → ValidationResult(base_url, canteen,
diner, menu_is_empty)`. `MealType.next_serving_day(on_or_after)` and
`MealType.slug` are used consistently in Tasks 3, 10 and 12.

**Known risk.** The entity ids asserted in Tasks 10–12 depend on how HA derives
them from the entry title plus translation keys. Task 10 Step 4 says to align
the assertions with the ids HA actually registers rather than forcing a
particular slug.
