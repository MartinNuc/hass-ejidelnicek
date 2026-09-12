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
