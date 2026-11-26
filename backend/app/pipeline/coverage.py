"""
TestSphere-AI — The coverage suite: a test for each element a page shows.

``suite.py`` plans the run's core tests (smoke, the goal, a login's own
tests, linked pages).  This module adds breadth: for every page the run
analyzed (the start page and the linked pages it opened), one test per
thing a visitor relies on, built only from what the analysis saw on that
page and checked to be visible there.

- content        each heading is shown
- elements       each field is shown and takes what is typed; each button is
                 shown with its label; each dropdown option can be chosen;
                 each checkbox and radio button can be ticked (and cleared)
- validation     each field keeps its contract: still required, still an
                 email/number/... field, still limited to its maximum length
- navigation     each link is shown; clicking a same-site link opens its
                 page; the page survives a reload; Back returns to it
- accessibility  the page declares its language; each image keeps its alt
                 text; each field keeps its accessible name
- responsive     the page, opened at phone and tablet width, still shows its
                 headings (a layout that hides content on small screens fails)

A link or heading shared by every page (the site's header and footer) is
checked once, on the first page it appears on, not again on every page.

Rules every test follows (the same as the core suite's):

- it checks something a broken page gets wrong; a test that only finds the
  page body is never made;
- it never submits a form or presses a button: that could send mail, place
  an order or change data.  Clicking is limited to plain same-site links to
  pages that loaded without sending the visitor elsewhere;
- it only touches what the analysis saw.  Pages read without a browser
  (visibility not checked) still get their tests, quarantined: they run and
  report but cannot fail a run until someone trusts them.

Pure functions; slugs depend only on the page and the element, so a test
keeps its row (and its trusted/quarantined state) from run to run.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin, urlparse

from app.pipeline.suite import stable_headings
from engine.locators import css_string

CATEGORIES = ("content", "elements", "validation", "navigation", "accessibility", "responsive")
# Widths a visitor really uses (name, viewport): checked on every analyzed page
VIEWPORTS = (("phone", "390x844"), ("tablet", "768x1024"))
MAX_RESPONSIVE_HEADINGS = 3

# Per page, at most this many of each kind (a page with 300 links is not 300 tests)
MAX_HEADINGS = 20
MAX_FIELDS = 25
MAX_BUTTONS = 20
MAX_OPTIONS = 5
MAX_LINKS_SHOWN = 30
MAX_LINK_CLICKS = 15
MAX_IMAGES = 15

# What each kind of field is given to type (a browser refuses other values for most)
_TYPED = {
    "text": "TestSphere check 2026", "search": "TestSphere check", "textarea": "TestSphere check\nsecond line",
    "email": "qa.check@example.com", "password": "Ts-Check-2026!", "tel": "5551234567",
    "url": "https://example.com/", "number": "42", "date": "2026-01-15", "time": "12:30",
    "datetime-local": "2026-01-15T12:30", "month": "2026-01", "week": "2026-W03",
}
_TOGGLES = ("checkbox", "radio")
# Field types whose type attribute is a contract worth keeping (the keyboard,
# validation and autofill a visitor gets depend on it)
_TYPED_CONTRACT = ("email", "number", "tel", "url", "password", "date", "search")
# Never clicked, even when same-site: opening them changes state
_UNSAFE = re.compile(r"log-?out|sign-?out|delete|remove|unsubscribe|destroy|cancel", re.IGNORECASE)
# Links to files: a browser downloads them instead of opening a page
_FILE = re.compile(r"\.(pdf|zip|gz|tar|csv|xlsx?|docx?|pptx?|png|jpe?g|gif|svg|webp|mp4|mp3|dmg|exe|apk)$",
                   re.IGNORECASE)


def _step(n: int, action: str, *, target: str | None = None, value: str | None = None,
          description: str) -> dict[str, Any]:
    return {"step_number": n, "action": action, "target": target, "value": value, "description": description}


def _path(url: str) -> str:
    return (urlparse(url).path or "/").rstrip("/") or "/"


def _key(*parts: Any) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:10]


def _short(text: str, limit: int = 40) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _field_label(field: dict[str, Any]) -> str:
    return _short(field.get("aria_label") or field.get("placeholder") or field.get("name") or field.get("id")
                  or field.get("type") or "field", 32)


class _Builder:
    """The tests for one page."""

    def __init__(self, url: str, analysis: dict[str, Any], *, trusted: bool,
                 shared: dict[str, set[str]] | None = None) -> None:
        self.url = url
        self.path = _path(url)
        self.analysis = analysis
        self.trusted = trusted
        self.tests: list[dict[str, Any]] = []
        # What earlier pages already checked (the site's shared header and footer)
        self.shared = shared if shared is not None else {}

    def first_time(self, kind: str, key: str) -> bool:
        """Whether no earlier page checked this link or heading."""
        seen = self.shared.setdefault(kind, set())
        if key in seen:
            return False
        seen.add(key)
        return True

    def open(self) -> dict[str, Any]:
        return _step(1, "NAVIGATE", value=self.url, description=f"Open {self.url}")

    def add(self, category: str, kind: str, ident: Any, name: str, steps: list[dict[str, Any]],
            *, about: str, quarantined: bool = False, viewport: str | None = None) -> None:
        for i, s in enumerate(steps, start=1):
            s["step_number"] = i
        extra = {"viewport": viewport} if viewport else {}
        self.tests.append({**extra,
            "slug": f"cov-{kind}-{_key(self.path, kind, ident)}",
            "name": f"{name} · {self.path}"[:255],
            "category": category,
            "steps": steps,
            "page": self.path,
            "about": about,
            # Visibility unchecked (no browser read the page): runs, reports, cannot fail the run
            "quarantined": quarantined or not self.trusted,
        })

    # ── content ──
    def headings(self, skip_first: bool) -> None:
        seen: set[str] = set()
        for heading in stable_headings(self.analysis)[1 if skip_first else 0:]:
            text = _short(heading, 60).rstrip("…")
            if len(text) < 3 or text.lower() in seen or not self.first_time("heading", text.lower()):
                continue
            seen.add(text.lower())
            if len(seen) > MAX_HEADINGS:
                break
            self.add("content", "heading", text.lower(), f"Heading '{_short(text)}' is shown", [
                self.open(),
                _step(0, "ASSERT_CONTAINS_TEXT", target="body", value=text, description=f"Page shows '{text}'"),
            ], about="A heading a visitor reads is still on the page")

    # ── elements and validation ──
    def fields(self) -> None:
        inventory = self.analysis.get("elements_inventory") or {}
        fields = [f for f in inventory.get("inputs") or [] if f.get("selector")][:MAX_FIELDS]
        for field in fields:
            sel, kind, label = field["selector"], (field.get("type") or "text").lower(), _field_label(field)
            if kind == "select":
                self._select(field, label)
                continue
            if kind in _TOGGLES:
                self._toggle(field, label)
            elif kind in _TYPED and not field.get("readonly"):
                value = _TYPED[kind]
                if field.get("maxlength") and kind in ("text", "search", "textarea", "password"):
                    value = value[:field["maxlength"]]  # the browser stops typing at the limit
                self.add("elements", "field", sel, f"Field '{label}' is shown and accepts input", [
                    self.open(),
                    _step(0, "ASSERT_VISIBLE", target=sel, description=f"The {label} field is shown"),
                    _step(0, "FILL", target=sel, value=value, description=f"Type into {label}"),
                    _step(0, "ASSERT_VALUE", target=sel, value=value, description=f"{label} holds what was typed"),
                ], about="A visitor can see the field and type into it (nothing is submitted)")
            self._contracts(field, sel, kind, label)

    def attribute_kept(self, sel: str, attribute: str, shown: str, kept: str) -> list[dict[str, Any]]:
        """Steps checking the element is shown and still carries *attribute*
        (``required``, ``type="email"``).  The second check looks for a copy
        of the element without it: a hidden-check is never self-healed, so a
        dropped attribute fails the test instead of healing onto the element."""
        return [self.open(),
                _step(0, "ASSERT_VISIBLE", target=sel, description=shown),
                _step(0, "ASSERT_HIDDEN", target=f"{sel}:not([{attribute}])", description=kept)]

    def _contracts(self, field: dict[str, Any], sel: str, kind: str, label: str) -> None:
        if field.get("required"):
            self.add("validation", "required", sel, f"Field '{label}' is still required",
                     self.attribute_kept(sel, "required", f"The {label} field is shown",
                                         f"{label} is marked required (the form refuses it empty)"),
                     about="The form still refuses to be sent without this field")
        if kind in _TYPED_CONTRACT and not sel.endswith(f"[type={css_string(kind)}]"):
            self.add("validation", "type", sel, f"Field '{label}' is still a {kind} field",
                     self.attribute_kept(sel, f"type={css_string(kind)}", f"The {label} field is shown",
                                         f"{label} has type={kind} (its keyboard, checks and autofill)"),
                     about=f"The browser still checks and assists this field as {kind}")
        if field.get("maxlength"):
            n = field["maxlength"]
            self.add("validation", "maxlength", sel, f"Field '{label}' is limited to {n} characters",
                     self.attribute_kept(sel, f'maxlength="{n}"', f"The {label} field is shown",
                                         f"{label} accepts at most {n} characters"),
                     about="The length limit the back end expects is still enforced in the page")
        if field.get("aria_label"):
            self.add("accessibility", "field-name", sel, f"Field '{label}' keeps its accessible name",
                     self.attribute_kept(sel, f"aria-label={css_string(field['aria_label'])}",
                                         f"The {label} field is shown",
                                         f"{label} is announced to screen readers as '{_short(field['aria_label'])}'"),
                     about="Screen readers still announce what the field is for")

    def _select(self, field: dict[str, Any], label: str) -> None:
        sel = field["selector"]
        for option in (field.get("options") or ([field["option"]] if field.get("option") else []))[:MAX_OPTIONS]:
            self.add("elements", "option", (sel, option), f"Dropdown '{label}' can select '{_short(option, 24)}'", [
                self.open(),
                _step(0, "SELECT", target=sel, value=option, description=f"Choose '{option}' in {label}"),
                _step(0, "ASSERT_VALUE", target=sel, value=option, description=f"{label} shows '{option}'"),
            ], about="Each choice of the dropdown can be picked")
        self._contracts(field, sel, "select", label)

    def _toggle(self, field: dict[str, Any], label: str) -> None:
        sel, kind = field["selector"], field.get("type")
        steps = [self.open(),
                 _step(0, "ASSERT_VISIBLE", target=sel, description=f"The {label} choice is shown"),
                 _step(0, "CHECK", target=sel, description=f"Tick {label}"),
                 _step(0, "ASSERT_HIDDEN", target=f"{sel}:not(:checked)", description=f"{label} is ticked")]
        if kind == "checkbox":
            steps += [_step(0, "UNCHECK", target=sel, description=f"Clear {label}"),
                      _step(0, "ASSERT_HIDDEN", target=f"{sel}:checked", description=f"{label} is no longer ticked")]
        self.add("elements", kind or "toggle", sel,
                 f"{'Checkbox' if kind == 'checkbox' else 'Option'} '{label}' can be "
                 + ("ticked and cleared" if kind == "checkbox" else "chosen"),
                 steps, about="A visitor can make this choice")

    def buttons(self) -> None:
        inventory = self.analysis.get("elements_inventory") or {}
        seen: set[str] = set()
        for button in inventory.get("buttons") or []:
            sel = button.get("selector")
            if not sel or sel == "button" or sel in seen:
                continue
            seen.add(sel)
            if len(seen) > MAX_BUTTONS:
                break
            text = (button.get("text") or "").strip()
            steps = [self.open(), _step(0, "ASSERT_VISIBLE", target=sel, description=f"The '{_short(text) or sel}' button is shown")]
            if text and text != "Button" and len(text) >= 2:
                steps.append(_step(0, "ASSERT_CONTAINS_TEXT", target=sel, value=_short(text, 35).rstrip("…"),
                                   description=f"The button reads '{_short(text)}'"))
            self.add("elements", "button", sel, f"Button '{_short(text, 30) or sel}' is shown"
                     + (" with its label" if len(steps) > 2 else ""), steps,
                     about="The control is there to press (it is not pressed: that could change data)")

    # ── navigation ──
    def links(self, safe_paths: set[str]) -> None:
        inventory = self.analysis.get("elements_inventory") or {}
        origin = urlparse(self.url).netloc.lower()
        shown = clicked = 0
        for link in inventory.get("link_details") or []:
            href, sel = link.get("href") or "", link.get("selector")
            if not sel or href.lower().startswith(("mailto:", "tel:", "javascript:", "data:")):
                continue
            absolute = urljoin(self.url, href)
            dest = urlparse(absolute)
            same_site = dest.netloc.lower() == origin
            text = _short(link.get("text") or href, 30)
            if not self.first_time("link", absolute.split("#")[0]):
                continue  # the shared header or footer: checked on an earlier page
            if shown < MAX_LINKS_SHOWN:
                shown += 1
                where = _path(absolute) if same_site else dest.netloc
                self.add("navigation", "link", href, f"Link '{text}' is shown", [
                    self.open(),
                    _step(0, "ASSERT_VISIBLE", target=sel, description=f"The '{text}' link to {where} is shown"),
                ], about="A visitor can still find this link")
            target = _path(absolute)
            if (clicked < MAX_LINK_CLICKS and same_site and not link.get("new_tab") and not link.get("download")
                    and target != self.path and target != "/" and target in safe_paths
                    and not _UNSAFE.search(dest.path) and not _FILE.search(dest.path)):
                clicked += 1
                self.add("navigation", "click", href, f"Clicking '{text}' opens {target}", [
                    self.open(),
                    _step(0, "CLICK", target=sel, description=f"Click the '{text}' link"),
                    _step(0, "ASSERT_URL", value=target, description=f"The browser is on {target}"),
                ], about="The link takes the visitor where it says")

    def stability(self, back_to: str | None) -> None:
        headings = [h for h in stable_headings(self.analysis) if len(h.strip()) >= 3]
        if not headings:
            return
        heading = _short(headings[0], 40).rstrip("…")
        self.add("navigation", "reload", "reload", "Page keeps its content after a reload", [
            self.open(),
            _step(0, "RELOAD", description="Reload the page"),
            _step(0, "ASSERT_CONTAINS_TEXT", target="body", value=heading, description=f"Page still shows '{heading}'"),
        ], about="A refresh does not lose the page (a broken route or session shows an error instead)")
        if back_to:
            self.add("navigation", "back", back_to, f"Back from {_path(back_to)} returns to this page", [
                self.open(),
                _step(0, "NAVIGATE", value=back_to, description=f"Open {back_to}"),
                _step(0, "GO_BACK", description="Press the browser's Back button"),
                _step(0, "ASSERT_CONTAINS_TEXT", target="body", value=heading,
                      description=f"The page shows '{heading}' again"),
            ], about="Browser history works: Back returns to this page with its content")

    # ── responsive ──
    def responsive(self) -> None:
        headings = [_short(h, 40).rstrip("…") for h in stable_headings(self.analysis) if len(h.strip()) >= 3]
        headings = list(dict.fromkeys(headings))[:MAX_RESPONSIVE_HEADINGS]
        if not headings:
            return
        for name, size in VIEWPORTS:
            width = size.split("x")[0]
            self.add("responsive", name, size, f"Page shows its content on a {name} ({width} px wide)", [
                self.open(),
                *(_step(0, "ASSERT_CONTAINS_TEXT", target="body", value=h,
                        description=f"At {width} px the page shows '{h}'") for h in headings),
            ], about=f"A visitor on a {name} sees the page's main content (it is not hidden or pushed off by the layout)",
               viewport=size)

    # ── accessibility ──
    def page_language(self) -> None:
        lang = self.analysis.get("page_lang")
        if lang:
            self.add("accessibility", "lang", lang, f"Page declares its language ({lang})",
                     self.attribute_kept("html", f"lang={css_string(lang)}", "The page renders",
                                         f"The page says it is in '{lang}' (screen readers pick the voice from it)"),
                     about="Screen readers and translation tools read the page in the right language")

    def images(self) -> None:
        inventory = self.analysis.get("elements_inventory") or {}
        done = 0
        for image in inventory.get("images") or []:
            if done >= MAX_IMAGES:
                break
            if image.get("hidden") or not image.get("selector") or not image.get("alt"):
                continue
            done += 1
            alt = image["alt"]
            self.add("accessibility", "image", image["src"], f"Image '{_short(alt, 30)}' is shown with its alt text",
                     # The same picture may also sit in a closed menu or another slide: the visible one
                     self.attribute_kept(f"{image['selector']}:visible", f"alt={css_string(alt)}", "The image is shown",
                                         f"The image is described as '{_short(alt)}'"),
                     about="The image is in place and keeps a text description for screen readers")


def page_coverage(url: str, analysis: dict[str, Any], *, start: bool, safe_paths: set[str],
                  back_to: str | None = None, shared: dict[str, set[str]] | None = None) -> list[dict[str, Any]]:
    """Coverage tests for one analyzed page.

    *start*: the run's start page, whose first heading the core ``content``
    test already checks.  *safe_paths*: same-site paths that loaded for a
    signed-out visitor without a redirect (the only links a test clicks).
    *back_to*: another analyzed page to visit and come Back from.
    *shared*: links and headings earlier pages already checked (filled in).
    """
    trusted = bool(analysis.get("visibility_checked"))
    b = _Builder(url, analysis, trusted=trusted, shared=shared)
    b.headings(skip_first=True)  # the first heading is the core suite's content / page check
    b.fields()
    b.buttons()
    b.links(safe_paths)
    b.stability(back_to)
    b.responsive()
    b.page_language()
    b.images()
    return b.tests


def site_coverage(start_url: str, start: dict[str, Any], pages: dict[str, dict[str, Any]],
                  safe_paths: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Coverage tests for the start page and every other analyzed page,
    interleaved by kind so a limit on the total keeps some of every kind."""
    safe = set(safe_paths) | {_path(u) for u in pages}
    others = [u for u in pages if _path(u) != _path(start_url)]
    shared: dict[str, set[str]] = {}
    per_page = [page_coverage(start_url, start, start=True, safe_paths=safe,
                              back_to=others[0] if others else None, shared=shared)]
    per_page += [page_coverage(u, pages[u], start=False, safe_paths=safe, shared=shared) for u in others]
    tests: list[dict[str, Any]] = []
    seen: set[str] = set()
    for test in interleave(per_page):
        if test["slug"] not in seen:
            seen.add(test["slug"])
            tests.append(test)
    return tests


def interleave(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Round-robin by category, then page: cutting the list anywhere keeps a
    mix of kinds and pages rather than every heading of the first page."""
    by_cat: dict[str, list[dict[str, Any]]] = {c: [] for c in CATEGORIES}
    for group in groups:
        for test in group:
            by_cat.setdefault(test["category"], []).append(test)
    queues = [q for q in by_cat.values() if q]
    out: list[dict[str, Any]] = []
    while queues:
        for q in list(queues):
            out.append(q.pop(0))
            if not q:
                queues.remove(q)
    return out


def counts(tests: Iterable[dict[str, Any]]) -> dict[str, int]:
    """How many tests of each coverage kind."""
    out: dict[str, int] = {}
    for t in tests:
        out[t["category"]] = out.get(t["category"], 0) + 1
    return out
