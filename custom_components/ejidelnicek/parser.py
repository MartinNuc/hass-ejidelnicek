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

import json

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
