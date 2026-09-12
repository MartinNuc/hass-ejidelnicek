"""Fixture invariants, including the repo-wide "no real school name" guard."""

import hashlib
import json
import subprocess
from pathlib import Path

from tests.fixture_loader import PUBLIC_FIXTURES, load

REPO_ROOT = Path(__file__).resolve().parent.parent

# SHA-256 digests of the lowercased strings that would identify which real
# school deployments the fixtures were trimmed from, as (length, digest) pairs.
#
# Digests rather than plaintext on purpose: a deny-list of real school
# hostnames is itself exactly the leak it exists to prevent -- it was the
# single most identifying thing in this repository. A substring search needs a
# window width, so the lengths are kept; a length on its own identifies
# nothing, and a digest cannot be reversed.
#
# To add a needle: hash the lowercased string with SHA-256 and append
# ``(len(needle), digest)``. Never commit the plaintext.
SCHOOL_IDENTIFYING_HASHES = frozenset(
    {
        (8, "4cca6217f5ad7c14b6118e648fd39f4805e64ace4f44ec7596e29a8afcff7513"),
        (6, "6603a3d16a960fd5d3e4fd8458a8835bf0943d3df3af25b59eb524462feeb45f"),
        (9, "fea101282ec813cde40b791454c9f1b8ea769ef5307753157895258970adec3e"),
        (8, "4ab79519c4f9fca72940b88e25676c455f1cc20f58cc06dcfba841f4dd76cf96"),
        (8, "08d213ce2dcd94e23b56ddcd32d495271fe371b5307d8b49c4758a9adf4f1b75"),
        (9, "0d5a99cd9a2cd592cdc9f5d5d502a07ce5710b591a778017eb03d85d710c823a"),
        (5, "24202eed198af9d8362b926f27a826d0a2c144c526904e5e070a184c529ba5c1"),
        (15, "ebcb24ae6f452208c8cf0a95b27e5c81e23d203bc474ae1273f2eff58802af5b"),
    }
)

# Every needle is drawn from this alphabet (lowercase hostname characters), so
# a candidate window can never straddle anything outside it. Restricting the
# search to maximal runs of these characters keeps the scan fast despite
# hashing every window.
_NEEDLE_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-")

# Directories that are never part of the published repository.
_SKIP_DIRS = frozenset({".git", ".venv", ".superpowers", "__pycache__", ".ruff_cache"})


def _tracked_files() -> list[Path]:
    """Return every tracked file in the repository.

    Falls back to a filesystem walk when ``git`` is unavailable, because a
    privacy guard that silently skips itself is worse than a slow one.
    """
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return [
            path
            for path in REPO_ROOT.rglob("*")
            if path.is_file() and not _SKIP_DIRS & set(path.relative_to(REPO_ROOT).parts)
        ]
    return [REPO_ROOT / name for name in listing.split("\0") if name]


def _windows(text: str, lengths: frozenset[int]) -> set[str]:
    """Return every substring of ``text`` whose length matches a needle's."""
    candidates: set[str] = set()
    for run in _runs(text):
        for length in lengths:
            candidates.update(run[i : i + length] for i in range(len(run) - length + 1))
    return candidates


def _runs(text: str) -> list[str]:
    """Split ``text`` into maximal runs of hostname characters."""
    runs: list[str] = []
    current: list[str] = []
    for char in text:
        if char in _NEEDLE_ALPHABET:
            current.append(char)
        elif current:
            runs.append("".join(current))
            current = []
    if current:
        runs.append("".join(current))
    return runs


def _identifying_hits(
    text: str, needle_hashes: frozenset[tuple[int, str]] = SCHOOL_IDENTIFYING_HASHES
) -> set[str]:
    """Return the digests of any denied strings ``text`` contains.

    Hash-based substring search: every window of every denied length is hashed
    and compared, which is exactly ``needle in text`` for each needle without
    the plaintext needles being present anywhere.
    """
    lengths = frozenset(length for length, _ in needle_hashes)
    digests = frozenset(digest for _, digest in needle_hashes)
    found = set()
    for window in _windows(text.lower(), lengths):
        digest = hashlib.sha256(window.encode("utf-8")).hexdigest()
        if digest in digests:
            found.add(digest)
    return found


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


def test_the_hash_based_substring_search_actually_finds_things():
    """A hashed deny-list is useless if the search silently matches nothing.

    Exercised with a sentinel hashed here rather than with a real needle: the
    committed digests cannot be verified against plaintext without the
    plaintext, which is the whole point of hashing them. What this pins down is
    the machinery -- window generation across hostname punctuation, the
    lowercasing, the digest comparison -- which is where a regression would
    actually turn the repo-wide scan below into a test that can never fail.
    """
    sentinel = "zx-quokka9.example"
    needle_hashes = frozenset(
        {(len(sentinel), hashlib.sha256(sentinel.encode("utf-8")).hexdigest())}
    )
    assert _identifying_hits("https://ZX-Quokka9.EXAMPLE/ejidelnicek/", needle_hashes)
    assert _identifying_hits(f"prefix{sentinel}suffix", needle_hashes)
    assert not _identifying_hits("https://school.example.cz/ejidelnicek/", needle_hashes)


def test_no_tracked_file_reveals_which_school_the_fixtures_came_from():
    """Fixtures are anonymised by shape, not by school -- and so is everything
    else that ships. The scan covers every tracked file, not just
    ``tests/fixtures/``: the identifying strings were previously sitting in a
    test's deny-list, in a comment table in another test, and in the spec and
    the plan, none of which the old fixtures-only scan could see.
    """
    offenders = []
    for path in sorted(_tracked_files()):
        if not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", "replace")
        if _identifying_hits(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"identifying school strings found in: {offenders}"
