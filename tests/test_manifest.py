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
    assert "requirements" in data and data["requirements"] == []


def test_source_never_references_the_order_writing_endpoint():
    """menu-update places and cancels real orders. Phase 1 is read-only."""
    SCANNED_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md"}
    files = [
        p
        for p in Path("custom_components/ejidelnicek").rglob("*")
        if p.is_file() and p.suffix in SCANNED_SUFFIXES
    ]
    offenders = [p for p in files if "menu-update" in p.read_text(encoding="utf-8")]
    assert offenders == []


COMPONENT = Path("custom_components/ejidelnicek")


def _key_tree(value, prefix=""):
    """Flatten a JSON object into its set of dotted leaf paths."""
    if not isinstance(value, dict):
        return {prefix}
    keys = set()
    for key, child in value.items():
        keys |= _key_tree(child, f"{prefix}.{key}" if prefix else key)
    return keys


def test_all_translation_files_have_identical_keys():
    """strings.json, en.json and cs.json must not drift apart.

    A key present in one file and missing in another shows up for the user as
    an untranslated placeholder string, and only in the language nobody on the
    project happens to be testing in.
    """
    trees = {
        name: _key_tree(json.loads((COMPONENT / name).read_text(encoding="utf-8")))
        for name in ("strings.json", "translations/en.json", "translations/cs.json")
    }
    reference = trees["strings.json"]
    for name, tree in trees.items():
        assert tree == reference, f"{name} differs: {tree ^ reference}"


def test_icons_json_matches_the_entity_translation_keys():
    """Every icon must name an entity that exists, and every entity an icon."""
    icons = json.loads((COMPONENT / "icons.json").read_text(encoding="utf-8"))
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))

    def entity_keys(entity_section):
        return {(platform, key) for platform, keys in entity_section.items() for key in keys}

    assert entity_keys(icons["entity"]) == entity_keys(strings["entity"])
