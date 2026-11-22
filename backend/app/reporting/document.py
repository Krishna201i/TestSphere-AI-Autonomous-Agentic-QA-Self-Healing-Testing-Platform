"""
TestSphere-AI — A run's report as one self-contained document.

``build_report`` gathers what the report needs (the run, each failure's
failing step and its screenshot); ``render_html`` lays it out: a cover with
the verdict, the plain summary and the numbers, the stages, every failure
with its diagnosis, failing step and screenshot, then all tests by type.

The document is static and self-contained: every value is HTML-escaped
(page text from the tested site may contain markup), there are no scripts,
and screenshots are embedded as data URIs, so rendering it to PDF or serving
it on a share link loads nothing from anywhere.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from html import escape
from typing import Any

from backend.artifacts import get_artifact_store
from backend.database.store import Record, Store
from backend.models import TEST_EXECUTIONS

GROUPS = [("smoke", "Smoke"), ("functional", "Goal scenario"), ("explored", "AI-explored goal"), ("content", "Content"),
          ("link", "Linked pages"), ("route", "Code routes"), ("ai", "AI-written tests"), ("saved", "Saved tests")]
GROUP_ABOUT = {"smoke": "Page loads; title and body render", "functional": "The written goal: form filled and its outcome checked",
               "explored": "The goal as the AI explorer reached it, replayed", "content": "The main heading is on the page",
               "link": "Linked page loads with its title and heading", "route": "Route found in the code loads",
               "ai": "Scenario written by the AI planner", "saved": "Saved test"}
MAX_SCREENSHOTS = 12
MAX_SCREENSHOT_BYTES = 2_000_000


def _group(test: dict[str, Any]) -> str:
    return test.get("category") if test.get("category") in GROUP_ABOUT else "saved"


def _label(test: dict[str, Any]) -> str:
    return "HEALED" if test.get("healed") and test.get("status") == "PASSED" else str(test.get("status") or "")


def _duration(ms: Any) -> str:
    if ms is None:
        return ""
    return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def build_report(db: Store, run: Record) -> dict[str, Any]:
    """The run plus, for each failure, its failing step and that step's screenshot."""
    store = get_artifact_store()
    failures, shots = [], 0
    for test in run.get("tests") or []:
        if test.get("status") != "FAILED":
            continue
        execution = db.get(TEST_EXECUTIONS, test["execution_id"]) or {}
        steps = execution.get("steps") or []
        step = next((s for s in steps if s.get("status") == "failed"), steps[-1] if steps else None)
        screenshot = None
        key = (step or {}).get("screenshot")
        if key and shots < MAX_SCREENSHOTS:
            found = store.get(key)
            if found and found[1] == "image/png" and len(found[0]) <= MAX_SCREENSHOT_BYTES:
                screenshot = base64.b64encode(found[0]).decode()
                shots += 1
        failures.append({"test": test, "step": step,
                         "step_number": steps.index(step) + 1 if step in steps else None,
                         "diagnosis": test.get("diagnosis") or execution.get("diagnosis"), "screenshot": screenshot})
    # Failures that fail the run first, then quarantined ones
    failures.sort(key=lambda f: (bool(f["test"].get("quarantined")), f["test"].get("execution_id", 0)))
    return {"run": run, "failures": failures}


_CSS = """
@page { size: A4; margin: 16mm 14mm; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; color: #1f2328;
       font-size: 12px; line-height: 1.5; margin: 0; background: #fff; }
.wrap { max-width: 900px; margin: 0 auto; padding: 24px; }
h1 { font-size: 24px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 28px 0 10px; border-bottom: 1px solid #e3e1dc; padding-bottom: 4px; }
h3 { font-size: 13px; margin: 0 0 6px; }
.muted { color: #636c76; } .small { font-size: 11px; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; border: 1px solid; }
.PASSED { color: #1a7f37; background: #e6f6ea; border-color: #a6dcb4; } .HEALED { color: #0b5ea8; background: #e4f0fb; border-color: #a8cbee; }
.FAILED, .failed { color: #9b1c1c; background: #fde3e3; border-color: #f0a3a3; } .passed { color: #1a7f37; background: #e6f6ea; border-color: #a6dcb4; }
.gray { color: #57606a; background: #f1efeb; border-color: #d8d4cc; }
.summary { border: 1px solid #e3e1dc; background: #faf8f5; border-radius: 10px; padding: 10px 14px; margin: 14px 0; }
.summary p { margin: 2px 0; } .verdict { font-weight: 600; }
.stats { display: flex; gap: 10px; flex-wrap: wrap; margin: 12px 0; }
.stat { border: 1px solid #e3e1dc; border-radius: 10px; padding: 8px 12px; min-width: 110px; }
.stat b { display: block; font-size: 18px; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { text-align: left; vertical-align: top; padding: 6px 8px; border-bottom: 1px solid #ece9e3; overflow-wrap: anywhere; }
th { font-size: 11px; color: #636c76; font-weight: 600; }
tr { break-inside: avoid; }
.failure { border: 1px solid #f0a3a3; border-left-width: 4px; border-radius: 10px; padding: 12px 14px; margin: 12px 0; break-inside: avoid; }
.failure.quarantined { border-color: #d8d4cc; }
.failure img { max-width: 100%; max-height: 420px; border: 1px solid #e3e1dc; border-radius: 6px; margin-top: 8px; }
.error { font-family: ui-monospace, Consolas, monospace; font-size: 11px; background: #faf8f5; padding: 6px 8px; border-radius: 6px;
         white-space: pre-wrap; overflow-wrap: anywhere; }
dl { display: grid; grid-template-columns: auto 1fr; gap: 2px 12px; margin: 6px 0; } dt { color: #636c76; } dd { margin: 0; overflow-wrap: anywhere; }
.group { margin-top: 14px; } .group h3 .muted { font-weight: 400; }
.pagebreak { break-before: page; }
footer { margin-top: 28px; color: #636c76; font-size: 10px; border-top: 1px solid #e3e1dc; padding-top: 6px; }
"""


def _e(value: Any) -> str:
    return escape(str(value if value is not None else ""))


def render_html(report: dict[str, Any], *, generated_at: datetime | None = None, shared: bool = False) -> str:
    run = report["run"]
    s = run.get("summary") or {}
    tests = run.get("tests") or []
    when = run.get("finished_at") or run.get("started_at") or run.get("created_at") or ""
    generated = (generated_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    status = str(run.get("status") or "")
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
           f"<meta name='robots' content='noindex'><title>Run #{_e(run['id'])} · {_e(run.get('project_name'))} — TestSphere report</title>"
           f"<style>{_CSS}</style></head><body><div class='wrap'>"]

    # Cover
    out.append(f"<div class='muted small'>TestSphere AI · test report{' · shared read-only copy' if shared else ''}</div>"
               f"<h1>Run #{_e(run['id'])} · {_e(run.get('project_name'))}</h1>"
               f"<div><span class='badge {_e(status)}'>{_e(status.upper())}</span> "
               f"<span class='muted'>{_e(run.get('trigger'))} · {_e(str(when)[:16].replace('T', ' '))} UTC</span></div>")
    narrative = s.get("narrative") or []
    if narrative:
        out.append("<div class='summary'>" + "".join(
            f"<p class='{'verdict' if line.startswith('Verdict:') else ''}'>{_e(line)}</p>" for line in narrative) + "</div>")
    if s:
        stats = [("Tests passed", f"{s.get('passed', 0)}/{s.get('total', 0)}"),
                 ("Failed", f"{s.get('failed', 0)}" + (f" (+{s['quarantined_failed']} quarantined)" if s.get("quarantined_failed") else "")),
                 ("Self-healed", s.get("healed", 0)), ("Flaky", s.get("flaky", 0)),
                 ("Regressions", len(run.get("regressions") or []))]
        out.append("<div class='stats'>" + "".join(f"<div class='stat'><b>{_e(v)}</b><span class='muted small'>{_e(k)}</span></div>"
                                                     for k, v in stats) + "</div>")

    # Stages
    stages = run.get("stages") or []
    if stages:
        out.append("<h2>Stages</h2><table><colgroup><col style='width:18%'><col style='width:12%'><col></colgroup>"
                   "<tr><th>Stage</th><th>Status</th><th>What happened</th></tr>")
        for st in stages:
            out.append(f"<tr><td>{_e(st.get('label'))}</td><td><span class='badge {_e(st.get('status'))} gray'>{_e(st.get('status'))}</span></td>"
                       f"<td class='small'>{_e(st.get('detail'))}</td></tr>")
        out.append("</table>")

    # Failures
    failures = report.get("failures") or []
    if failures:
        out.append(f"<h2 class='pagebreak'>Failures ({len(failures)})</h2>")
        for f in failures:
            t, d, step = f["test"], f.get("diagnosis") or {}, f.get("step") or {}
            out.append(f"<div class='failure {'quarantined' if t.get('quarantined') else ''}'>"
                       f"<h3>{_e(t.get('name'))}</h3><div class='small muted'>{_e(dict(GROUPS).get(_group(t)))} · execution #{_e(t.get('execution_id'))}"
                       f"{' · ' + _e(_duration(t.get('duration_ms'))) if t.get('duration_ms') is not None else ''}"
                       f"{' · quarantined: does not fail the run' if t.get('quarantined') else ''}</div>")
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
            if f.get("screenshot"):
                out.append(f"<img alt='Screenshot at the failing step of {_e(t.get('name'))}' src='data:image/png;base64,{f['screenshot']}'>")
            out.append("</div>")

    # All tests, by type
    if tests:
        out.append(f"<h2 class='pagebreak'>All tests ({len(tests)})</h2>")
        rank = {"FAILED": 0, "HEALED": 1, "PASSED": 2}
        for key, label in GROUPS:
            group = sorted((t for t in tests if _group(t) == key), key=lambda t: (rank.get(_label(t), 1), t.get("execution_id", 0)))
            if not group:
                continue
            failed = sum(1 for t in group if t.get("status") == "FAILED")
            out.append(f"<div class='group'><h3>{_e(label)} <span class='muted small'>{len(group)} test{'s' if len(group) != 1 else ''}"
                       f"{f' · {failed} failed' if failed else ''}</span></h3><table>"
                       "<colgroup><col style='width:36%'><col style='width:14%'><col><col style='width:9%'></colgroup>"
                       "<tr><th>Test</th><th>Result</th><th>Details</th><th>Time</th></tr>")
            for t in group:
                if t.get("status") == "FAILED":
                    detail = ((t.get("diagnosis") or {}).get("label", "") + ": " if t.get("diagnosis") else "") + str(t.get("error") or "")
                else:
                    detail = " · ".join(c for c in t.get("checks") or [] if c) or GROUP_ABOUT[key]
                    detail += " — a broken locator was healed" if t.get("healed") else ""
                tag = " <span class='badge gray'>Quarantined</span>" if t.get("quarantined") else ""
                out.append(f"<tr><td>{_e(t.get('name'))}</td><td><span class='badge {_e(_label(t))}'>{_e(_label(t))}</span>{tag}</td>"
                           f"<td class='small'>{_e(detail[:400])}</td><td class='small'>{_e(_duration(t.get('duration_ms')))}</td></tr>")
            out.append("</table></div>")

    out.append(f"<footer>Generated {generated} by TestSphere AI · run #{_e(run['id'])}. Screenshots show the page at the failing step."
               "</footer></div></body></html>")
    return "".join(out)
