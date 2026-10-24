"""
engine/heal_benchmark.py
========================
Self-healing benchmark on a generated corpus of broken pages.

    python -m engine.heal_benchmark            # full corpus (a few hundred cases)
    python -m engine.heal_benchmark --quick    # one target per page (CI-sized)

Four realistic pages (login, sign-up, shop, settings) each mark their test
targets.  Every target is broken by every applicable mutation operator: the
primary locator (``data-testid``) always stops matching, and the operator
adds a further change (ids, names, classes or text renamed, the element
wrapped, moved, or joined by a look-alike), or makes healing *wrong* (the
element removed, its tag or input type changed, or replaced by a look-alike).

Each case runs with three strategies on the same enriched fallbacks:

* ``none``        — no healing (the step simply fails; computed, not run)
* ``chain``       — a fallback chain: the first stored fallback that matches
                    exactly one element is used (what ``locator.or(...)`` chains
                    and most multi-locator tools do)
* ``testsphere``  — TestSphere's healer: scored fallbacks, then a fingerprint
                    scan with a confidence threshold and an ambiguity margin

Ground truth is element identity: a probe copy of the mutated page marks the
real target, and a heal counts as correct only if the healed locator resolves
to exactly that element.  Results go to docs/healing-benchmark.md and .csv.

Playwright's own Healer (Playwright Agents) is an LLM agent working through an
MCP session; it cannot run deterministically offline, so it is not a column
here.  The ``chain`` strategy stands in for static multi-locator healing.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import hashlib
import http.server
import re
import shutil
import socket
import tempfile
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import async_playwright

import engine.runner as runner
from engine.healer import attempt_healing
from engine.schemas import (
    ActionType,
    HealingReport,
    RunOptions,
    Step,
    StepStatus,
    Target,
    TestPlan,
)

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# ── Pages ──────────────────────────────────────────────────────────────────
# Targets carry data-t="<key>" (and data-alt="<other wording>" for text
# changes); both are stripped before serving.  <!--end--> marks where a moved
# element is put.

PAGES: dict[str, str] = {
    "login": """<!doctype html><html><head><title>Sign in</title></head><body>
<main class="auth">
  <h1>Welcome back</h1>
  <form class="login-form" onsubmit="return false">
    <label for="email">Email</label>
    <input data-t="email" id="email" name="email" type="email" class="input input-email" data-testid="email-input" placeholder="you@company.com" autocomplete="email" aria-label="Email address"/>
    <label for="password">Password</label>
    <input data-t="password" id="password" name="password" type="password" class="input input-password" data-testid="password-input" placeholder="Your password" autocomplete="current-password" aria-label="Password"/>
    <label class="remember"><input data-t="remember" id="remember" name="remember" type="checkbox" class="check" data-testid="remember-check" aria-label="Remember me"/> Remember me</label>
    <button data-t="submit" data-alt="Sign in" id="login-btn" name="login" type="button" class="btn btn-primary" data-testid="login-button">Log in</button>
    <a data-t="forgot" data-alt="Reset password" id="forgot-link" class="link" data-testid="forgot-link" href="#forgot">Forgot password?</a>
    <!--end-->
  </form>
</main></body></html>""",
    "signup": """<!doctype html><html><head><title>Create account</title></head><body>
<main class="auth">
  <h1>Create your account</h1>
  <form class="signup-form" onsubmit="return false">
    <input data-t="name" id="full-name" name="name" type="text" class="input" data-testid="name-input" placeholder="Your name" autocomplete="name" aria-label="Full name"/>
    <input data-t="email" id="signup-email" name="email" type="email" class="input" data-testid="signup-email" placeholder="Work email" autocomplete="email" aria-label="Work email"/>
    <input data-t="password" id="new-password" name="password" type="password" class="input" data-testid="new-password" placeholder="At least 8 characters" autocomplete="new-password" aria-label="New password"/>
    <label><input data-t="terms" id="terms" name="terms" type="checkbox" data-testid="terms-check" aria-label="Accept the terms"/> I accept the terms</label>
    <button data-t="create" data-alt="Sign up" id="create-btn" name="create" type="button" class="btn btn-primary" data-testid="create-account">Create account</button>
    <a data-t="back" data-alt="Return to sign in" id="back-link" class="link" data-testid="back-to-login" href="#login">Back to sign in</a>
    <!--end-->
  </form>
</main></body></html>""",
    "shop": """<!doctype html><html><head><title>Shop</title></head><body>
<header class="bar">
  <input data-t="search" id="search" name="q" type="search" class="search" data-testid="search-box" placeholder="Search products" aria-label="Search products"/>
  <select data-t="category" id="category" name="category" class="select" data-testid="category-filter" aria-label="Category"><option value="all">All</option><option value="books">Books</option><option value="games">Games</option></select>
</header>
<main class="grid">
  <article class="card" id="p1"><h2>Notebook</h2><button id="add-1" type="button" class="btn add" data-testid="add-to-cart-1">Add to cart</button></article>
  <article class="card" id="p2"><h2>Fountain pen</h2><button data-t="add" data-alt="Buy now" id="add-2" type="button" class="btn add" data-testid="add-to-cart-2">Add to cart</button></article>
  <article class="card" id="p3"><h2>Desk lamp</h2><button id="add-3" type="button" class="btn add" data-testid="add-to-cart-3">Add to cart</button></article>
  <!--end-->
</main>
<footer><a data-t="checkout" data-alt="Go to cart" id="checkout" class="link cta" data-testid="checkout-link" href="#checkout">Checkout</a>
<input data-t="newsletter" id="newsletter" name="newsletter" type="email" class="input" data-testid="newsletter-email" placeholder="Get our newsletter" aria-label="Newsletter email"/></footer>
</body></html>""",
    "settings": """<!doctype html><html><head><title>Settings</title></head><body>
<nav class="side"><a id="nav-home" href="#home" data-testid="nav-home">Home</a>
<a data-t="billing" data-alt="Payments" id="nav-billing" href="#billing" class="nav-link" data-testid="nav-billing">Billing</a>
<a id="nav-settings" href="#settings" data-testid="nav-settings">Settings</a></nav>
<main class="settings">
  <h1>Settings</h1>
  <form onsubmit="return false">
    <input data-t="display" id="display-name" name="display_name" type="text" class="input" data-testid="display-name" placeholder="Display name" aria-label="Display name"/>
    <label><input data-t="digest" id="weekly-digest" name="digest" type="checkbox" data-testid="digest-toggle" aria-label="Weekly digest"/> Weekly digest</label>
    <button data-t="save" data-alt="Update profile" id="save-btn" name="save" type="button" class="btn btn-primary" data-testid="save-settings">Save changes</button>
    <button data-t="delete" data-alt="Remove account" id="delete-btn" name="delete" type="button" class="btn btn-danger" data-testid="delete-account">Delete account</button>
    <!--end-->
  </form>
</main></body></html>""",
}

QUICK_TARGETS = {"login": "submit", "signup": "email", "shop": "add", "settings": "billing"}

# ── Elements ───────────────────────────────────────────────────────────────

ATTR_RE = re.compile(r'([\w:-]+)="([^"]*)"')


@dataclass
class El:
    tag: str
    attrs: dict[str, str]
    inner: str | None  # None = void element (<input .../>)

    def html(self) -> str:
        attrs = " ".join(f'{k}="{v}"' for k, v in self.attrs.items())
        return f"<{self.tag} {attrs}/>" if self.inner is None else f"<{self.tag} {attrs}>{self.inner}</{self.tag}>"


def element_re(key: str) -> re.Pattern:
    return re.compile(
        rf'<(?P<tag>input)\b(?P<a>[^>]*\bdata-t="{key}"[^>]*?)/>'
        rf'|<(?P<tag2>\w+)\b(?P<a2>[^>]*\bdata-t="{key}"[^>]*)>(?P<inner>.*?)</(?P=tag2)>', re.S)


def find(page: str, key: str) -> tuple[re.Match, El]:
    m = element_re(key).search(page)
    if not m:
        raise KeyError(key)
    if m.group("tag"):
        return m, El("input", dict(ATTR_RE.findall(m.group("a"))), None)
    return m, El(m.group("tag2"), dict(ATTR_RE.findall(m.group("a2"))), m.group("inner"))


def kind(el: El) -> str:
    if el.tag == "input":
        return "checkbox" if el.attrs.get("type") == "checkbox" else "text"
    return el.tag  # button, a, select


def clean(html: str) -> str:
    return re.sub(r'\s(?:data-t|data-alt)="[^"]*"', "", html)


def _suffix(value: str, tag: str) -> str:
    return f"{value}-{hashlib.sha1(f'{value}{tag}'.encode(), usedforsecurity=False).hexdigest()[:4]}"  # nosemgrep: insecure-hash-algorithm-sha1 - test fixture names


# ── Mutation operators ─────────────────────────────────────────────────────
# Each returns the mutated page and whether the target still exists (truth).
# Every operator breaks the primary locator (data-testid).


@dataclass
class Operator:
    name: str
    heal_expected: bool
    applies: Callable[[El], bool]
    apply: Callable[[str, re.Match, El], tuple[str, El | None]]


def _replace(page: str, m: re.Match, new: str) -> str:
    return page[: m.start()] + new + page[m.end():]


def _break_testid(el: El) -> El:
    el = copy.deepcopy(el)
    el.attrs["data-testid"] = _suffix(el.attrs["data-testid"], "v2")
    return el


def _renamed(*attrs: str) -> Callable[[str, re.Match, El], tuple[str, El | None]]:
    def go(page: str, m: re.Match, el: El) -> tuple[str, El | None]:
        new = _break_testid(el)
        for a in attrs:
            if a in new.attrs:
                new.attrs[a] = " ".join(_suffix(v, a) for v in new.attrs[a].split()) if a == "class" else _suffix(new.attrs[a], a)
        return _replace(page, m, new.html()), new
    return go


def _testid_removed(page, m, el):
    new = copy.deepcopy(el)
    del new.attrs["data-testid"]
    return _replace(page, m, new.html()), new


def _text_changed(page, m, el):
    new = _break_testid(el)
    new.inner = el.attrs.get("data-alt", el.inner)
    return _replace(page, m, new.html()), new


def _hard(page, m, el):
    new = _break_testid(el)
    for a in ("id", "name", "class"):
        if a in new.attrs:
            new.attrs[a] = _suffix(new.attrs[a], "hard")
    if new.inner is not None and new.tag != "select":
        new.inner = el.attrs.get("data-alt", el.inner)
    return _replace(page, m, new.html()), new


def _wrapped(page, m, el):
    new = _break_testid(el)
    return _replace(page, m, f'<div class="field-wrap"><span class="slot">{new.html()}</span></div>'), new


def _moved(page, m, el):
    new = _break_testid(el)
    page = _replace(page, m, "")
    return page.replace("<!--end-->", new.html() + "\n<!--end-->", 1), new


def _decoy(el: El, tag: str) -> El:
    d = copy.deepcopy(el)
    d.attrs.pop("data-t", None)
    for a in ("id", "name", "data-testid"):
        if a in d.attrs:
            d.attrs[a] = _suffix(d.attrs[a], tag)
    if "placeholder" in d.attrs:
        d.attrs["placeholder"] = "Confirm " + d.attrs["placeholder"].lower()
    if "aria-label" in d.attrs:
        d.attrs["aria-label"] = "Confirm " + d.attrs["aria-label"].lower()
    if d.inner is not None and d.tag != "select":
        d.inner = el.attrs.get("data-alt", el.inner)
    return d


def _with_decoy(page, m, el):
    new = _break_testid(el)
    return _replace(page, m, _decoy(el, "decoy").html() + "\n    " + new.html()), new


def _removed(page, m, el):
    return _replace(page, m, ""), None


def _removed_with_decoy(page, m, el):
    return _replace(page, m, _decoy(el, "twin").html()), None


def _tag_changed(page, m, el):
    new = _break_testid(el)
    if el.tag == "input" and kind(el) == "text":
        new.tag, new.inner = "textarea", ""
        new.attrs.pop("type", None)
    elif el.tag == "button":
        new.tag = "a"
        new.attrs.pop("type", None)
        new.attrs["href"] = "#"
    elif el.tag == "a":
        new.tag = "button"
        new.attrs.pop("href", None)
        new.attrs["type"] = "button"
    return _replace(page, m, new.html()), None  # a different kind of element: a human should look


def _type_changed(page, m, el):
    new = _break_testid(el)
    new.attrs["type"] = "radio" if new.attrs.get("type") == "checkbox" else "checkbox"
    return _replace(page, m, new.html()), None


def _has(*attrs: str) -> Callable[[El], bool]:
    return lambda el: all(a in el.attrs for a in attrs)


OPERATORS = [
    Operator("testid-renamed", True, _has("data-testid"), _renamed()),
    Operator("testid-removed", True, _has("data-testid"), _testid_removed),
    Operator("id-renamed", True, _has("id"), _renamed("id")),
    Operator("name-renamed", True, _has("name"), _renamed("name")),
    Operator("class-renamed", True, _has("class"), _renamed("class")),
    Operator("ids-renamed", True, _has("id", "name"), _renamed("id", "name")),
    Operator("text-changed", True, lambda el: el.inner is not None and el.tag != "select", _text_changed),
    Operator("wrapped", True, lambda el: True, _wrapped),
    Operator("moved", True, lambda el: True, _moved),
    Operator("look-alike-added", True, lambda el: True, _with_decoy),
    Operator("everything-renamed", True, _has("id"), _hard),
    Operator("removed", False, lambda el: True, _removed),
    Operator("replaced-by-look-alike", False, lambda el: True, _removed_with_decoy),
    Operator("tag-changed", False, lambda el: el.tag in ("button", "a") or kind(el) == "text", _tag_changed),
    Operator("input-type-changed", False, lambda el: el.tag == "input", _type_changed),
]


@dataclass
class Case:
    page: str
    target: str
    operator: Operator
    html: str          # served
    probe: str         # served copy with the true target marked

    @property
    def name(self) -> str:
        return f"{self.page}/{self.target}/{self.operator.name}"


def build_cases(quick: bool = False) -> list[Case]:
    cases = []
    for page_name, page in PAGES.items():
        keys = re.findall(r'data-t="([^"]+)"', page)
        if quick:
            keys = [QUICK_TARGETS[page_name]]
        for key in keys:
            m, el = find(page, key)
            for op in OPERATORS:
                if not op.applies(el):
                    continue
                mutated, survivor = op.apply(page, m, el)
                probe = mutated
                if survivor is not None:
                    pm, _ = find(mutated, key)
                    marked = copy.deepcopy(survivor)
                    marked.attrs["data-truth"] = "1"
                    probe = _replace(mutated, pm, marked.html())
                cases.append(Case(page_name, key, op, clean(mutated), clean(probe)))
    return cases


def step_for(page: str, key: str) -> Step:
    _, el = find(page, key)
    k = kind(el)
    action = {"text": ActionType.FILL, "checkbox": ActionType.CLICK, "select": ActionType.SELECT}.get(k, ActionType.CLICK)
    value = {"text": "hello@example.com", "select": "books"}.get(k)
    fallbacks = [f'#{el.attrs["id"]}'] + ([f'[name="{el.attrs["name"]}"]'] if "name" in el.attrs else [])
    return Step(step_id=f"{key}", action=action, value=value, timeout_ms=1_500,
                target=Target(description=key, primary_locator=f'[data-testid="{el.attrs["data-testid"]}"]',
                              fallback_locators=fallbacks))


# ── Serving ────────────────────────────────────────────────────────────────

_CONTENT: dict[str, bytes] = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        body = _CONTENT.get(self.path.lstrip("/"))
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve() -> tuple[http.server.ThreadingHTTPServer, str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{port}"


# ── Strategies ─────────────────────────────────────────────────────────────

async def chain_healing(page, step: Step, config, exc) -> HealingReport | None:
    """A static fallback chain: first stored fallback matching exactly one element."""
    target = step.target
    if target is None:
        return None
    for loc in target.fallback_locators:
        if loc == target.primary_locator:
            continue
        try:
            if await page.locator(loc).count() == 1:
                return HealingReport(original_locator=target.primary_locator, selected_locator=loc,
                                     confidence=1.0, strategy_used="fallback-chain")
        except Exception:  # noqa: BLE001 - an invalid selector is just not a match
            continue
    return HealingReport(original_locator=target.primary_locator, strategy_used="none")


STRATEGIES = {"chain": chain_healing, "testsphere": attempt_healing}


@dataclass
class Result:
    case: str
    page: str
    target: str
    operator: str
    heal_expected: bool
    strategy: str
    healed: bool
    correct: bool | None    # healed onto the true element (None if not healed)
    locator: str
    how: str
    confidence: float
    ms: int

    @property
    def outcome(self) -> str:
        if self.healed:
            return "correct heal" if self.correct else "false heal"
        return "missed heal" if self.heal_expected else "correct refusal"


async def _truth_check(probe_page, url: str, locator: str) -> bool:
    await probe_page.goto(url, wait_until="domcontentloaded")
    try:
        loc = probe_page.locator(locator)
        if await loc.count() != 1:
            return False
        return bool(await loc.first.evaluate("el => el.hasAttribute('data-truth')"))
    except Exception:  # noqa: BLE001
        return False


async def run(quick: bool = False, concurrency: int = 2, progress: bool = True) -> list[Result]:
    cases = build_cases(quick)
    server, base = _serve()
    artifacts = Path(tempfile.mkdtemp(prefix="heal-bench-"))
    options = RunOptions(headless=True, artifacts_dir=str(artifacts), default_timeout_ms=1_500,
                         min_action_timeout_ms=1_500, tracing_enabled=False)
    original_hook = runner._attempt_healing
    results: list[Result] = []
    try:
        # Baseline: enrich every target's fingerprint and fallbacks on the intact pages
        enriched: dict[tuple[str, str], Step] = {}
        runner._attempt_healing = attempt_healing
        for page_name, page in PAGES.items():
            _CONTENT[f"{page_name}.html"] = clean(page).encode()
            steps = [step_for(page, k) for k in re.findall(r'data-t="([^"]+)"', page)]
            url = f"{base}/{page_name}.html"
            plan = TestPlan(test_id=f"bench-{page_name}", name=page_name, base_url=url,
                            steps=[Step(step_id="open", action=ActionType.GOTO, value=url), *steps])
            res = await runner.run_test(plan, options)
            assert all(s.status == StepStatus.PASSED for s in res.steps), f"baseline failed on {page_name}"
            for st in plan.steps[1:]:
                enriched[(page_name, st.step_id)] = st

        for i, case in enumerate(cases):
            _CONTENT[f"c{i}.html"] = case.html.encode()
            _CONTENT[f"p{i}.html"] = case.probe.encode()

        async with async_playwright() as pw:
            probe_browser = await pw.chromium.launch(headless=True)
            probe = await probe_browser.new_page()
            sem = asyncio.Semaphore(concurrency)

            for strategy, hook in STRATEGIES.items():
                runner._attempt_healing = hook
                done = 0

                async def one(i: int, case: Case, strategy=strategy) -> Result:
                    nonlocal done
                    url = f"{base}/c{i}.html"
                    step = copy.deepcopy(enriched[(case.page, case.target)])
                    plan = TestPlan(test_id=f"case-{strategy}-{i}", name=case.name, base_url=url,
                                    steps=[Step(step_id="open", action=ActionType.GOTO, value=url), step])
                    async with sem:
                        started = time.monotonic()
                        res = await runner.run_test(plan, options)
                    sr = res.steps[-1]
                    healed = sr.status == StepStatus.HEALED
                    done += 1
                    if progress and done % 25 == 0:
                        print(f"  {strategy}: {done}/{len(cases)}", flush=True)
                    return Result(case.name, case.page, case.target, case.operator.name, case.operator.heal_expected,
                                  strategy, healed, None, sr.locator_used or "",
                                  sr.healing.strategy_used if sr.healing else "",
                                  sr.healing.confidence if sr.healing else 0.0,
                                  int((time.monotonic() - started) * 1000))

                batch = await asyncio.gather(*(one(i, c) for i, c in enumerate(cases)))
                for i, r in enumerate(batch):
                    if r.healed:
                        r.correct = await _truth_check(probe, f"{base}/p{i}.html", r.locator)
                results += batch
            await probe_browser.close()
    finally:
        runner._attempt_healing = original_hook
        server.shutdown()
        shutil.rmtree(artifacts, ignore_errors=True)

    # "none": the primary locator never matches by construction, so the step fails
    for case in cases:
        results.append(Result(case.name, case.page, case.target, case.operator.name, case.operator.heal_expected,
                              "none", False, None, "", "", 0.0, 0))
    return results


# ── Report ─────────────────────────────────────────────────────────────────

def summarize(results: list[Result]) -> dict[str, dict[str, float]]:
    out = {}
    for strategy in ("none", "chain", "testsphere"):
        rs = [r for r in results if r.strategy == strategy]
        expected = [r for r in rs if r.heal_expected]
        refusals = [r for r in rs if not r.heal_expected]
        heals = [r for r in rs if r.healed]
        out[strategy] = {
            "cases": len(rs),
            "heal_rate": sum(r.outcome == "correct heal" for r in expected) / len(expected) if expected else 0.0,
            "false_heal_rate": sum(r.outcome == "false heal" for r in heals) / len(heals) if heals else 0.0,
            "false_heals": sum(r.outcome == "false heal" for r in rs),
            "refusal_rate": sum(r.outcome == "correct refusal" for r in refusals) / len(refusals) if refusals else 0.0,
            "pass_rate": sum(r.outcome in ("correct heal",) for r in rs) / len(rs) if rs else 0.0,
            "mean_ms": sum(r.ms for r in rs) / len(rs) if rs else 0.0,
        }
    return out


def write_reports(results: list[Result], quick: bool) -> tuple[Path, Path]:
    DOCS.mkdir(exist_ok=True)
    stem = "healing-benchmark-quick" if quick else "healing-benchmark"
    csv_path, md_path = DOCS / f"{stem}.csv", DOCS / f"{stem}.md"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["case", "page", "target", "operator", "heal_expected", "strategy", "outcome", "locator", "how", "confidence", "ms"])
        for r in sorted(results, key=lambda r: (r.case, r.strategy)):
            w.writerow([r.case, r.page, r.target, r.operator, r.heal_expected, r.strategy, r.outcome, r.locator, r.how,
                        f"{r.confidence:.2f}", r.ms])

    s = summarize(results)
    pct = lambda v: f"{v * 100:.1f}%"  # noqa: E731
    cases = s["testsphere"]["cases"]
    lines = [
        "# Self-healing benchmark",
        "",
        f"{cases} broken-locator cases: {len(PAGES)} pages, every test target, {len(OPERATORS)} mutation operators "
        f"({sum(1 for o in OPERATORS if o.heal_expected)} where healing is right, "
        f"{sum(1 for o in OPERATORS if not o.heal_expected)} where it is wrong). "
        "Generated by `python -m engine.heal_benchmark`" + (" --quick" if quick else "") + ".",
        "",
        "A heal is **correct** only if the healed locator resolves to the very element that was the target "
        "(checked on a marked copy of the page). Where the target is gone or became a different kind of element, "
        "the right answer is to **refuse**.",
        "",
        "| Strategy | Heals where it should | False heals (of all heals) | Correct refusals | Mean time per case |",
        "| :--- | ---: | ---: | ---: | ---: |",
    ]
    names = {"none": "No healing", "chain": "Fallback chain (first unique fallback)", "testsphere": "**TestSphere healer**"}
    for k in ("none", "chain", "testsphere"):
        v = s[k]
        lines.append(f"| {names[k]} | {pct(v['heal_rate'])} | {pct(v['false_heal_rate'])} ({v['false_heals']}) | "
                     f"{pct(v['refusal_rate'])} | {v['mean_ms'] / 1000:.1f} s |")
    lines += ["", "## By mutation", "",
              "| Mutation | Should heal | Cases | Fallback chain | TestSphere |", "| :--- | :---: | ---: | :--- | :--- |"]
    by = defaultdict(lambda: defaultdict(Counter))
    for r in results:
        by[r.operator][r.strategy][r.outcome] += 1
    for op in OPERATORS:
        cell = {}
        for strat in ("chain", "testsphere"):
            c = by[op.name][strat]
            n = sum(c.values())
            good = c["correct heal"] if op.heal_expected else c["correct refusal"]
            extra = f", {c['false heal']} false" if c["false heal"] else ""
            cell[strat] = f"{good}/{n} {'healed' if op.heal_expected else 'refused'}{extra}"
        n = sum(by[op.name]["testsphere"].values())
        lines.append(f"| {op.name} | {'yes' if op.heal_expected else 'no'} | {n} | {cell['chain']} | {cell['testsphere']} |")
    lines += ["", "## Not compared",
              "",
              "Playwright's Healer (Playwright Agents) repairs tests with an LLM through an MCP session. It is not "
              "deterministic and needs a model and network access, so it is not a column here. The fallback chain "
              "stands in for static multi-locator healing (`locator.or(...)` chains and similar tools).", ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--quick", action="store_true", help="one target per page")
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    started = time.monotonic()
    results = asyncio.run(run(quick=args.quick, concurrency=args.concurrency))
    md, csv_path = write_reports(results, args.quick)
    s = summarize(results)
    for k, v in s.items():
        print(f"{k:11s} heal {v['heal_rate']:.1%}  false-heal {v['false_heal_rate']:.1%}  refuse {v['refusal_rate']:.1%}")
    print(f"Wrote {md} and {csv_path} in {time.monotonic() - started:.0f}s")


if __name__ == "__main__":
    main()
