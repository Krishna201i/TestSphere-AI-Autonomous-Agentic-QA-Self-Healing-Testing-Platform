"""
TestSphere-AI — A run in a few plain sentences.

Built from the run's own numbers, never by a model, so it cannot claim what
did not happen: how many passed, what changed since the previous run, where
the failures are and whether they count, and a verdict.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

GROUP_LABELS = {"smoke": "smoke", "functional": "goal scenario", "explored": "AI-explored goal", "content": "content",
                "link": "linked-page", "route": "code-route", "ai": "AI-written"}
MAX_NAMED = 3


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _verb(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _names(rows: list[dict[str, Any]]) -> str:
    named = ", ".join(f"“{r['name']}”" for r in rows[:MAX_NAMED])
    return named + (f" and {len(rows) - MAX_NAMED} more" if len(rows) > MAX_NAMED else "")


def run_summary(summary: dict[str, Any], results: list[dict[str, Any]], regressions: list[dict[str, Any]]) -> list[str]:
    """Plain sentences about a finished run (*summary* is the run's summary record)."""
    total, passed = summary.get("total", 0), summary.get("passed", 0)
    if not total:
        return ["No tests ran."]
    failed = [r for r in results if r.get("status") == "FAILED"]
    counting = [r for r in failed if not r.get("quarantined")]
    lines = []

    head = f"All {total} tests passed." if passed == total else f"{passed} of {total} tests passed ({round(100 * passed / total)}%)."
    if summary.get("healed"):
        head += f" {_plural(summary['healed'], 'test')} passed only after self-healing repaired a broken locator."
    lines.append(head)

    previous = summary.get("previous_run_id")
    tests_regressed = [g for g in regressions if g.get("kind") == "test"]
    if previous is None:
        lines.append("This is the project's first run, so there is nothing to compare with yet.")
    elif tests_regressed:
        n = len(tests_regressed)
        lines.append(f"{_plural(n, 'test')} passed in run #{previous} and {_verb(n, 'fails', 'fail')} now: "
                     f"{_names(tests_regressed)}.")
    else:
        lines.append(f"Nothing that passed in run #{previous} fails now.")
    reopened = [g for g in regressions if g.get("kind") == "security"]
    if reopened:
        lines.append(f"{_plural(len(reopened), 'resolved security finding')} reopened: {_names(reopened)}.")

    if failed:
        kinds = Counter((r.get("diagnosis") or {}).get("label") for r in failed if r.get("diagnosis"))
        cause = f" Most common cause: {kinds.most_common(1)[0][0].lower()} ({kinds.most_common(1)[0][1]})." if kinds else ""
        if not counting:
            groups = Counter(GROUP_LABELS.get(r.get("category"), "saved") for r in failed)
            where = " and ".join(f"{n} {g}" for g, n in groups.most_common())
            lines.append(f"{_plural(len(failed), 'test')} failed, all quarantined ({where}), so they do not fail the run.{cause}")
        else:
            n = len(counting)
            lines.append(f"{_plural(n, 'test')} failed and {_verb(n, 'fails', 'fail')} the run: {_names(counting)}.{cause}")
            if len(failed) > len(counting):
                lines.append(f"{_plural(len(failed) - len(counting), 'more quarantined test')} failed without counting.")

    extras = []
    if summary.get("flaky"):
        extras.append(f"{_plural(summary['flaky'], 'test')} {_verb(summary['flaky'], 'is', 'are')} flaky "
                      "(results keep changing between runs)")
    if summary.get("visual_changes"):
        extras.append(f"{_plural(summary['visual_changes'], 'visual change')} to review")
    findings = summary.get("findings") or {}
    serious = sum(findings.get(s, 0) for s in ("critical", "high"))
    if serious:
        extras.append(f"{_plural(serious, 'critical or high security finding')}")
    if summary.get("goal_untested"):
        extras.append("parts of the written goal could not be turned into steps")
    if extras:
        lines.append("Also: " + "; ".join(extras) + ".")

    if counting or tests_regressed or reopened or serious:
        lines.append("Verdict: needs attention.")
    else:
        lines.append("Verdict: the app looks healthy" + (", but review the quarantined failures." if failed else "."))
    return lines
