import ast
from pathlib import Path

import pytest

FORBIDDEN = {"aiohttp", "homeassistant", "requests", "urllib", "socket", "asyncio"}

# The model + parser layer must stay free of Home Assistant and of anything
# that does I/O: it is text in, frozen dataclasses out, and the spec's
# argument for one day extracting it as a plain PyPI package depends on that
# staying true. ``models.py`` is included because it briefly was not -- a
# ``slug`` property nobody used pulled in ``homeassistant.util.slugify``.
PURE_MODULES = ("parser.py", "models.py")


def _imported_top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text("utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    return imported


@pytest.mark.parametrize("module", PURE_MODULES)
def test_the_model_layer_is_pure_and_imports_nothing_that_does_io(module):
    """models.py and parser.py must stay offline-testable and HA-free."""
    path = Path("custom_components/ejidelnicek") / module
    assert _imported_top_level_names(path) & FORBIDDEN == set(), module
