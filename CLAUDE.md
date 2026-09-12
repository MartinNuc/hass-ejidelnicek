# Working on this repository

A Home Assistant custom integration that reads Czech school canteen menus
from the **E-jídelníček** system. Generic across schools, and read-only.

## Workflow

- **Commit directly to `main`.** No feature branch, no PR, unless the change
  is large enough that you want a review checkpoint — ask first in that case.
- Push to `origin` when the work is done and the suite is green.
- Releases are git tags (`vX.Y.Z`) plus a GitHub release; HACS installs from
  those. Bump `custom_components/ejidelnicek/manifest.json` `version` to match
  the tag in the same commit, or HACS and the manifest will disagree.

## Invariants — do not break these

1. **Read-only. Never call, construct, or reference `ajax/menu-update`.**
   That endpoint places *and cancels* real school lunch orders for a real
   child. Ordering is phase 2 and is not implemented. A test greps every
   `.py`/`.json`/`.yaml`/`.yml`/`.md` under `custom_components/` for the
   string; do not weaken it.
2. **Never commit credentials, personal data, or a real school hostname.**
   This repo is public. A test hashes the known school-identifying strings
   and scans every tracked file. Test fixtures are trimmed public payloads
   named by *shape* (`canteen_two_options.html`), never by school, and test
   hosts are `school.example.cz`.
3. **`parser.py` and `models.py` do no I/O** and import neither `aiohttp` nor
   `homeassistant`. That keeps the payload layer testable offline against
   real deployment data. A test enforces it by walking the AST.
4. **Order status comes only from `ajax/get-jidelnicek?datum=`**, never from
   an HTML page. The authenticated page fills in order data for just the one
   day its UI has selected and leaves every other day looking "not ordered".
5. **Absent data is `None`, never `0`.** The public view zeroes `cena` and
   `zbyva`; reporting `0` would read as "free" or "sold out".
6. **Allergen codes are base-36 characters** (`1`-`9` = 1-9, `A`-`S` = 10-28).
   A digit-wise split silently drops mustard, sesame, sulfites and every
   gluten sub-code. This is allergy-safety relevant; test against real fixture
   data, not only a synthetic legend.
7. **Each config entry gets its own aiohttp session** with
   `CookieJar(unsafe=True)`. Home Assistant's shared session drops cookies for
   IP-address hosts (real deployments exist on LAN IPs) and would let two
   children at one school share a `JSESSIONID` and report each other's data.

## Commands

```bash
.venv/bin/python -m pytest -q                                  # full suite
.venv/bin/python -m ruff check custom_components tests
.venv/bin/python -m ruff format --check custom_components tests
```

Dev dependencies are declared in `pyproject.toml` under `[dependency-groups]`;
install with `pip install --group dev` (pip >= 25.1) or `uv sync --group dev`.

## Layout

`parser.py` (pure: payload text → frozen dataclasses in `models.py`) ←
`api.py` (all HTTP, login, session recovery) ← `coordinator.py`
(`DataUpdateCoordinator[Snapshot]`) ← `sensor.py` / `binary_sensor.py` /
`calendar.py`, sharing `entity.py` (device info + local-midnight re-render).
Entity values are computed in properties, never cached, so "today" rolls over
at midnight without waiting for the 6-hour poll.

Design rationale and the verified upstream behaviour live in
`docs/superpowers/specs/`. Read that before changing parsing.
