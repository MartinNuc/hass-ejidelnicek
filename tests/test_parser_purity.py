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
