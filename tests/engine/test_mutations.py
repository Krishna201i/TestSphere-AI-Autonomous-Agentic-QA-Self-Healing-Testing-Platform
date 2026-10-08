"""
tests/engine/test_mutations.py
==============================
Verifies the mutation generator:

1. All expected mutant directories exist after generation.
2. Every healable mutant contains expected_element_marker exactly once.
3. No non-healable mutant contains expected_element_marker (it's empty string,
   so this check is skipped — we only assert the element we expect gone IS gone).
4. The generator is deterministic: two runs produce bit-for-bit identical files.
5. mutants.json is valid and contains all required fields.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tests.engine.mutations import (
    MANIFEST_PATH,
    MUTATIONS_DIR,
    generate,
)

_REQUIRED_FIELDS = {
    "name",
    "change_type",
    "expected_to_heal",
    "target_step_id",
    "expected_element_marker",
    "source_file",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest() -> list[dict]:
    """Generate mutants once for the whole module."""
    return generate()


@pytest.fixture(scope="module")
def manifest_healable(manifest) -> list[dict]:
    return [m for m in manifest if m["expected_to_heal"]]


@pytest.fixture(scope="module")
def manifest_no_heal(manifest) -> list[dict]:
    return [m for m in manifest if not m["expected_to_heal"]]


# ---------------------------------------------------------------------------
# Basic manifest structure
# ---------------------------------------------------------------------------


def test_manifest_written(manifest):
    assert MANIFEST_PATH.exists(), "mutants.json not written"


def test_manifest_count(manifest):
    assert len(manifest) >= 12, f"Expected ≥12 mutants, got {len(manifest)}"


def test_manifest_has_no_heal(manifest_no_heal):
    assert len(manifest_no_heal) >= 2, "Need ≥2 must-not-heal mutants"


def test_manifest_fields(manifest):
    for entry in manifest:
        missing = _REQUIRED_FIELDS - entry.keys()
        assert not missing, f"Mutant '{entry.get('name')}' missing fields: {missing}"


def test_no_duplicate_names(manifest):
    names = [m["name"] for m in manifest]
    assert len(names) == len(set(names)), "Duplicate mutant names found"


# ---------------------------------------------------------------------------
# Directory & file existence
# ---------------------------------------------------------------------------


def test_all_dirs_exist(manifest):
    for m in manifest:
        d = MUTATIONS_DIR / m["name"]
        assert d.is_dir(), f"Missing mutant dir: {d}"


def test_all_source_files_exist(manifest):
    for m in manifest:
        f = MUTATIONS_DIR / m["name"] / m["source_file"]
        assert f.is_file(), f"Missing mutated file: {f}"


def test_companion_files_exist(manifest):
    """The unmodified companion page must also be present."""
    for m in manifest:
        companion = "dashboard.html" if m["source_file"] == "index.html" else "index.html"
        f = MUTATIONS_DIR / m["name"] / companion
        assert f.is_file(), f"Missing companion file: {f}"


# ---------------------------------------------------------------------------
# Marker presence
# ---------------------------------------------------------------------------


def test_healable_marker_exists_exactly_once(manifest_healable):
    for m in manifest_healable:
        marker = m["expected_element_marker"]
        assert marker, f"Healable mutant '{m['name']}' has empty marker"
        html = (MUTATIONS_DIR / m["name"] / m["source_file"]).read_text(encoding="utf-8")
        count = html.count(marker)
        assert count == 1, (
            f"Mutant '{m['name']}': marker {marker!r} "
            f"found {count} times (expected exactly 1)"
        )


def test_no_heal_marker_is_empty(manifest_no_heal):
    """Non-healable mutants must declare empty marker (no valid healing target)."""
    for m in manifest_no_heal:
        assert m["expected_element_marker"] == "", (
            f"Non-healable mutant '{m['name']}' should have empty marker"
        )


# ---------------------------------------------------------------------------
# Determinism: two runs produce identical files
# ---------------------------------------------------------------------------


def _dir_hash(directory: Path) -> str:
    """Stable hash over all file contents in a directory tree."""
    h = hashlib.sha256()
    for f in sorted(directory.rglob("*")):
        if f.is_file() and f.name != "mutants.json":  # manifest has no content instability
            h.update(f.relative_to(directory).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def test_deterministic(tmp_path, manifest):
    """Second generate() call produces identical file tree."""
    first_hash = _dir_hash(MUTATIONS_DIR)

    # Wipe and regenerate
    shutil.rmtree(MUTATIONS_DIR)
    generate()

    second_hash = _dir_hash(MUTATIONS_DIR)
    assert first_hash == second_hash, "Generator is not deterministic — hashes differ"


# ---------------------------------------------------------------------------
# Spot-check specific mutants
# ---------------------------------------------------------------------------


def test_rename_id_login_btn():
    html = (MUTATIONS_DIR / "rename-id-login-btn" / "index.html").read_text(encoding="utf-8")
    assert 'id="login-btn"' not in html, "Old id should be gone"
    assert 'id="submit-btn"' in html, "New id should be present"
    assert 'data-testid="login-button"' in html, "Marker must survive rename"


def test_element_removed_no_marker():
    html = (MUTATIONS_DIR / "removed-login-btn" / "index.html").read_text(encoding="utf-8")
    # Button is completely gone — no submit button of any kind with this testid
    assert 'data-testid="login-button"' not in html


def test_button_to_anchor_tag():
    html = (MUTATIONS_DIR / "button-to-anchor" / "index.html").read_text(encoding="utf-8")
    assert "<a " in html and 'role="button"' in html
    assert 'data-testid="login-button"' in html


def test_reorder_stat_cards():
    html = (MUTATIONS_DIR / "reorder-stat-cards" / "dashboard.html").read_text(encoding="utf-8")
    fail_pos = html.index('id="fail-count"')
    test_pos = html.index('id="test-count"')
    assert fail_pos < test_pos, "fail-count should now appear before test-count"


def test_remove_testid_username():
    html = (MUTATIONS_DIR / "remove-testid-username" / "index.html").read_text(encoding="utf-8")
    assert 'data-testid="username-input"' not in html
    assert 'name="username"' in html, "name attr (the marker) must still be present"


def test_replaced_element_has_different_semantics():
    html = (MUTATIONS_DIR / "replaced-username-with-select" / "index.html").read_text(encoding="utf-8")
    assert "<select" in html
    assert 'data-testid="username-input"' not in html
