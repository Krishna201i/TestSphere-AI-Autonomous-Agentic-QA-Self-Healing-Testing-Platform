"""
TestSphere-AI — AI fixes for the repository's failing tests, verified before
anyone sees them.

When the sandbox (``app.pipeline.unit_tests``) ran the repository's tests and
some failed, and a real model is configured, the model reads the failing
output and the source files it points at and proposes a small change to the
**source**.  The change is applied to a copy of the checkout and the tests run
again in the sandbox.  Only a change after which every test passes, with no
fewer tests passing than before, is kept: as a fix patch a person reviews and
approves as a pull request.  A second attempt is told what the first left
failing.

Rules, enforced in code (a fooled model still cannot do harm):
* Edits are search/replace on files that already exist inside the repository,
  and each search text must occur in its file exactly once.
* Test files are never edited: a failure is fixed in the code, not by
  weakening the test.
* The repository's code and test output are untrusted (fenced in the prompt);
  nothing the model writes runs anywhere but the sandbox.
* Any model, parse or sandbox problem degrades to "no fix"; the run's results
  stand as they are.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from agents.llm.untrusted import UNTRUSTED_RULE, fence
from app.config import settings

logger = logging.getLogger("testsphere.ai_fix")

MAX_ATTEMPTS = 2
MAX_FILES = 6
MAX_FILE_BYTES = 30_000
MAX_PROMPT_FILES_BYTES = 60_000
MAX_EDITS = 8
_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go"}
_SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "site-packages", ".tox", "build", "dist", ".ts"}

_SYSTEM = (
    "You fix bugs in a software project so that its failing tests pass. You get the failing test output and "
    "source files. Change the source code, never the tests: the tests describe the intended behaviour. Make the "
    "smallest change that fixes the cause. Answer with JSON only: "
    '{"explanation": "one or two sentences on the cause and the fix", '
    '"edits": [{"file": "path/as/given", "search": "exact text to replace, copied from the file, unique in it", '
    '"replace": "the new text"}]}. If you cannot find a fix, answer {"explanation": "why", "edits": []}. '
    + UNTRUSTED_RULE
)


class Edit(BaseModel):
    file: str = Field(..., min_length=1, max_length=300)
    search: str = Field(..., min_length=1, max_length=20_000)
    replace: str = Field("", max_length=20_000)


class Proposal(BaseModel):
    explanation: str = Field("", max_length=2000)
    edits: list[Edit] = Field(default_factory=list, max_length=MAX_EDITS)


class EditError(ValueError):
    """An edit the model proposed that cannot be applied safely."""


def enabled() -> bool:
    """AI fixes run when ``AI_TEST_FIX`` is on, or on "auto" with a real (non-mock) model."""
    from agents.llm.config import LLMConfig

    mode = settings.AI_TEST_FIX
    if mode == "off":
        return False
    if mode == "on":
        return True
    return LLMConfig.from_env().provider != "mock"


_TEST_NAME = re.compile(r"(^test_.*\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$)")
_TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs", "e2e"}


def is_test_file(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    return bool(_TEST_NAME.search(parts[-1])) or bool(_TEST_DIRS.intersection(parts[:-1]))


def _candidates(root: Path) -> list[str]:
    out = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and path.suffix in _SOURCE_SUFFIXES and not _SKIP_DIRS.intersection(rel.split("/")) \
                and path.stat().st_size <= MAX_FILE_BYTES:
            out.append(rel)
    return out


_PATH_IN_OUTPUT = re.compile(r"(?:/work/src/)?((?:[\w.@-]+/)*[\w.@-]+\.(?:py|js|jsx|ts|tsx|mjs|cjs|go))\b")


def relevant_files(output: str, root: Path) -> list[str]:
    """The files to show the model: those the failure output names (source before
    tests), else, in a small project, all of its source files."""
    known = _candidates(root)
    named: list[str] = []
    for match in _PATH_IN_OUTPUT.finditer(output):
        text = match.group(1)
        hit = next((k for k in known if k == text or k.endswith("/" + text) or text.endswith("/" + k)), None)
        if hit and hit not in named:
            named.append(hit)
    # The code under test is often only imported by the failing test: add the
    # project's own source files when there are few of them
    sources = [k for k in known if not is_test_file(k)]
    if len(sources) <= MAX_FILES:
        named += [s for s in sources if s not in named]
    named.sort(key=is_test_file)  # source files first
    return named[:MAX_FILES]


def build_prompt(output: str, root: Path, files: list[str], previous: str | None = None) -> str:
    parts = ["The project's tests fail. Fix the source code so that they pass.", "",
             fence("test output", output[-6000:])]
    budget = MAX_PROMPT_FILES_BYTES
    for rel in files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        if len(text) > budget:
            break
        budget -= len(text)
        role = "test file (do not edit)" if is_test_file(rel) else "source file"
        parts += ["", f"{role}: {rel}", fence(f"file {rel}", text)]
    if previous:
        parts += ["", "Your previous change did not make every test pass. The tests after it:",
                  fence("test output after the previous change", previous[-4000:])]
    return "\n".join(parts)


def apply_edits(root: Path, edits: list[Edit]) -> dict[str, tuple[str, str]]:
    """Apply *edits* under *root*; returns {file: (before, after)}.  Raises
    ``EditError`` for anything unsafe or ambiguous, leaving files untouched."""
    if not edits:
        raise EditError("no change proposed")
    base = root.resolve()
    changed: dict[str, tuple[str, str]] = {}
    for edit in edits:
        rel = edit.file.replace("\\", "/").lstrip("/").removeprefix("work/src/")
        target = (root / rel).resolve()
        if base not in target.parents or not target.is_file():
            raise EditError(f"{edit.file}: not a file of the repository")
        rel = target.relative_to(base).as_posix()
        if is_test_file(rel):
            raise EditError(f"{rel}: test files are not changed")
        if _SKIP_DIRS.intersection(rel.split("/")):
            raise EditError(f"{rel}: not the project's own code")
        before, current = changed.get(rel, (None, None))
        if current is None:
            before = current = target.read_text(encoding="utf-8")
        if current.count(edit.search) != 1:
            raise EditError(f"{rel}: the text to replace occurs {current.count(edit.search)} times, not once")
        changed[rel] = (before, current.replace(edit.search, edit.replace, 1))
    for rel, (_before, after) in changed.items():
        (root / rel).write_text(after, encoding="utf-8")
    return changed


def unified_diff(rel: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))


def _copy(root: Path) -> Path:
    """A scratch copy of the checkout to try a change on (``<tmp>/src``; delete ``<tmp>``)."""
    workspace = Path(settings.INGEST_WORKSPACE)
    workspace.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="aifix-", dir=workspace)) / "src"
    shutil.copytree(root, dest, ignore=shutil.ignore_patterns(".git", "node_modules", ".venv", "__pycache__"))
    return dest


async def propose(root: Path, plan: Any, failing: dict[str, Any], *, client: Any = None,
                  sandbox: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """A verified fix for the failing sandbox result *failing* of the checkout at
    *root*, or why there is none: ``{"status": "verified", ...}`` with the
    explanation, files (diff and new contents) and the before/after counts, or
    ``{"status": "not_found", "note": ...}``."""
    from agents.llm.exceptions import LLMError
    from agents.llm.schemas import LLMRequest
    from app.pipeline import unit_tests

    sandbox = sandbox or unit_tests.run_in_sandbox
    if client is None:
        try:
            from agents.llm.factory import create_llm_client

            client = create_llm_client()
        except Exception as exc:  # noqa: BLE001 - misconfigured provider, missing key...
            return {"status": "not_found", "attempts": 0, "note": f"no AI model available ({exc})"}

    files = relevant_files(failing.get("output") or "", root)
    if not any(not is_test_file(f) for f in files):
        return {"status": "not_found", "attempts": 0, "note": "the failure points at no source file to change"}
    previous: str | None = None
    note = "the model proposed no change"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = LLMRequest(prompt=build_prompt(failing.get("output") or "", root, files, previous),
                             system_instruction=_SYSTEM, response_format="json")
        try:
            raw = await asyncio.wait_for(client.generate_json(request), timeout=settings.AI_FIX_TIMEOUT)
            proposal = Proposal.model_validate(raw)
        except (TimeoutError, LLMError, ValidationError) as exc:
            note = f"the model's answer could not be used ({type(exc).__name__})"
            continue
        except Exception as exc:  # noqa: BLE001 - never let a fix attempt break a run
            logger.warning("AI test fix errored: %s", exc)
            note = "the model could not be asked"
            break
        if not proposal.edits:
            note = f"the model found no fix: {proposal.explanation[:300]}" if proposal.explanation else note
            break
        copy = await asyncio.to_thread(_copy, root)
        try:
            try:
                changed = await asyncio.to_thread(apply_edits, copy, proposal.edits)
            except EditError as exc:
                note, previous = f"a proposed edit was refused ({exc})", f"Your edit was refused: {exc}"
                continue
            after = await asyncio.to_thread(sandbox, copy, plan)
        finally:
            await asyncio.to_thread(shutil.rmtree, copy.parent, True)
        if after["status"] == "passed" and after["passed"] >= failing.get("passed", 0) and after["failed"] == 0:
            return {
                "status": "verified", "attempts": attempt, "explanation": proposal.explanation.strip(),
                "framework": plan.framework,
                "before": {"passed": failing.get("passed", 0), "failed": failing.get("failed", 0)},
                "after": {"passed": after["passed"], "failed": after["failed"]},
                "files": [{"path": rel, "diff": unified_diff(rel, b, a), "verified": True, "content": a}
                          for rel, (b, a) in changed.items()],
            }
        note = f"no change made every test pass ({after['detail']})"
        previous = after.get("output") or after["detail"]
    return {"status": "not_found", "attempts": MAX_ATTEMPTS, "note": note}
