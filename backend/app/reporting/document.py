"""
TestSphere-AI — A run's report as one self-contained document.

``build_report`` gathers what the report needs: the run, each test's
recorded steps (status, timing, locator, self-healing), and each failure's
failing step and screenshot.  ``render_html`` lays it out:

 1. cover: verdict, target, timing
 2. executive summary: the plain-sentence summary and the key numbers
 3. recommendations, worked out from the run's own results
 4. results by kind of test, and coverage by page
 5. the pages analyzed: how each answered, what is on it, its health audit
    (security headers, accessibility, performance)
 6. security findings, most serious first
 7. the pipeline's stages with their timing
 8. regressions, self-healed tests (old and new locator), flaky tests
 9. every failure with its diagnosis, steps and screenshot
10. timing: the slowest tests and time by kind
11. every test, by kind, with what it protects, its checks and its steps
12. how to read the report

The document is static and self-contained: every value is HTML-escaped
(page text from the tested site may contain markup), there are no scripts,
and screenshots are embedded as data URIs, so rendering it to PDF or serving
it on a share link loads nothing from anywhere.
"""

from __future__ import annotations

import base64
from collections import Counter, defaultdict
from datetime import UTC, datetime
from html import escape
from typing import Any

from app.artifacts import get_artifact_store
from app.database.store import Record, Store
from app.models import TEST_EXECUTIONS

GROUPS = [("smoke", "Smoke"), ("functional", "Goal scenario & forms"), ("explored", "AI-explored goal"),
          ("content", "Content"), ("elements", "Page elements"), ("validation", "Field validation"),
          ("navigation", "Navigation"), ("accessibility", "Accessibility"), ("responsive", "Responsive layout"),
          ("link", "Linked pages"),
          ("route", "Code routes"), ("ai", "AI-written tests"), ("repository", "Repository tests"),
          ("saved", "Saved tests")]
GROUP_ABOUT = {
    "smoke": "The page loads; its title and body render",
    "functional": "The written goal and the page's forms: filled in, sent, and the outcome checked",
    "explored": "The goal as the AI explorer reached it, replayed",
    "content": "Each heading a visitor reads is still on the page",
    "elements": "Each field takes input, each button is shown with its label, each choice can be made",
    "validation": "Each field keeps its contract: required, its type, its maximum length",
    "navigation": "Links are shown and lead where they say; pages survive reload and Back",
    "accessibility": "Language declared, images described, fields named for screen readers",
    "responsive": "Each page still shows its content at phone (390 px) and tablet (768 px) width",
    "link": "Linked page loads with its title and heading", "route": "Route found in the code loads",
    "ai": "Scenario written by the AI planner (quarantined until trusted)",
    "repository": "The repository's own Playwright tests, replayed", "saved": "Saved test",
}
MAX_SCREENSHOTS = 12
MAX_SCREENSHOT_BYTES = 2_000_000
# Tests whose recorded steps are read for the report (each is one database read)
MAX_DETAILED_TESTS = 600
SLOWEST = 10


def _group(test: dict[str, Any]) -> str:
    return test.get("category") if test.get("category") in GROUP_ABOUT else "saved"


def _label(test: dict[str, Any]) -> str:
    return "HEALED" if test.get("healed") and test.get("status") == "PASSED" else str(test.get("status") or "")


def _duration(ms: Any) -> str:
    if ms is None:
        return ""
    if ms < 1000:
        return f"{int(ms)} ms"
    if ms < 120_000:
        return f"{ms / 1000:.1f} s"
    return f"{int(ms // 60000)} min {int(ms % 60000 / 1000)} s"


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _span_ms(start: Any, end: Any) -> int | None:
    a, b = _parse_time(start), _parse_time(end)
    return int((b - a).total_seconds() * 1000) if a and b and b >= a else None


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def build_report(db: Store, run: Record) -> dict[str, Any]:
    """The run plus every test's recorded steps and, for each failure, its
    failing step and that step's screenshot."""
    store = get_artifact_store()
    failures, shots = [], 0
    steps_by_execution: dict[Any, list[dict[str, Any]]] = {}
    for test in (run.get("tests") or [])[:MAX_DETAILED_TESTS]:
        execution = db.get(TEST_EXECUTIONS, test["execution_id"]) if test.get("execution_id") is not None else None
        execution = execution or {}
        steps = execution.get("steps") or []
        steps_by_execution[test.get("execution_id")] = steps
        if test.get("status") != "FAILED":
            continue
        step = next((s for s in steps if s.get("status") == "failed"), steps[-1] if steps else None)
        screenshot = None
        key = (step or {}).get("screenshot")
        if key and shots < MAX_SCREENSHOTS:
            found = store.get(key)
            if found and found[1] == "image/png" and len(found[0]) <= MAX_SCREENSHOT_BYTES:
                screenshot = base64.b64encode(found[0]).decode()
                shots += 1
        failures.append({"test": test, "step": step, "steps": steps,
                         "step_number": steps.index(step) + 1 if step in steps else None,
                         "diagnosis": test.get("diagnosis") or execution.get("diagnosis"), "screenshot": screenshot})
    # Failures that fail the run first, then quarantined ones
    failures.sort(key=lambda f: (bool(f["test"].get("quarantined")), f["test"].get("execution_id", 0)))
    return {"run": run, "failures": failures, "steps": steps_by_execution}


_CSS = """
@page { size: A4; margin: 14mm 12mm; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; color: #1f2328;
       font-size: 12px; line-height: 1.55; margin: 0; background: #fff; }
.wrap { max-width: 1000px; margin: 0 auto; padding: 28px; }
h1 { font-size: 26px; margin: 4px 0 6px; line-height: 1.25; }
h2 { font-size: 17px; margin: 34px 0 12px; border-bottom: 2px solid #17402c; padding-bottom: 5px; color: #17402c; }
h3 { font-size: 13.5px; margin: 18px 0 8px; } h4 { font-size: 12px; margin: 12px 0 6px; }
a { color: #0b5ea8; text-decoration: none; }
.muted { color: #636c76; } .small { font-size: 11px; } .xsmall { font-size: 10px; } .mono { font-family: ui-monospace, Consolas, monospace; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 10.5px; font-weight: 600; border: 1px solid; white-space: nowrap; }
.PASSED, .passed, .done, .ok { color: #1a7f37; background: #e6f6ea; border-color: #a6dcb4; }
.HEALED { color: #0b5ea8; background: #e4f0fb; border-color: #a8cbee; }
.FAILED, .failed, .bad { color: #9b1c1c; background: #fde3e3; border-color: #f0a3a3; }
.gray, .skipped, .pending, .PENDING { color: #57606a; background: #f1efeb; border-color: #d8d4cc; }
.warn { color: #8a5300; background: #fff4dd; border-color: #f1cf8a; }
.critical, .high { color: #fff; background: #b42318; border-color: #b42318; } .medium { color: #8a5300; background: #fff4dd; border-color: #f1cf8a; }
.low, .info { color: #57606a; background: #f1efeb; border-color: #d8d4cc; }
.cover { border: 1px solid #e3e1dc; border-radius: 14px; padding: 22px 24px; background: linear-gradient(135deg, #f4faf6, #fff 60%); }
.cover .meta { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 18px; margin-top: 14px; }
.cover .meta div b { display: block; font-size: 10px; color: #636c76; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
.summary { border: 1px solid #e3e1dc; background: #faf8f5; border-radius: 10px; padding: 12px 16px; margin: 14px 0; }
.summary p { margin: 3px 0; } .verdict { font-weight: 700; }
.stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; margin: 14px 0; }
.stat { border: 1px solid #e3e1dc; border-radius: 10px; padding: 10px 12px; break-inside: avoid; }
.stat b { display: block; font-size: 20px; line-height: 1.2; } .stat.bad b { color: #9b1c1c; } .stat.good b { color: #1a7f37; }
.bar { height: 8px; background: #eeebe5; border-radius: 99px; overflow: hidden; display: flex; min-width: 60px; }
.bar span { display: block; height: 100%; } .bar .p { background: #2a6a46; } .bar .h { background: #3b82c4; } .bar .f { background: #c0392b; } .bar .q { background: #b9b3a8; }
.bar.big { height: 14px; margin: 8px 0 4px; }
.legend { display: flex; gap: 14px; flex-wrap: wrap; } .legend i { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; margin: 6px 0; }
th, td { text-align: left; vertical-align: top; padding: 6px 8px; border-bottom: 1px solid #ece9e3; overflow-wrap: anywhere; }
th { font-size: 10.5px; color: #636c76; font-weight: 600; text-transform: uppercase; letter-spacing: .03em; background: #faf8f5; }
td.num, th.num { text-align: right; } tr { break-inside: avoid; }
.card { border: 1px solid #e3e1dc; border-radius: 12px; padding: 14px 16px; margin: 12px 0; break-inside: avoid; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; } .grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.score { border: 1px solid #ece9e3; border-radius: 8px; padding: 8px 10px; } .score b { font-size: 18px; display: block; }
.checklist { list-style: none; padding: 0; margin: 4px 0; columns: 2; } .checklist li { margin: 2px 0; break-inside: avoid; }
.yes::before { content: "✓ "; color: #1a7f37; font-weight: 700; } .no::before { content: "✗ "; color: #b42318; font-weight: 700; }
.failure { border: 1px solid #f0a3a3; border-left-width: 5px; border-radius: 10px; padding: 12px 14px; margin: 12px 0; break-inside: avoid; }
.failure.quarantined { border-color: #d8d4cc; }
.failure img { max-width: 100%; max-height: 420px; border: 1px solid #e3e1dc; border-radius: 6px; margin-top: 8px; }
.error { font-family: ui-monospace, Consolas, monospace; font-size: 10.5px; background: #faf8f5; padding: 6px 8px; border-radius: 6px;
         white-space: pre-wrap; overflow-wrap: anywhere; border: 1px solid #ece9e3; }
dl { display: grid; grid-template-columns: auto 1fr; gap: 2px 12px; margin: 6px 0; } dt { color: #636c76; } dd { margin: 0; overflow-wrap: anywhere; }
ol.steps { margin: 4px 0 0; padding-left: 18px; } ol.steps li { margin: 1px 0; font-size: 10.5px; }
ol.steps li.failed { color: #9b1c1c; font-weight: 600; } ol.steps li.healed { color: #0b5ea8; }
ul.checks { margin: 2px 0; padding-left: 16px; font-size: 10.5px; }
code { font-family: ui-monospace, Consolas, monospace; font-size: 10.5px; background: #f4f2ee; padding: 0 4px; border-radius: 4px; overflow-wrap: anywhere; }
.toc { columns: 2; padding-left: 18px; } .toc li { margin: 2px 0; }
.rec { border-left: 4px solid #2a6a46; background: #f4faf6; padding: 8px 12px; margin: 8px 0; border-radius: 0 8px 8px 0; break-inside: avoid; }
.rec.bad { border-color: #c0392b; background: #fdf1f0; } .rec.warn { border-color: #d49b2a; background: #fffaf0; }
.rec b { display: block; }
.heal { font-size: 10.5px; } .heal code.old { text-decoration: line-through; color: #9b1c1c; } .heal code.new { color: #1a7f37; }
.pagebreak { break-before: page; }
footer { margin-top: 32px; color: #636c76; font-size: 10px; border-top: 1px solid #e3e1dc; padding-top: 8px; }
"""


def _e(value: Any) -> str:
    return escape(str(value if value is not None else ""))


def _bar(passed: int, healed: int, failed: int, quarantined: int, total: int, big: bool = False) -> str:
    if not total:
        return "<div class='bar'></div>"
    parts = [("p", passed - healed), ("h", healed), ("f", failed), ("q", quarantined)]
    return (f"<div class='bar{' big' if big else ''}' role='img' aria-label='{_e(passed)} of {_e(total)} passed'>"
            + "".join(f"<span class='{c}' style='width:{100 * n / total:.2f}%'></span>" for c, n in parts if n > 0)
            + "</div>")


def _tally(tests: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for t in tests if t.get("status") in ("PASSED", "HEALED"))
    healed = sum(1 for t in tests if t.get("healed") and t.get("status") in ("PASSED", "HEALED"))
    failed = sum(1 for t in tests if t.get("status") == "FAILED" and not t.get("quarantined"))
    quarantined = sum(1 for t in tests if t.get("status") == "FAILED" and t.get("quarantined"))
    times = [t["duration_ms"] for t in tests if isinstance(t.get("duration_ms"), (int, float))]
    return {"total": len(tests), "passed": passed, "healed": healed, "failed": failed, "quarantined": quarantined,
            "time": sum(times), "avg": (sum(times) / len(times)) if times else None}


def _status_of(test: dict[str, Any]) -> str:
    return _label(test) if not (test.get("status") == "FAILED" and test.get("quarantined")) else "FAILED"


def _steps_html(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return ""
    out = ["<ol class='steps'>"]
    for s in steps:
        status = str(s.get("status") or "")
        cls = "failed" if status == "failed" else "healed" if status == "healed" or (s.get("healing") or {}).get("selected_locator") else ""
        timing = f" · {_duration(s.get('duration_ms'))}" if s.get("duration_ms") is not None else ""
        loc = f" <code>{_e(str(s.get('locator'))[:120])}</code>" if s.get("locator") else ""
        out.append(f"<li class='{cls}'>{_e(s.get('description') or s.get('step_id'))}{loc} "
                   f"<span class='muted'>[{_e(status or '—')}{_e(timing)}]</span></li>")
    out.append("</ol>")
    return "".join(out)


def _recommendations(run: dict[str, Any], tests: list[dict[str, Any]], findings: list[dict[str, Any]] | None) -> list[tuple[str, str, str]]:
    """(level, title, detail): what to do next, worked out from the run's own results."""
    recs: list[tuple[str, str, str]] = []
    failing = [t for t in tests if t.get("status") == "FAILED" and not t.get("quarantined")]
    if failing:
        causes = Counter((t.get("diagnosis") or {}).get("label") for t in failing if t.get("diagnosis"))
        top = f" Most common cause: {causes.most_common(1)[0][0]} ({causes.most_common(1)[0][1]})." if causes else ""
        recs.append(("bad", f"Fix {len(failing)} failing test(s)",
                     "They fail the run. Each is listed under Failures with its diagnosis, failing step and screenshot." + top))
    regressions = run.get("regressions") or []
    if regressions:
        recs.append(("bad", f"Look at {len(regressions)} regression(s) first",
                     "These passed in the previous run and fail now: the most likely sign of a change that broke something."))
    proven = [f for f in findings or [] if f.get("tier") == "proven"]
    if proven:
        recs.append(("bad", f"Fix {len(proven)} proven security issue(s)",
                     "The scan showed the harm itself. See Security findings for evidence and the recommended fix."))
    healed = [t for t in tests if t.get("healed")]
    if healed:
        recs.append(("warn", f"Update {len(healed)} self-healed locator(s)",
                     "The tests passed only because a broken locator was repaired during the run. Review each heal under "
                     "Self-healed tests; accepting it keeps the next run fast and certain."))
    flaky = [t for t in tests if t.get("flaky")]
    if flaky:
        recs.append(("warn", f"Stabilise {len(flaky)} flaky test(s)",
                     "Their result keeps changing between runs: usually timing (content that loads late) or shared state."))
    quarantined = [t for t in tests if t.get("status") == "FAILED" and t.get("quarantined")]
    if quarantined:
        recs.append(("warn", f"Review {len(quarantined)} quarantined failure(s)",
                     "They do not fail the run. Either the app has a problem the test found, or the test assumes too much; "
                     "fix one or the other, then release the test from quarantine."))
    hardening = [f for f in findings or [] if f.get("tier") == "hardening"]
    if hardening:
        recs.append(("warn", f"Add {len(hardening)} missing defence(s)",
                     "Missing security headers or cookie flags: no harm was shown, but each is a cheap layer of protection."))
    analysis = run.get("analysis") or {}
    pages = [p for p in [analysis.get("start"), *(analysis.get("pages") or [])] if p]
    slow = [p for p in pages if (p.get("latency_ms") or 0) > 1500]
    if slow:
        recs.append(("warn", f"Speed up {len(slow)} slow page(s)",
                     "First response over 1.5 s: " + ", ".join(f"{p.get('url')} ({p.get('latency_ms')} ms)" for p in slow[:4])))
    no_alt = sum(p.get("images_without_alt") or 0 for p in pages)
    if no_alt:
        recs.append(("warn", f"Describe {no_alt} image(s) with alt text",
                     "Screen-reader users hear nothing (or the file name) for these images."))
    no_lang = [p.get("url") for p in pages if not p.get("lang")]
    if no_lang:
        recs.append(("warn", f"Declare the language of {len(no_lang)} page(s)",
                     "Add lang=\"…\" to <html> so screen readers use the right voice: " + ", ".join(map(str, no_lang[:4]))))
    s = run.get("summary") or {}
    if s.get("render_only"):
        recs.append(("warn", f"Strengthen {s['render_only']} test(s) that only check a page opens",
                     "A test that cannot fail when its page breaks proves little. Add a check of what the page shows or does."))
    if not recs:
        recs.append(("ok", "Nothing to fix",
                     "Every test that counts passed, nothing regressed and the scan proved no issue. Keep the schedule running."))
    return recs


def render_html(report: dict[str, Any], *, generated_at: datetime | None = None, shared: bool = False) -> str:
    run = report["run"]
    s = run.get("summary") or {}
    tests = run.get("tests") or []
    steps_of = report.get("steps") or {}
    findings = run.get("security_findings")
    analysis = run.get("analysis") or {}
    when = run.get("finished_at") or run.get("started_at") or run.get("created_at") or ""
    generated = (generated_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    status = str(run.get("status") or "")
    total_ms = _span_ms(run.get("started_at") or run.get("created_at"), run.get("finished_at"))
    tally = _tally(tests)
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
           f"<meta name='robots' content='noindex'><title>Run #{_e(run['id'])} · {_e(run.get('project_name'))} — TestSphere report</title>"
           f"<style>{_CSS}</style></head><body><div class='wrap'>"]

    # ── 1. Cover ──
    target = (analysis.get("start") or {}).get("url") or run.get("app_url") or ""
    pages_count = len([p for p in [analysis.get("start"), *(analysis.get("pages") or [])] if p])
    out.append("<section class='cover'>"
               f"<div class='muted small'>TestSphere AI · quality report{' · shared read-only copy' if shared else ''}</div>"
               f"<h1>Run #{_e(run['id'])} · {_e(run.get('project_name'))}</h1>"
               f"<div><span class='badge {_e(status)}'>{_e(status.upper())}</span> "
               f"<span class='muted'>{_e(tally['passed'])} of {_e(tally['total'])} tests passed ({_pct(tally['passed'], tally['total'])}%)</span></div>"
               "<div class='meta'>"
               f"<div><b>Target</b>{_e(target) or '—'}</div>"
               f"<div><b>Trigger</b>{_e(run.get('trigger'))}{(' · ' + _e(run.get('trigger_detail'))) if run.get('trigger_detail') else ''}</div>"
               f"<div><b>Started by</b>{_e(run.get('actor') or '—')}</div>"
               f"<div><b>Finished</b>{_e(str(when)[:16].replace('T', ' '))} UTC</div>"
               f"<div><b>Duration</b>{_e(_duration(total_ms)) or '—'}</div>"
               f"<div><b>Pages analyzed</b>{pages_count or '—'}</div>"
               "</div></section>")

    # Contents
    sections = [("summary", "Executive summary"), ("recommendations", "Recommendations"), ("by-kind", "Results by kind of test"),
                ("by-page", "Coverage by page"), ("pages", "Pages analyzed"), ("security", "Security findings"),
                ("stages", "Pipeline stages"), ("changes", "Regressions, healing and flaky tests"),
                ("failures", "Failures"), ("timing", "Timing"), ("tests", "Every test in detail"), ("method", "How to read this report")]
    out.append("<h2>Contents</h2><ol class='toc'>" + "".join(f"<li><a href='#{k}'>{_e(v)}</a></li>" for k, v in sections) + "</ol>")

    # ── 2. Executive summary ──
    out.append("<h2 id='summary'>Executive summary</h2>")
    narrative = s.get("narrative") or []
    if narrative:
        out.append("<div class='summary'>" + "".join(
            f"<p class='{'verdict' if line.startswith('Verdict:') else ''}'>{_e(line)}</p>" for line in narrative) + "</div>")
    out.append(_bar(tally["passed"], tally["healed"], tally["failed"], tally["quarantined"], tally["total"], big=True))
    out.append("<div class='legend small muted'><span><i style='background:#2a6a46'></i>Passed</span>"
               "<span><i style='background:#3b82c4'></i>Passed after self-healing</span>"
               "<span><i style='background:#c0392b'></i>Failed</span><span><i style='background:#b9b3a8'></i>Failed, quarantined</span></div>")
    proven = sum((s.get("findings") or {}).values()) if s.get("findings") is not None else None
    stats = [("Pass rate", f"{_pct(tally['passed'], tally['total'])}%", "good" if tally["total"] and not tally["failed"] else ""),
             ("Tests run", tally["total"], ""), ("Passed", tally["passed"], "good"),
             ("Failed (counting)", tally["failed"], "bad" if tally["failed"] else ""),
             ("Failed, quarantined", tally["quarantined"], ""), ("Self-healed", s.get("healed", tally["healed"]), ""),
             ("Flaky", s.get("flaky", 0), ""), ("Regressions", len(run.get("regressions") or []), "bad" if run.get("regressions") else ""),
             ("Proven to catch a break", s.get("verified", "—"), ""),
             ("Proven security issues", "—" if proven is None else proven, "bad" if proven else ""),
             ("Hardening suggestions", s.get("hardening", "—"), ""), ("Visual changes", s.get("visual_changes", 0), ""),
             ("Pages covered", len({t.get("page") for t in tests if t.get("page")}) or pages_count or "—", ""),
             ("Test time (sum)", _duration(tally["time"]) or "—", "")]
    out.append("<div class='stats'>" + "".join(
        f"<div class='stat {c}'><b>{_e(v)}</b><span class='muted small'>{_e(k)}</span></div>" for k, v, c in stats) + "</div>")
    unit = s.get("unit_tests") or {}
    if unit:
        parts = [str(unit.get("status") or "")]
        if unit.get("passed") is not None:
            parts.append(f"{unit['passed']} passed")
        if unit.get("failed"):
            parts.append(f"{unit['failed']} failed")
        if unit.get("framework"):
            parts.append(str(unit["framework"]))
        out.append(f"<p class='small'><b>Repository unit tests:</b> {_e(' · '.join(parts))}</p>")

    # ── 3. Recommendations ──
    out.append("<h2 id='recommendations'>Recommendations</h2>")
    for level, title, detail in _recommendations(run, tests, findings):
        out.append(f"<div class='rec {level}'><b>{_e(title)}</b><span class='small'>{_e(detail)}</span></div>")

    # ── 4. Results by kind, coverage by page ──
    out.append("<h2 id='by-kind' class='pagebreak'>Results by kind of test</h2>"
               "<table><colgroup><col style='width:20%'><col><col style='width:7%'><col style='width:7%'><col style='width:7%'>"
               "<col style='width:7%'><col style='width:13%'><col style='width:9%'></colgroup>"
               "<tr><th>Kind</th><th>What it checks</th><th class='num'>Tests</th><th class='num'>Passed</th><th class='num'>Failed</th>"
               "<th class='num'>Quar.</th><th>Pass rate</th><th class='num'>Avg time</th></tr>")
    for key, label in GROUPS:
        group = [t for t in tests if _group(t) == key]
        if not group:
            continue
        g = _tally(group)
        out.append(f"<tr><td><b>{_e(label)}</b></td><td class='small'>{_e(GROUP_ABOUT[key])}</td><td class='num'>{g['total']}</td>"
                   f"<td class='num'>{g['passed']}</td><td class='num'>{g['failed']}</td><td class='num'>{g['quarantined']}</td>"
                   f"<td>{_bar(g['passed'], g['healed'], g['failed'], g['quarantined'], g['total'])}"
                   f"<span class='xsmall muted'>{_pct(g['passed'], g['total'])}%</span></td>"
                   f"<td class='num small'>{_e(_duration(g['avg']))}</td></tr>")
    out.append("</table>")

    by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in tests:
        by_page[t.get("page") or "(no page)"].append(t)
    if by_page:
        out.append("<h3 id='by-page'>Coverage by page</h3><table><colgroup><col style='width:30%'><col><col style='width:8%'>"
                   "<col style='width:8%'><col style='width:8%'><col style='width:14%'></colgroup>"
                   "<tr><th>Page</th><th>Kinds of test</th><th class='num'>Tests</th><th class='num'>Passed</th><th class='num'>Failed</th><th>Pass rate</th></tr>")
        for page, group in sorted(by_page.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            g = _tally(group)
            kinds = Counter(dict(GROUPS).get(_group(t), "Saved tests") for t in group)
            out.append(f"<tr><td class='mono small'>{_e(page)}</td><td class='small'>"
                       + ", ".join(f"{n} {_e(k.lower())}" for k, n in kinds.most_common())
                       + f"</td><td class='num'>{g['total']}</td><td class='num'>{g['passed']}</td><td class='num'>{g['failed'] + g['quarantined']}</td>"
                       f"<td>{_bar(g['passed'], g['healed'], g['failed'], g['quarantined'], g['total'])}</td></tr>")
        out.append("</table>")

    # ── 5. Pages analyzed ──
    out.append("<h2 id='pages' class='pagebreak'>Pages analyzed</h2>")
    audited = [p for p in [analysis.get("start"), *(analysis.get("pages") or [])] if p]
    if not audited:
        out.append("<p class='muted'>This run kept no page analysis (it ran before page audits were recorded, or did not reach planning).</p>")
    for i, page in enumerate(audited):
        out.append(_page_card(page, start=i == 0))

    # ── 6. Security ──
    out.append("<h2 id='security' class='pagebreak'>Security findings</h2>")
    if findings is None:
        out.append("<p class='muted'>No security scan result is kept with this run"
                   + (f" ({_e(next((st.get('detail') for st in run.get('stages') or [] if st.get('key') == 'security'), ''))})" if run.get("stages") else "")
                   + ".</p>")
    elif not findings:
        out.append("<p>The scan found nothing on the pages it checked.</p>")
    else:
        tiers = Counter(f.get("tier") for f in findings)
        out.append("<p class='small'>" + " · ".join(
            f"<b>{tiers[t]}</b> {label}" for t, label in (("proven", "proven (counted)"), ("unconfirmed", "to check by hand"),
                                                         ("hardening", "hardening suggestions")) if tiers[t]) + "</p>")
        out.append("<table><colgroup><col style='width:10%'><col style='width:11%'><col style='width:27%'><col></colgroup>"
                   "<tr><th>Severity</th><th>Tier</th><th>Finding</th><th>Evidence and fix</th></tr>")
        for f in findings:
            evidence = "".join(f"<li>{_e(e)}</li>" for e in f.get("evidence") or [])
            out.append(f"<tr><td><span class='badge {_e(f.get('severity'))}'>{_e(f.get('severity'))}</span></td>"
                       f"<td class='small'>{_e(f.get('tier'))}</td>"
                       f"<td><b>{_e(f.get('title'))}</b><div class='xsmall muted mono'>{_e(f.get('check_id'))}</div>"
                       f"<div class='xsmall muted'>{_e(f.get('component'))}</div></td>"
                       f"<td class='small'>{f'<ul class=checks>{evidence}</ul>' if evidence else ''}"
                       f"{('<div><b>Why:</b> ' + _e(f['root_cause']) + '</div>') if f.get('root_cause') else ''}"
                       f"{('<div><b>Fix:</b> ' + _e(f['recommendation']) + '</div>') if f.get('recommendation') else ''}</td></tr>")
        out.append("</table>")

    # ── 7. Stages ──
    stages = run.get("stages") or []
    if stages:
        out.append("<h2 id='stages'>Pipeline stages</h2><table><colgroup><col style='width:17%'><col style='width:10%'>"
                   "<col style='width:9%'><col></colgroup><tr><th>Stage</th><th>Status</th><th class='num'>Time</th><th>What happened</th></tr>")
        for st in stages:
            took = _span_ms(st.get("started_at"), st.get("finished_at"))
            out.append(f"<tr><td><b>{_e(st.get('label'))}</b></td><td><span class='badge {_e(st.get('status'))}'>{_e(st.get('status'))}</span></td>"
                       f"<td class='num small'>{_e(_duration(took))}</td><td class='small'>{_e(st.get('detail'))}</td></tr>")
        out.append("</table>")

    # ── 8. Regressions, healing, flaky ──
    out.append("<h2 id='changes'>Regressions, healing and flaky tests</h2>")
    regressions = run.get("regressions") or []
    out.append(f"<h3>Regressions ({len(regressions)})</h3>")
    if regressions:
        out.append("<table><tr><th style='width:12%'>Kind</th><th>What</th><th style='width:24%'>Change</th></tr>"
                   + "".join(f"<tr><td>{_e(r.get('kind'))}</td><td>{_e(r.get('name'))}"
                             f"{('<div class=error>' + _e(str(r.get('error'))[:400]) + '</div>') if r.get('error') else ''}</td>"
                             f"<td>{_e(r.get('was'))} → <b>{_e(r.get('now'))}</b></td></tr>" for r in regressions) + "</table>")
    else:
        out.append("<p class='muted small'>" + ("Nothing that passed in run #" + _e(s.get("previous_run_id")) + " fails now."
                                                 if s.get("previous_run_id") else "First run: nothing to compare with.") + "</p>")
    healed = [t for t in tests if t.get("healed")]
    out.append(f"<h3>Self-healed tests ({len(healed)})</h3>")
    if healed:
        out.append("<table><colgroup><col style='width:34%'><col></colgroup><tr><th>Test</th><th>What was repaired</th></tr>")
        for t in healed:
            heals = [st["healing"] for st in steps_of.get(t.get("execution_id")) or [] if (st.get("healing") or {}).get("selected_locator")]
            detail = "".join(
                f"<div class='heal'><code class='old'>{_e(h.get('original_locator'))}</code> → <code class='new'>{_e(h.get('selected_locator'))}</code>"
                f" <span class='muted'>{_e(h.get('strategy') or '')} · {round(float(h.get('confidence') or 0) * 100)}% confidence</span></div>"
                for h in heals) or f"<span class='small'>{_e(t.get('error') or 'A broken locator was repaired during the run')}</span>"
            out.append(f"<tr><td>{_e(t.get('name'))}<div class='xsmall muted'>{_e(t.get('page') or '')}</div></td><td>{detail}</td></tr>")
        out.append("</table>")
    else:
        out.append("<p class='muted small'>No locator needed repairing.</p>")
    flaky = [t for t in tests if t.get("flaky")]
    out.append(f"<h3>Flaky tests ({len(flaky)})</h3>")
    out.append("<ul class='small'>" + "".join(f"<li>{_e(t.get('name'))} <span class='badge {_e(_label(t))}'>{_e(_label(t))}</span></li>" for t in flaky)
               + "</ul>" if flaky else "<p class='muted small'>No test flipped between pass and fail in recent runs.</p>")

    # ── 9. Failures ──
    failures = report.get("failures") or []
    out.append(f"<h2 id='failures' class='pagebreak'>Failures ({len(failures)})</h2>")
    if not failures:
        out.append("<p>No test failed.</p>")
    for f in failures:
        t, d, step = f["test"], f.get("diagnosis") or {}, f.get("step") or {}
        out.append(f"<div class='failure {'quarantined' if t.get('quarantined') else ''}'>"
                   f"<h3 style='margin-top:0'>{_e(t.get('name'))}</h3><div class='small muted'>{_e(dict(GROUPS).get(_group(t)))}"
                   f"{(' · page ' + _e(t.get('page'))) if t.get('page') else ''} · execution #{_e(t.get('execution_id'))}"
                   f"{' · ' + _e(_duration(t.get('duration_ms'))) if t.get('duration_ms') is not None else ''}"
                   f"{' · quarantined: does not fail the run' if t.get('quarantined') else ''}</div>")
        if t.get("about"):
            out.append(f"<p class='small'><b>Protects:</b> {_e(t['about'])}</p>")
        if d:
            out.append(f"<p><span class='badge FAILED'>{_e(d.get('label'))}</span> "
                       f"<span class='muted small'>{_e(d.get('confidence') or '')}{' confidence' if d.get('confidence') else ''}</span><br>"
                       f"{_e(d.get('explanation'))}</p>")
            rows = [(k.title(), d[k]) for k in ("expected", "actual") if d.get(k)]
            if rows:
                out.append("<dl>" + "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in rows) + "</dl>")
            out.append(f"<p class='small'><b>Next step:</b> {_e(d.get('next_step'))}</p>")
        if step:
            out.append(f"<p class='small'><b>Failing step{(' ' + str(f['step_number'])) if f.get('step_number') else ''}:</b> "
                       f"{_e(step.get('description') or step.get('step_id'))}</p>")
        error = step.get("error") or t.get("error")
        if error:
            out.append(f"<div class='error'>{_e(str(error)[:1500])}</div>")
        if f.get("steps"):
            out.append("<h4>All steps</h4>" + _steps_html(f["steps"]))
        if f.get("screenshot"):
            out.append(f"<img alt='Screenshot at the failing step of {_e(t.get('name'))}' src='data:image/png;base64,{f['screenshot']}'>")
        out.append("</div>")

    # ── 10. Timing ──
    timed = [t for t in tests if isinstance(t.get("duration_ms"), (int, float))]
    out.append("<h2 id='timing'>Timing</h2>")
    if timed:
        times = sorted(t["duration_ms"] for t in timed)
        median = times[len(times) // 2]
        p90 = times[min(len(times) - 1, int(len(times) * 0.9))]
        out.append("<div class='stats'>" + "".join(f"<div class='stat'><b>{_e(v)}</b><span class='muted small'>{_e(k)}</span></div>" for k, v in (
            ("Total test time", _duration(sum(times))), ("Median test", _duration(median)), ("90th percentile", _duration(p90)),
            ("Slowest test", _duration(times[-1])), ("Fastest test", _duration(times[0])))) + "</div>")
        out.append(f"<h3>The {min(SLOWEST, len(timed))} slowest tests</h3><table><colgroup><col><col style='width:18%'><col style='width:12%'></colgroup>"
                   "<tr><th>Test</th><th>Kind</th><th class='num'>Time</th></tr>")
        for t in sorted(timed, key=lambda t: -t["duration_ms"])[:SLOWEST]:
            out.append(f"<tr><td>{_e(t.get('name'))}</td><td class='small'>{_e(dict(GROUPS).get(_group(t)))}</td>"
                       f"<td class='num'>{_e(_duration(t['duration_ms']))}</td></tr>")
        out.append("</table>")
    else:
        out.append("<p class='muted'>No test timing was recorded.</p>")

    # ── 11. Every test ──
    out.append(f"<h2 id='tests' class='pagebreak'>Every test in detail ({len(tests)})</h2>")
    rank = {"FAILED": 0, "HEALED": 1, "PASSED": 2}
    for key, label in GROUPS:
        group = sorted((t for t in tests if _group(t) == key), key=lambda t: (rank.get(_label(t), 1), t.get("execution_id", 0)))
        if not group:
            continue
        g = _tally(group)
        failed_note = f" · {g['failed'] + g['quarantined']} failed" if g["failed"] + g["quarantined"] else ""
        out.append(f"<h3>{_e(label)} <span class='muted small'>{g['total']} test{'s' if g['total'] != 1 else ''} · {g['passed']} passed"
                   f"{failed_note}</span></h3>"
                   f"<p class='small muted' style='margin-top:-4px'>{_e(GROUP_ABOUT[key])}</p><table>"
                   "<colgroup><col style='width:4%'><col style='width:30%'><col style='width:12%'><col><col style='width:8%'></colgroup>"
                   "<tr><th>#</th><th>Test</th><th>Result</th><th>What it checks · steps</th><th class='num'>Time</th></tr>")
        for t in group:
            tags = " <span class='badge gray'>Quarantined</span>" if t.get("quarantined") else ""
            tags += " <span class='badge warn'>Flaky</span>" if t.get("flaky") else ""
            body = ""
            if t.get("about"):
                body += f"<div class='small'><b>Protects:</b> {_e(t['about'])}</div>"
            if t.get("status") == "FAILED":
                body += (f"<div class='small'><b>{_e((t.get('diagnosis') or {}).get('label') or 'Failed')}:</b> "
                         f"{_e(str(t.get('error') or '')[:400])}</div>")
            checks = [c for c in t.get("checks") or [] if c]
            if checks:
                body += "<ul class='checks'>" + "".join(f"<li>{_e(c)}</li>" for c in checks) + "</ul>"
            elif not body:
                body += f"<div class='small'>{_e(GROUP_ABOUT[key])}</div>"
            body += _steps_html(steps_of.get(t.get("execution_id")) or [])
            page_line = f"<div class='xsmall muted mono'>{_e(t.get('page'))}</div>" if t.get("page") else ""
            out.append(f"<tr><td class='xsmall muted'>{_e(t.get('execution_id'))}</td><td>{_e(t.get('name'))}{page_line}</td>"
                       f"<td><span class='badge {_e(_status_of(t))}'>{_e(_label(t))}</span>{tags}</td>"
                       f"<td>{body}</td><td class='num small'>{_e(_duration(t.get('duration_ms')))}</td></tr>")
        out.append("</table>")

    # ── 12. Method ──
    out.append("<h2 id='method'>How to read this report</h2><dl class='small'>"
               "<dt>Passed</dt><dd>Every step and check of the test held.</dd>"
               "<dt>Healed</dt><dd>A locator no longer matched; the healer found the same element by its other traits, and the test "
               "passed with it. It refuses look-alikes rather than guess.</dd>"
               "<dt>Failed</dt><dd>A step or check did not hold. A failed test fails the run unless it is quarantined.</dd>"
               "<dt>Quarantined</dt><dd>A test still being earned (written by the AI, or planned without seeing the page in a browser): "
               "it runs and reports, but cannot fail the run until someone trusts it.</dd>"
               "<dt>Proven to catch a break</dt><dd>The test was also run on a deliberately broken copy of its page and failed there, "
               "so its pass means something.</dd>"
               "<dt>Flaky</dt><dd>Its result flipped between pass and fail at least twice in recent runs.</dd>"
               "<dt>Security tiers</dt><dd>Proven: the harm was shown and counts. To check by hand: a real signal the scan could not "
               "prove. Hardening: a missing defence, worth adding, never counted as a vulnerability.</dd>"
               "<dt>Coverage tests</dt><dd>One test per heading, field, button, link and image the analysis saw on each page. They "
               "never press a button or send a form, and only click plain links to pages that loaded.</dd></dl>")

    out.append(f"<footer>Generated {generated} by TestSphere AI · run #{_e(run['id'])}. Screenshots show the page at the failing step. "
               "Every value in this document came from the run itself; nothing was added by a model.</footer></div></body></html>")
    return "".join(out)


def _page_card(page: dict[str, Any], *, start: bool) -> str:
    health = page.get("health") or {}
    sec, a11y, perf = health.get("security") or {}, health.get("accessibility") or {}, health.get("performance") or {}
    counts = page.get("counts") or {}
    status = page.get("status_code")
    out = [f"<div class='card'><h3 style='margin-top:0'>{'Start page · ' if start else ''}{_e(page.get('title') or page.get('url'))}</h3>"
           f"<div class='small mono muted'>{_e(page.get('url'))}"
           + (f" → {_e(page.get('final_url'))}" if page.get("final_url") and page.get("final_url") != page.get("url") else "") + "</div>"]
    if page.get("description"):
        out.append(f"<p class='small'>{_e(page['description'])}</p>")
    facts = [("HTTP status", status, "ok" if status and status < 400 else "bad"),
             ("First response", f"{page.get('latency_ms')} ms" if page.get("latency_ms") is not None else "—", ""),
             ("HTML size", f"{page.get('html_kb')} KB" if page.get("html_kb") else "—", ""),
             ("Language", page.get("lang") or "not declared", "" if page.get("lang") else "warn"),
             ("Read in a browser", "yes" if page.get("rendered_in_browser") else "no (HTML only)", ""),
             ("Visibility checked", "yes" if page.get("visibility_checked") else "no", "")]
    out.append("<div class='grid4' style='grid-template-columns:repeat(6,1fr)'>" + "".join(
        f"<div class='score'><span class='xsmall muted'>{_e(k)}</span><b style='font-size:13px'>"
        f"<span class='badge {c}'>{_e(v)}</span></b></div>" if c else
        f"<div class='score'><span class='xsmall muted'>{_e(k)}</span><b style='font-size:13px'>{_e(v)}</b></div>"
        for k, v, c in facts) + "</div>")
    if health:
        def score(label: str, value: Any, note: str) -> str:
            v = int(value or 0)
            cls = "ok" if v >= 80 else "warn" if v >= 50 else "bad"
            return (f"<div class='score'><span class='xsmall muted'>{_e(label)}</span><b><span class='badge {cls}' style='font-size:14px'>{v}/100</span></b>"
                    f"<span class='xsmall muted'>{_e(note)}</span></div>")
        out.append("<h4>Health audit</h4><div class='grid4'>"
                   + score("Overall", health.get("overall_score"), "weighted: security 35%, accessibility 35%, performance 30%")
                   + score("Security", sec.get("score"), sec.get("summary") or "")
                   + score("Accessibility", a11y.get("score"), a11y.get("status") or "")
                   + score("Performance", perf.get("score"), perf.get("rating") or "") + "</div>")
        checks = [("Served over HTTPS", sec.get("is_https")), ("Valid TLS certificate", sec.get("certificate_valid")),
                  ("Strict-Transport-Security", sec.get("hsts")), ("Content-Security-Policy", sec.get("csp")),
                  ("X-Frame-Options (clickjacking)", sec.get("x_frame_options")), ("X-Content-Type-Options", sec.get("x_content_type_options"))]
        out.append("<div class='grid2'><div><h4>Security headers</h4><ul class='checklist small'>"
                   + "".join(f"<li class='{'yes' if ok else 'no'}'>{_e(k)}</li>" for k, ok in checks if ok is not None) + "</ul></div>"
                   "<div><h4>Accessibility</h4><ul class='checklist small' style='columns:1'>"
                   f"<li class='{'no' if a11y.get('missing_image_alts') else 'yes'}'>Images without alt text: {_e(a11y.get('missing_image_alts', 0))}</li>"
                   f"<li class='{'no' if a11y.get('unlabeled_inputs') else 'yes'}'>Fields without a label or placeholder: {_e(a11y.get('unlabeled_inputs', 0))}</li>"
                   f"<li class='{'no' if a11y.get('unlabeled_buttons') else 'yes'}'>Buttons without text: {_e(a11y.get('unlabeled_buttons', 0))}</li>"
                   f"<li class='{'yes' if page.get('lang') else 'no'}'>Page language declared</li></ul></div></div>")
    if counts:
        labels = {"inputs": "Fields", "buttons": "Buttons", "forms": "Forms", "links": "Links", "headings": "Headings",
                  "images": "Images", "hidden_controls": "Controls hidden on load"}
        out.append("<h4>What is on the page</h4><div class='grid4' style='grid-template-columns:repeat(7,1fr)'>" + "".join(
            f"<div class='score'><b>{_e(counts[k])}</b><span class='xsmall muted'>{_e(labels.get(k, k))}</span></div>"
            for k in labels if k in counts) + "</div>")
    if page.get("headings"):
        out.append("<h4>Headings</h4><ul class='checks'>" + "".join(f"<li>{_e(h)}</li>" for h in page["headings"]) + "</ul>")
    headers = page.get("headers") or {}
    if headers:
        out.append("<h4>Response headers</h4><table><colgroup><col style='width:30%'><col></colgroup>"
                   + "".join(f"<tr><td class='mono small'>{_e(k)}</td><td class='mono small'>{_e(v)}</td></tr>" for k, v in sorted(headers.items()))
                   + "</table>")
    out.append("</div>")
    return "".join(out)
