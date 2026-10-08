"""
tests/engine/mutations.py
=========================
Generates mutated copies of demo_app/{index,dashboard}.html into
tests/engine/demo_app/mutations/<name>/.

Each mutant applies ONE structural change to exercise the self-healing engine.

Usage
-----
    python tests/engine/mutations.py            # generate all mutants
    python -m pytest tests/engine/test_mutations.py   # verify manifest

Determinism
-----------
Output is pure string-substitution — no randomness. Re-running produces
identical files. The manifest (mutants.json) is written atomically via a
temp-file rename to avoid partial writes.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
DEMO_APP = _HERE / "demo_app"
MUTATIONS_DIR = DEMO_APP / "mutations"

INDEX_SRC = DEMO_APP / "index.html"
DASH_SRC = DEMO_APP / "dashboard.html"

MANIFEST_PATH = MUTATIONS_DIR / "mutants.json"

# ---------------------------------------------------------------------------
# Mutant definitions
# ---------------------------------------------------------------------------
# Each entry: (name, change_type, source_file, patch_fn, expected_to_heal,
#              target_step_id, expected_element_marker)
#
# patch_fn(html: str) -> str  — pure transformation, no side effects.
# expected_element_marker: a unique attribute value present exactly once on
#   the correct element in *healable* mutants (used to detect false heals).
# ---------------------------------------------------------------------------


def _rename_id(html: str, old: str, new: str) -> str:
    """Replace id="old" → id="new" and for="old" → for="new"."""
    html = html.replace(f'id="{old}"', f'id="{new}"')
    html = html.replace(f"id='{old}'", f"id='{new}'")
    html = html.replace(f'for="{old}"', f'for="{new}"')
    # Update JS references too so the page still works
    html = html.replace(f"getElementById('{old}')", f"getElementById('{new}')")
    return html


def _rename_class(html: str, old: str, new: str) -> str:
    """Replace class="old" → class="new" (exact class match only)."""
    html = html.replace(f'class="{old}"', f'class="{new}"')
    return html


def _change_text(html: str, old: str, new: str) -> str:
    return html.replace(old, new, 1)


def _remove_data_testid(html: str, testid: str) -> str:
    """Strip data-testid="<testid>" from the element that carries it."""
    return html.replace(f' data-testid="{testid}"', "")


def _change_placeholder(html: str, old: str, new: str) -> str:
    return html.replace(f'placeholder="{old}"', f'placeholder="{new}"', 1)


def _change_name_attr(html: str, old: str, new: str) -> str:
    return html.replace(f'name="{old}"', f'name="{new}"', 1)


def _button_to_anchor(html: str, btn_id: str, text: str) -> str:
    """Change <button id="...">text</button> → <a role="button" id="...">text</a>."""
    old = f'<button id="{btn_id}" type="submit" data-testid="login-button">\n        {text}\n      </button>'
    new = (
        f'<a role="button" id="{btn_id}" data-testid="login-button" href="#" '
        f'onclick="document.getElementById(\'login-form\').dispatchEvent(new Event(\'submit\'))">'
        f'\n        {text}\n      </a>'
    )
    return html.replace(old, new)


def _wrap_in_div(html: str, inner_open: str, wrapper_attrs: str = "") -> str:
    """Wrap the first occurrence of inner_open's element in an extra div."""
    idx = html.find(inner_open)
    if idx == -1:
        return html
    return html[:idx] + f"<div{' ' + wrapper_attrs if wrapper_attrs else ''}>" + html[idx:]


def _move_element(html: str, element_snippet: str, before_marker: str) -> str:
    """Remove element_snippet and re-insert it before before_marker."""
    html = html.replace(element_snippet, "", 1)
    return html.replace(before_marker, element_snippet + "\n" + before_marker, 1)


def _reorder_siblings(html: str, first: str, second: str) -> str:
    """Swap positions of two adjacent sibling blocks."""
    if first not in html or second not in html:
        return html
    # Replace first with a placeholder, second with first, placeholder with second
    placeholder = "___REORDER_PLACEHOLDER___"
    html = html.replace(first, placeholder, 1)
    html = html.replace(second, first, 1)
    html = html.replace(placeholder, second, 1)
    return html


def _combined_id_class(html: str, old_id: str, new_id: str, old_cls: str, new_cls: str) -> str:
    html = _rename_id(html, old_id, new_id)
    html = _rename_class(html, old_cls, new_cls)
    return html


# ---------------------------------------------------------------------------
# "Must NOT heal" patches
# ---------------------------------------------------------------------------


def _remove_element(html: str, snippet: str) -> str:
    """Delete the element entirely — no valid healing target exists."""
    return html.replace(snippet, "", 1)


def _replace_with_different(html: str, snippet: str, replacement: str) -> str:
    """Swap element for a semantically different one."""
    return html.replace(snippet, replacement, 1)


# ---------------------------------------------------------------------------
# Mutant table
# ---------------------------------------------------------------------------
# Fields per row:
#   name, source ("index"|"dashboard"), change_type,
#   patch(html)->html, expected_to_heal,
#   target_step_id, expected_element_marker (attr=value, or "" if not healable)
# ---------------------------------------------------------------------------

_LOGIN_BTN_SNIPPET = (
    '<button id="login-btn" type="submit" data-testid="login-button">\n'
    "        Log in\n"
    "      </button>"
)

_USERNAME_SNIPPET = (
    '<input\n'
    '        id="username"\n'
    '        type="text"\n'
    '        name="username"\n'
    '        placeholder="admin"\n'
    '        autocomplete="username"\n'
    '        data-testid="username-input"\n'
    '      />'
)

_PASSWORD_SNIPPET = (
    '<input\n'
    '        id="password"\n'
    '        type="password"\n'
    '        name="password"\n'
    '        placeholder="••••••••"\n'
    '        autocomplete="current-password"\n'
    '        data-testid="password-input"\n'
    '      />'
)

_WELCOME_SNIPPET = '<p id="welcome-msg" data-testid="welcome-message">Welcome, admin!</p>'
_LOGOUT_SNIPPET = '<button id="logout-btn" data-testid="logout-button">Logout</button>'

_STAT_TEST_CARD = (
    '    <div class="stat-card" id="test-count" data-testid="test-count">\n'
    '      <div class="value">42</div>\n'
    '      <div class="label">Tests Run</div>\n'
    '    </div>'
)
_STAT_FAIL_CARD = (
    '    <div class="stat-card" id="fail-count" data-testid="fail-count">\n'
    '      <div class="value">3</div>\n'
    '      <div class="label">Failures</div>\n'
    '    </div>'
)


def _mutants() -> list[dict[str, Any]]:
    """Return mutant definitions. Called at generation time."""

    raw_index = INDEX_SRC.read_text(encoding="utf-8")
    raw_dash = DASH_SRC.read_text(encoding="utf-8")

    return [
        # ── 1. rename id ───────────────────────────────────────────────────
        {
            "name": "rename-id-login-btn",
            "source": "index",
            "change_type": "rename_id",
            "html": _rename_id(raw_index, "login-btn", "submit-btn"),
            "expected_to_heal": True,
            "target_step_id": "click-login",
            "expected_element_marker": 'data-testid="login-button"',
        },
        # ── 2. rename id on dashboard ───────────────────────────────────────
        {
            "name": "rename-id-welcome-msg",
            "source": "dashboard",
            "change_type": "rename_id",
            "html": _rename_id(raw_dash, "welcome-msg", "greeting-msg"),
            "expected_to_heal": True,
            "target_step_id": "assert-welcome",
            "expected_element_marker": 'data-testid="welcome-message"',
        },
        # ── 3. rename class ────────────────────────────────────────────────
        {
            "name": "rename-class-card",
            "source": "index",
            "change_type": "rename_class",
            "html": _rename_class(raw_index, "card", "login-card"),
            "expected_to_heal": True,
            "target_step_id": "fill-username",
            "expected_element_marker": 'data-testid="username-input"',
        },
        # ── 4. change visible text ─────────────────────────────────────────
        {
            "name": "change-text-login-btn",
            "source": "index",
            "change_type": "change_visible_text",
            "html": _change_text(raw_index, "Log in", "Sign In"),
            "expected_to_heal": True,
            "target_step_id": "click-login",
            "expected_element_marker": 'data-testid="login-button"',
        },
        # ── 5. move element to another container ───────────────────────────
        {
            "name": "move-error-msg-outside-form",
            "source": "index",
            "change_type": "move_element",
            "html": _move_element(
                raw_index,
                '      <p id="error-msg" role="alert" data-testid="error-message">\n'
                "        Invalid username or password.\n"
                "      </p>",
                "  </div>",  # place before closing .card div
            ),
            "expected_to_heal": True,
            "target_step_id": "assert-error",
            "expected_element_marker": 'data-testid="error-message"',
        },
        # ── 6. wrap in extra div ───────────────────────────────────────────
        {
            "name": "wrap-username-in-div",
            "source": "index",
            "change_type": "wrap_in_div",
            "html": raw_index.replace(
                '<label for="username">Username</label>',
                '<div class="field-wrapper"><label for="username">Username</label>',
                1,
            ).replace(
                '        data-testid="username-input"\n      />',
                '        data-testid="username-input"\n      /></div>',
                1,
            ),
            "expected_to_heal": True,
            "target_step_id": "fill-username",
            "expected_element_marker": 'data-testid="username-input"',
        },
        # ── 7. change tag: button → a[role=button] ─────────────────────────
        {
            "name": "button-to-anchor",
            "source": "index",
            "change_type": "change_tag",
            "html": _button_to_anchor(raw_index, "login-btn", "Log in"),
            "expected_to_heal": True,
            "target_step_id": "click-login",
            "expected_element_marker": 'data-testid="login-button"',
        },
        # ── 8. reorder siblings (stat cards) ──────────────────────────────
        {
            "name": "reorder-stat-cards",
            "source": "dashboard",
            "change_type": "reorder_siblings",
            "html": _reorder_siblings(raw_dash, _STAT_TEST_CARD, _STAT_FAIL_CARD),
            "expected_to_heal": True,
            "target_step_id": "assert-test-count",
            "expected_element_marker": 'data-testid="test-count"',
        },
        # ── 9. remove data-testid ──────────────────────────────────────────
        {
            "name": "remove-testid-username",
            "source": "index",
            "change_type": "remove_data_testid",
            "html": _remove_data_testid(raw_index, "username-input"),
            "expected_to_heal": True,
            "target_step_id": "fill-username",
            "expected_element_marker": 'name="username"',
        },
        # ── 10. change placeholder ─────────────────────────────────────────
        {
            "name": "change-placeholder-username",
            "source": "index",
            "change_type": "change_placeholder",
            "html": _change_placeholder(raw_index, "admin", "Enter username"),
            "expected_to_heal": True,
            "target_step_id": "fill-username",
            "expected_element_marker": 'data-testid="username-input"',
        },
        # ── 11. change name attribute ──────────────────────────────────────
        {
            "name": "change-name-password",
            "source": "index",
            "change_type": "change_name_attr",
            "html": _change_name_attr(raw_index, "password", "pass"),
            "expected_to_heal": True,
            "target_step_id": "fill-password",
            "expected_element_marker": 'data-testid="password-input"',
        },
        # ── 12. combined id + class change ─────────────────────────────────
        {
            "name": "combined-id-class-logout",
            "source": "dashboard",
            "change_type": "combined_id_class",
            "html": _combined_id_class(
                raw_dash,
                "logout-btn", "signout-btn",
                "welcome-banner", "welcome-section",
            ),
            "expected_to_heal": True,
            "target_step_id": "click-logout",
            "expected_element_marker": 'data-testid="logout-button"',
        },
        # ══ MUST NOT HEAL ══════════════════════════════════════════════════
        # ── 13. element removed entirely ──────────────────────────────────
        {
            "name": "removed-login-btn",
            "source": "index",
            "change_type": "element_removed",
            "html": _remove_element(raw_index, _LOGIN_BTN_SNIPPET),
            "expected_to_heal": False,
            "target_step_id": "click-login",
            "expected_element_marker": "",
        },
        # ── 14. element replaced with different element ────────────────────
        {
            "name": "replaced-username-with-select",
            "source": "index",
            "change_type": "element_replaced",
            "html": _replace_with_different(
                raw_index,
                _USERNAME_SNIPPET,
                (
                    '<select id="user-select" name="user-select" '
                    'data-testid="user-select">\n'
                    '        <option value="admin">admin</option>\n'
                    "      </select>"
                ),
            ),
            "expected_to_heal": False,
            "target_step_id": "fill-username",
            "expected_element_marker": "",
        },
        # ── 15. welcome element replaced with unrelated div ────────────────
        {
            "name": "replaced-welcome-msg",
            "source": "dashboard",
            "change_type": "element_replaced",
            "html": _replace_with_different(
                raw_dash,
                _WELCOME_SNIPPET,
                '<div id="promo-banner" data-testid="promo-banner">Upgrade to Pro!</div>',
            ),
            "expected_to_heal": False,
            "target_step_id": "assert-welcome",
            "expected_element_marker": "",
        },
    ]


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def generate(clean: bool = False) -> list[dict[str, Any]]:
    """Generate all mutant directories and write mutants.json.

    Parameters
    ----------
    clean:
        If True, wipe the mutations/ directory before regenerating.
        Defaults to False (idempotent: existing dirs are overwritten).

    Returns
    -------
    list[dict]
        The manifest entries written to mutants.json.
    """
    if clean and MUTATIONS_DIR.exists():
        shutil.rmtree(MUTATIONS_DIR)
    MUTATIONS_DIR.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []

    for m in _mutants():
        mutant_dir = MUTATIONS_DIR / m["name"]
        mutant_dir.mkdir(exist_ok=True)

        source_file = "index.html" if m["source"] == "index" else "dashboard.html"
        # Always copy the *other* file unchanged so both pages are present
        other_file = "dashboard.html" if source_file == "index.html" else "index.html"
        other_src = DEMO_APP / other_file
        shutil.copy2(other_src, mutant_dir / other_file)

        # Write the mutated HTML
        (mutant_dir / source_file).write_text(m["html"], encoding="utf-8")

        entry: dict[str, Any] = {
            "name": m["name"],
            "change_type": m["change_type"],
            "expected_to_heal": m["expected_to_heal"],
            "target_step_id": m["target_step_id"],
            "expected_element_marker": m["expected_element_marker"],
            "source_file": source_file,
        }
        manifest.append(entry)

    # Atomic write of manifest
    fd, tmp = tempfile.mkstemp(dir=MUTATIONS_DIR, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp, MANIFEST_PATH)
    except Exception:
        os.unlink(tmp)
        raise

    print(f"Generated {len(manifest)} mutants -> {MUTATIONS_DIR}")
    return manifest


if __name__ == "__main__":
    generate()
