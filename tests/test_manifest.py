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
