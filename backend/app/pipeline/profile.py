"""
TestSphere-AI — A project's test generation profile.

What the pipeline generates for a project, set once and used on every run
(the parameters commercial generators expose as plan scope, seed data and
review settings):

- ``test_types``  which kinds of tests to generate:
    smoke       the page loads (title, body)
    functional  the written goal / the page's form, and a login's successful sign-in
    negative    what must be refused: wrong password, empty or invalid form input
    content     the page shows its main heading
    pages       linked pages and code routes render
- ``test_data``   values to type, by field kind: username, password, email,
                  name, text (a search term or item to add).  The goal's own
                  values win when both give one.
- ``max_ai_tests`` how many tests the AI planner may add (0 = none)
- ``strict``      leave out tests that check nothing about the app's features
                  (only that a page renders)
- ``acceptance``  run each new or changed test once on a deliberately broken
                  copy of its page, to show whether it can fail at all

Every field has a default, so a project without a profile behaves as before.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

TestType = Literal["smoke", "functional", "negative", "content", "pages"]
ALL_TYPES: tuple[str, ...] = ("smoke", "functional", "negative", "content", "pages")
DATA_KEYS = ("username", "password", "email", "name", "text")
_NEGATIVE_SLUGS = ("wrong-password", "empty-submit", "password-mismatch", "invalid-email", "duplicate-email",
                   "password-masked", "form-required-empty", "form-invalid-email")


class GenerationProfile(BaseModel):
    test_types: list[TestType] = Field(default_factory=lambda: list(ALL_TYPES))
    test_data: dict[str, str] = Field(default_factory=dict)
    max_ai_tests: int = Field(5, ge=0, le=20)
    strict: bool = False
    acceptance: bool = True

    @field_validator("test_data")
    @classmethod
    def _known_keys(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = set(value) - set(DATA_KEYS)
        if unknown:
            raise ValueError(f"test_data keys must be among {', '.join(DATA_KEYS)} (not {', '.join(sorted(unknown))})")
        return {k: str(v)[:200] for k, v in value.items() if str(v).strip()}


def profile_of(project: dict[str, Any] | None) -> GenerationProfile:
    """The project's profile (defaults where unset or unreadable)."""
    raw = (project or {}).get("generation_profile")
    try:
        return GenerationProfile.model_validate(raw or {})
    except ValueError:
        return GenerationProfile()


def type_of(test: dict[str, Any]) -> str:
    """Which test type a planned test belongs to."""
    slug, category = str(test.get("slug") or ""), str(test.get("category") or "")
    if category in ("link", "route") or slug.startswith(("link-", "route-")):
        return "pages"
    if slug == "smoke":
        return "smoke"
    if slug == "content":
        return "content"
    if any(n in slug for n in _NEGATIVE_SLUGS):
        return "negative"
    return "functional"


_RENDER_ONLY = {("ASSERT_VISIBLE", "body"), ("ASSERT_VISIBLE", "html")}


def checks_a_feature(test: dict[str, Any]) -> bool:
    """Whether a test checks more than that a page renders."""
    for s in test.get("steps") or []:
        action = str(s.get("action", "")).upper()
        if action.startswith("ASSERT") and (action, str(s.get("target") or "").strip()) not in _RENDER_ONLY \
                and str(s.get("target") or "").strip() not in ("head > title", "title"):
            return True
    return False


def select(tests: list[dict[str, Any]], profile: GenerationProfile) -> list[dict[str, Any]]:
    """The planned tests this profile keeps (AI tests are limited by ``max_ai_tests``)."""
    kept, ai = [], 0
    for test in tests:
        if test.get("category") == "ai":
            ai += 1
            if ai > profile.max_ai_tests:
                continue
        elif type_of(test) not in profile.test_types:
            continue
        if profile.strict and not checks_a_feature(test):
            continue
        kept.append(test)
    return kept
