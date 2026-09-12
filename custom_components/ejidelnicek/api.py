"""HTTP client for the E-jídelníček system.

Owns every network call the integration makes: resolving a user-supplied
base URL into candidate ``.../ejidelnicek/`` URLs, fetching and parsing the
public menu page, logging in via classic Spring Security form auth, fetching
per-day authoritative order data over AJAX, and assembling a self-consistent
``Snapshot`` for the coordinator.

Request budget (see ``EjidelnicekClient.async_fetch_snapshot``):
  * No credentials: exactly one request (``GET menu/``).
  * With credentials, steady state (session already valid): three requests
    -- one ``GET menu/`` plus one ``GET ajax/get-jidelnicek`` per distinct
    date needed (today and each meal type's next serving day -- strictly
    after today, see ``MealType.next_serving_day`` -- deduplicated and
    restricted to dates the canteen actually publishes). Session login
    and recovery are paid for lazily, only when a request actually reveals
    the session is missing or has expired, so they are not part of this
    steady-state count.

``parser.py`` stays pure; all I/O -- and all exception translation from
``aiohttp``/parser exceptions into this module's error types -- lives here.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import aiohttp
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.util import dt as dt_util

from .models import Canteen, Diner, Snapshot
from .parser import PayloadNotFound, extract_payload, merge_day, parse_ajax, parse_canteen

if TYPE_CHECKING:
    from aiohttp import ClientSession
    from homeassistant.core import HomeAssistant

_MENU_PATH = "menu/"
_LOGIN_PATH = "logincheck"
_AJAX_DAY_PATH = "ajax/get-jidelnicek"


class EjidelnicekError(Exception):
    """Base error for this integration's API client."""


class CannotConnect(EjidelnicekError):
    """Raised when the site cannot be reached or returns a bad response."""


class InvalidAuth(EjidelnicekError):
    """Raised when login fails or a session cannot be recovered."""


class UnsupportedSite(EjidelnicekError):
    """Raised when a page has no usable E-jídelníček payload at all."""


class _SessionExpired(Exception):
    """Internal signal: the current session is missing or has expired.

    Never escapes this module -- it is always caught and translated into
    either a successful retry or ``InvalidAuth``.
    """


def async_new_session(hass: HomeAssistant, *, auto_cleanup: bool = True) -> ClientSession:
    """Create a session that is this client's alone, with its own cookie jar.

    Never ``async_get_clientsession``: that session is shared by every
    integration in the instance and, as of HA 2026.2, is created with no
    ``cookie_jar`` argument, so all of them share one
    ``aiohttp.CookieJar(unsafe=False)``. This client keeps its ``JSESSIONID``
    in the session's jar, which makes that sharing actively wrong twice over:

    * ``CookieJar.update_cookies`` returns early for an IP-address host when
      the jar is not ``unsafe``, so the session cookie is silently dropped --
      and several E-jídelníček deployments are reachable only by a LAN IP.
      A credentialed entry there could never authenticate: it would log in,
      lose the cookie, look session-expired, re-login, and finally raise
      ``InvalidAuth`` into a reauth dialog no correct password could satisfy.
    * Two diners at one school are two config entries against one host. On a
      shared jar, whichever logged in last owns the ``JSESSIONID``; the other
      entry sees a *valid* session for the wrong diner and silently reports
      its sibling's orders, balance and debt as its own.

    ``auto_cleanup`` is left on for a config entry (HA then detaches the
    session when the entry unloads); callers outside an entry -- the config
    flow -- pass ``False`` and ``detach()`` the session themselves.
    """
    return async_create_clientsession(
        hass,
        cookie_jar=aiohttp.CookieJar(unsafe=True),
        auto_cleanup=auto_cleanup,
    )


def _contains_login_form(text: str) -> bool:
    """Return True if the response text looks like the login page."""
    return "loginForm" in text


def _contains_payload(text: str) -> bool:
    """Return True if the response text carries a setJidelnicek(...) call."""
    return "setJidelnicek(" in text


def _normalise(scheme: str, rest: str) -> str:
    """Build one ``scheme://host[:port]/ejidelnicek/`` candidate from a raw host/path.

    The ``ejidelnicek`` path segment is matched case-insensitively: a user who
    pastes ``HTTPS://X.CZ/EJIDELNICEK/`` out of a browser bar would otherwise
    get ``.../EJIDELNICEK/ejidelnicek/`` appended and a confusing
    ``cannot_connect``. The segment is kept with the casing the user typed,
    since only the server knows whether its path is case-sensitive.
    """
    rest = rest.strip().strip("/")
    host, _, path = rest.partition("/")
    segments = [segment for segment in path.split("/") if segment]
    lowered = [segment.lower() for segment in segments]
    if "ejidelnicek" in lowered:
        segments = segments[: lowered.index("ejidelnicek") + 1]
    else:
        segments.append("ejidelnicek")
    return f"{scheme}://{host}/{'/'.join(segments)}/"


def candidate_base_urls(raw: str) -> tuple[str, ...]:
    """Normalise a user-supplied URL/host into candidate ``.../ejidelnicek/`` bases.

    Accepts a bare host, ``.../ejidelnicek``, ``.../ejidelnicek/`` or
    ``.../ejidelnicek/menu/`` and normalises any of them to a base ending in
    ``/ejidelnicek/``. When the input carries no scheme, the ``https``
    candidate is returned first and ``http`` second, since several
    deployments are http-only. When a scheme is given, it is respected and
    exactly one candidate is returned.
    """
    raw = raw.strip()
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        return (_normalise(scheme, rest),)
    return (_normalise("https", raw), _normalise("http", raw))


def _dates_to_fetch(canteen: Canteen, today: datetime.date) -> tuple[datetime.date, ...]:
    """Return the dates worth an authoritative AJAX fetch: today plus each meal
    type's next serving day, deduplicated and restricted to published dates.
    """
    published: set[datetime.date] = set()
    for meal_type in canteen.meal_types:
        published.update(meal_type.days)

    wanted: set[datetime.date] = set()
    if today in published:
        wanted.add(today)
    for meal_type in canteen.meal_types:
        day = meal_type.next_serving_day(today)
        if day is not None:
            wanted.add(day.date)

    return tuple(sorted(wanted))


def _merge_canteen(base: Canteen, authoritative: Canteen) -> Canteen:
    """Overlay an authoritative canteen's days onto a public base canteen.

    Matches meal types by ``index``. Days present in both are merged with
    ``merge_day`` (public text, authoritative order/price/blocked data); days
    only present in the authoritative canteen are added as-is; days only in
    the base are kept untouched.
    """
    merged_meal_types = []
    for meal_type in base.meal_types:
        auth_meal_type = authoritative.meal_type_by_index(meal_type.index)
        if auth_meal_type is None:
            merged_meal_types.append(meal_type)
            continue
        merged_days = dict(meal_type.days)
        for date_value, auth_day in auth_meal_type.days.items():
            base_day = merged_days.get(date_value)
            merged_days[date_value] = (
                auth_day if base_day is None else merge_day(base_day, auth_day)
            )
        merged_meal_types.append(replace(meal_type, days=merged_days))
    return replace(base, meal_types=tuple(merged_meal_types))


def menu_is_empty(canteen: Canteen) -> bool:
    """Return True if the canteen appears to publish no real menu at all.

    This is the signal for a canteen (typically a kindergarten) that publishes
    nothing publicly and requires credentials to see anything: every day is a
    single placeholder option (upstream literally names it "Přihlásit" -- "Log
    in") with no soup, dessert or drink.

    Both halves matter. Soups/dessert/drink alone would misfire on a canteen
    that genuinely serves nothing but a main course -- ``canteen_long_window``
    already has days in exactly that shape -- and a day offering a *choice* of
    options is self-evidently a real published menu whatever else is missing.

    Public because it is evaluated on every setup (``__init__.py``) against
    the *current* snapshot, not once during the config flow: a canteen that
    starts publishing must make the resulting Repairs issue go away by itself.
    """
    for meal_type in canteen.meal_types:
        for day in meal_type.days.values():
            if day.soups or day.dessert or day.drink or len(day.options) > 1:
                return False
    return True


class EjidelnicekClient:
    """Thin async HTTP client for one E-jídelníček deployment."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._session = session
        self.base_url = base_url
        self._username = username
        self._password = password

    @property
    def has_credentials(self) -> bool:
        """Return True if both a username and a password were supplied."""
        return bool(self._username) and bool(self._password)

    async def _get(self, url: str) -> tuple[int, str]:
        """GET a URL, mapping connection failures to CannotConnect."""
        try:
            async with self._session.get(url) as response:
                return response.status, await response.text()
        except TimeoutError as err:
            raise CannotConnect(f"timeout requesting {url}") from err
        except aiohttp.ClientError as err:
            raise CannotConnect(f"connection error requesting {url}") from err

    async def _get_text(self, url: str) -> str:
        """GET a URL and return its body, mapping a non-2xx status to CannotConnect."""
        status, text = await self._get(url)
        if status >= 300:
            raise CannotConnect(f"unexpected status {status} for {url}")
        return text

    async def async_fetch_public(self) -> Canteen:
        """Fetch and parse the public menu page. Exactly one HTTP request."""
        text = await self._get_text(self.base_url + _MENU_PATH)
        try:
            payload = extract_payload(text)
        except PayloadNotFound as err:
            raise UnsupportedSite(str(err)) from err
        return parse_canteen(payload, authoritative=False)

    async def async_login(self) -> None:
        """Log in via classic Spring Security form auth (``j_username``/``j_password``).

        Success is detected positively: the logincheck response carries a
        usable payload, or at least does not look like the login page again.
        Anything else raises InvalidAuth.
        """
        await self._get_text(self.base_url)
        try:
            async with self._session.post(
                self.base_url + _LOGIN_PATH,
                data={"j_username": self._username, "j_password": self._password},
            ) as response:
                status = response.status
                text = await response.text()
        except TimeoutError as err:
            raise CannotConnect("timeout during login") from err
        except aiohttp.ClientError as err:
            raise CannotConnect("connection error during login") from err
        if status >= 300:
            raise CannotConnect(f"unexpected status {status} during login")
        if _contains_login_form(text) and not _contains_payload(text):
            raise InvalidAuth("login failed: credentials were rejected")

    async def _fetch_day_once(self, url: str) -> tuple[Canteen, Diner | None]:
        """Fetch one AJAX day, raising _SessionExpired if the session looks dead."""
        try:
            async with self._session.get(url) as response:
                status = response.status
                text = await response.text()
        except TimeoutError as err:
            raise CannotConnect(f"timeout requesting {url}") from err
        except aiohttp.ClientError as err:
            raise CannotConnect(f"connection error requesting {url}") from err

        if status in (302, 400) or _contains_login_form(text):
            raise _SessionExpired
        if status >= 300:
            raise CannotConnect(f"unexpected status {status} for {url}")
        try:
            return parse_ajax(text)
        except PayloadNotFound as err:
            raise CannotConnect(f"malformed authenticated response: {err}") from err

    async def async_fetch_day(self, value: datetime.date) -> tuple[Canteen, Diner | None]:
        """Fetch the authoritative AJAX day for ``value``.

        On a session that is missing or has expired (a redirect back to the
        login page, or a 400/302 from this endpoint), re-logs in exactly once
        and retries exactly once; if that still fails, raises InvalidAuth.
        """
        url = f"{self.base_url}{_AJAX_DAY_PATH}?datum={value.isoformat()}"
        try:
            return await self._fetch_day_once(url)
        except _SessionExpired:
            pass
        await self.async_login()
        try:
            return await self._fetch_day_once(url)
        except _SessionExpired as err:
            raise InvalidAuth("session could not be recovered") from err

    async def async_fetch_snapshot(self, today: datetime.date | None = None) -> Snapshot:
        """Assemble a self-consistent Snapshot.

        ``today`` governs which days are worth an authoritative fetch and
        defaults to ``date.today()``; callers running inside Home Assistant
        should pass ``dt_util.now().date()`` so HA's configured timezone
        governs instead of the process timezone.
        """
        if today is None:
            today = datetime.date.today()

        canteen = await self.async_fetch_public()
        diner: Diner | None = None

        if self.has_credentials:
            for value in _dates_to_fetch(canteen, today):
                auth_canteen, auth_diner = await self.async_fetch_day(value)
                canteen = _merge_canteen(canteen, auth_canteen)
                if auth_diner is not None:
                    diner = auth_diner

        return Snapshot(canteen=canteen, diner=diner, fetched_at=dt_util.utcnow())


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of validating a base URL and optional credentials."""

    base_url: str
    canteen: Canteen
    diner: Diner | None


async def async_validate(
    session: ClientSession,
    raw_url: str,
    username: str | None,
    password: str | None,
) -> ValidationResult:
    """Resolve ``raw_url`` and validate it (and any credentials) against the site.

    Walks ``candidate_base_urls`` in order and returns on the first candidate
    that yields a payload; if none do, re-raises the last CannotConnect or
    UnsupportedSite encountered. A failed login raises InvalidAuth
    immediately -- once a candidate has produced a payload, the URL itself is
    known good, so a credentials problem should not trigger trying another
    URL scheme.
    """
    last_error: EjidelnicekError | None = None
    # Home Assistant's configured timezone, not the process timezone: the same
    # ``today`` the coordinator passes, so validation fetches the same days a
    # real refresh would.
    today = dt_util.now().date()
    for base_url in candidate_base_urls(raw_url):
        client = EjidelnicekClient(session, base_url, username, password)
        try:
            snapshot = await client.async_fetch_snapshot(today=today)
        except (CannotConnect, UnsupportedSite) as err:
            last_error = err
            continue
        return ValidationResult(
            base_url=base_url,
            canteen=snapshot.canteen,
            diner=snapshot.diner,
        )
    if last_error is None:
        raise CannotConnect(f"no candidate base url could be resolved from {raw_url!r}")
    raise last_error
