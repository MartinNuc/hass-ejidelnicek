import json

from tests.fixture_loader import FIXTURES, PUBLIC_FIXTURES, load

# Strings that would identify which real school deployments the fixtures were
# trimmed from. None of these may appear in any committed fixture file.
SCHOOL_IDENTIFYING_STRINGS = (
    "letohrad",
    "stross",
    "betlemska",
    "jakutska",
    "jesenice",
    "zs-stross",
    "sjp10",
    "e-jidelnicek.eu",
)


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


def test_no_fixture_reveals_which_school_it_came_from():
    """Fixtures are anonymised by shape, not by school. This must stay true."""
    for path in sorted(FIXTURES.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for needle in SCHOOL_IDENTIFYING_STRINGS:
            assert needle not in text, f"{path.relative_to(FIXTURES)} contains {needle!r}"
