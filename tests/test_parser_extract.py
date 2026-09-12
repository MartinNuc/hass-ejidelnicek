import pytest

from custom_components.ejidelnicek.parser import PayloadNotFound, extract_payload
from tests.fixture_loader import PUBLIC_FIXTURES, load


@pytest.mark.parametrize("name", PUBLIC_FIXTURES)
def test_extracts_a_payload_from_every_real_deployment(name):
    payload = extract_payload(load(name))
    assert "stravaMap" in payload
    assert "alergenyMap" in payload


def test_stops_at_the_matching_brace_not_the_last_one():
    html = 'x = ejidelnicek.setJidelnicek({"a": {"b": 1}}); more(); }'
    assert extract_payload(html) == {"a": {"b": 1}}


def test_braces_inside_strings_do_not_end_the_payload():
    html = 'ejidelnicek.setJidelnicek({"nazev": "Gulas {domaci}", "n": 2});'
    assert extract_payload(html)["nazev"] == "Gulas {domaci}"


def test_escaped_quote_inside_a_string_is_handled():
    html = r'ejidelnicek.setJidelnicek({"nazev": "rizek \"domaci\"", "n": 1});'
    assert extract_payload(html)["nazev"] == 'rizek "domaci"'


def test_missing_payload_raises_payload_not_found():
    with pytest.raises(PayloadNotFound):
        extract_payload(load("not_ejidelnicek.html"))


def test_unbalanced_payload_raises_payload_not_found():
    with pytest.raises(PayloadNotFound):
        extract_payload('ejidelnicek.setJidelnicek({"a": 1')


def test_escaped_backslash_before_closing_quote_does_not_swallow_it():
    """A string ending in a literal backslash (JSON `\\\\`) must still end at the next quote."""
    html = r'ejidelnicek.setJidelnicek({"nazev": "path\\", "n": 1});'
    assert extract_payload(html)["nazev"] == "path\\"


@pytest.mark.parametrize(
    "html",
    [
        "ejidelnicek.setJidelnicek([1,2]);",
        "ejidelnicek.setJidelnicek();",
    ],
)
def test_non_object_argument_raises_payload_not_found(html):
    with pytest.raises(PayloadNotFound):
        extract_payload(html)
