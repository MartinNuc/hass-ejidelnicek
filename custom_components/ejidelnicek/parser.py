"""Pure extraction of the E-jídelníček JSON payload from an HTML page.

Every page embeds its menu as the single JSON argument of an inline
``ejidelnicek.setJidelnicek({...})`` call. A regex to the last ``}`` is
wrong here: Czech dish names can contain braces, and more JavaScript
follows the payload on the page. So this module scans forward from the
opening brace, tracking nesting depth while correctly skipping over
string literals and backslash escapes.

This module performs no I/O of any kind.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal, InvalidOperation

from .models import Canteen, DayMenu, Diner, Dish, MealType, MenuOption

CALL = "setJidelnicek("


class PayloadNotFound(Exception):
    """Raised when the page has no usable setJidelnicek(...) payload."""


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


def resolve_allergens(
    codes: str | None, legend: Mapping[str, str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Resolve a concatenated allergen code string against a legend.

    The payload concatenates allergen codes as single BASE-36 characters, e.g.
    ``"17"`` means codes ``1`` and ``7`` -- never the integer 17 -- and codes
    10-28 are encoded as the letters ``A``-``S`` (confirmed against the site's
    own ``alergZobr`` rendering, e.g. ``alerg="1F"`` displays as allergens
    ``1,1a``, and ``alergenyMap["15"]`` is ``1a``, so ``F`` decodes to ``15``).
    Each character is decoded with ``int(ch, 36)`` and the decoded numeric
    code (not the raw character) is what appears in the returned codes tuple,
    so it matches both the legend's keys and what the site shows a parent.
    Unknown codes are kept in the returned codes tuple but contribute no name.
    A character that is not valid base-36 is silently skipped rather than
    raising.
    """
    if not codes:
        return (), ()
    resolved_codes = []
    for char in codes:
        try:
            resolved_codes.append(str(int(char, 36)))
        except ValueError:
            continue
    names = tuple(legend[code] for code in resolved_codes if code in legend)
    return names, tuple(resolved_codes)


def parse_decimal_cz(value: str | None) -> Decimal | None:
    """Parse a decimal that may use a Czech comma or a dot as separator.

    Returns None for empty, missing or unparseable input instead of raising.
    """
    if not value:
        return None
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation:
        return None


def _clean_text(value: str | None) -> str | None:
    """Return None for an empty or missing string, else the string itself."""
    return value if value else None


def _parse_soups(polevka: list[dict] | None, legend: Mapping[str, str]) -> tuple[Dish, ...]:
    """Parse the soup list, tolerating a missing or empty list."""
    soups = []
    for soup in polevka or []:
        names, codes = resolve_allergens(soup.get("alerg"), legend)
        soups.append(Dish(name=soup["polevka"], allergens=names, allergen_codes=codes))
    return tuple(soups)


def _parse_option(
    key: str,
    raw: dict,
    *,
    allergen_legend: Mapping[str, str],
    diet_legend: Mapping[str, str],
    authoritative: bool,
) -> MenuOption:
    """Parse a single menuMap entry into a MenuOption."""
    names, codes = resolve_allergens(raw.get("alerg"), allergen_legend)
    diet_code = raw.get("dieta")
    diet = diet_legend.get(diet_code) if diet_code else None

    if authoritative:
        price = parse_decimal_cz(raw.get("cena"))
        # ``or 0`` rather than a ``get`` default: upstream sends these keys as
        # JSON ``null`` as well as omitting them, and a None here would escape
        # into ``DayMenu.ordered_option``, where ``None > 0`` raises TypeError
        # from inside a property -- i.e. an unreadable entity, not a bad value.
        ordered = int(raw.get("objednavka") or 0)
        remaining = raw.get("zbyva")
        remaining = None if remaining is None or int(remaining) == -1 else int(remaining)
    else:
        price = None
        ordered = 0
        remaining = None

    return MenuOption(
        key=key,
        label=raw["dMenu"],
        name=raw["nazev"],
        allergens=names,
        allergen_codes=codes,
        diet=diet,
        price=price,
        ordered=ordered,
        remaining=remaining,
        db_id=raw["dbId"],
        is_primary=bool(raw.get("isFirst")),
    )


def _parse_day(
    raw: dict,
    date: datetime.date,
    *,
    allergen_legend: Mapping[str, str],
    diet_legend: Mapping[str, str],
    authoritative: bool,
) -> DayMenu:
    """Parse a single denMap entry into a DayMenu."""
    options = tuple(
        _parse_option(
            key,
            option,
            allergen_legend=allergen_legend,
            diet_legend=diet_legend,
            authoritative=authoritative,
        )
        for key, option in raw.get("menuMap", {}).items()
    )
    return DayMenu(
        date=date,
        weekday_label=raw.get("datumden", ""),
        soups=_parse_soups(raw.get("polevka"), allergen_legend),
        dessert=_clean_text(raw.get("zakusek")),
        drink=_clean_text(raw.get("napoj")),
        options=options,
        is_blocked=raw.get("barva") == "B",
    )


def parse_canteen(payload: dict, *, authoritative: bool = False) -> Canteen:
    """Map an extracted E-jídelníček payload into a frozen Canteen.

    With ``authoritative=False`` (the public page) ``price``, ``remaining``
    and ``ordered`` are forced to unknown/zero-order values, because the
    public payload always carries ``cena: "0.00"`` and ``zbyva: 0`` and
    reporting those verbatim would misrepresent them as real prices or a
    sold-out meal. With ``authoritative=True`` (the AJAX response) these
    fields are mapped for real, with ``zbyva == -1`` mapped to ``None``
    (meaning "not tracked").
    """
    allergen_legend: Mapping[str, str] = payload.get("alergenyMap", {})
    diet_legend: Mapping[str, str] = payload.get("dietyMap", {})

    meal_types = []
    for index, strava in payload.get("stravaMap", {}).items():
        days: dict[datetime.date, DayMenu] = {}
        for date_key, day_raw in strava.get("denMap", {}).items():
            try:
                date = datetime.date.fromisoformat(date_key)
            except ValueError:
                continue
            days[date] = _parse_day(
                day_raw,
                date,
                allergen_legend=allergen_legend,
                diet_legend=diet_legend,
                authoritative=authoritative,
            )
        meal_types.append(
            MealType(
                index=index,
                strava_id=strava["id"],
                name=strava.get("nazev", ""),
                order_day_offset=strava.get("posunDne", 0),
                days=days,
            )
        )

    return Canteen(
        allergens=allergen_legend,
        diets=diet_legend,
        meal_types=tuple(meal_types),
    )


def parse_diner(stravnik: dict) -> Diner:
    """Map a ``stravnik`` object into a frozen Diner.

    Deliberately ignores identifying fields (``jmeno``, ``cislo``, ``vs``,
    ``loginEmail``) present on the real upstream object: Diner has no fields
    for them, which is what stops them leaking into entity attributes,
    diagnostics or logs. Missing keys yield None rather than raising.
    """
    return Diner(
        balance=parse_decimal_cz(stravnik.get("konto")),
        balance_meals=parse_decimal_cz(stravnik.get("kontoStravne")),
        balance_tuition=parse_decimal_cz(stravnik.get("kontoSkolne")),
        in_debt=stravnik.get("dluh"),
        ordering_disabled=stravnik.get("bezObjednavani"),
    )


def parse_ajax(body: str) -> tuple[Canteen, Diner | None]:
    """Parse the JSON body of an authenticated AJAX response.

    The body has the shape ``{"jidelnicek": {...}, "stravnik": {...}}``. The
    canteen is parsed with ``authoritative=True`` since this response carries
    real order, price and remaining-count data. ``diner`` is None when
    ``stravnik`` is missing or not a dict.

    Raises PayloadNotFound if the body is not valid JSON or has no usable
    ``jidelnicek`` object.
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as err:
        raise PayloadNotFound(f"body is not valid JSON: {err}") from err

    jidelnicek = payload.get("jidelnicek") if isinstance(payload, dict) else None
    if not isinstance(jidelnicek, dict):
        raise PayloadNotFound("no usable jidelnicek object found")

    canteen = parse_canteen(jidelnicek, authoritative=True)

    stravnik = payload.get("stravnik")
    diner = parse_diner(stravnik) if isinstance(stravnik, dict) else None

    return canteen, diner


def merge_day(base: DayMenu, authoritative: DayMenu) -> DayMenu:
    """Overlay authoritative per-option order data onto a public base day.

    Iterates the base day's options and, for each option whose key also
    appears in the authoritative day, overlays ``ordered``, ``price`` and
    ``remaining``. Everything else -- dish names, soups, dessert, drink,
    allergens -- comes from the base (public) day, which is the only source
    with full menu text. ``is_blocked`` is taken from the authoritative day.

    Base options whose key is absent from the authoritative day are kept,
    not dropped: real upstream data has shown the authoritative response
    can be terser than the public page for the same date.
    """
    authoritative_options = {option.key: option for option in authoritative.options}

    merged_options = []
    for option in base.options:
        auth_option = authoritative_options.get(option.key)
        if auth_option is None:
            merged_options.append(option)
        else:
            merged_options.append(
                replace(
                    option,
                    ordered=auth_option.ordered,
                    price=auth_option.price,
                    remaining=auth_option.remaining,
                )
            )

    return replace(
        base,
        options=tuple(merged_options),
        is_blocked=authoritative.is_blocked,
    )
