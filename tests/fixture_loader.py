"""Load test fixtures from disk."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

PUBLIC_FIXTURES: tuple[str, ...] = (
    "canteen_two_options.html",
    "canteen_single_option.html",
    "canteen_three_options.html",
    "canteen_long_window.html",
    "canteen_placeholder.html",
)


def load(name: str) -> str:
    """Return a fixture's text."""
    return (FIXTURES / name).read_text(encoding="utf-8")
