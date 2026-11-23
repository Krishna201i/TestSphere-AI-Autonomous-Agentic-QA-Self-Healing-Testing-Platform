"""AI fixes for failing repository tests: only edits to the project's source,
applied to a copy, and kept only when the sandbox shows every test passing."""

import asyncio
import os
import shutil

import pytest

from app.config import settings
from app.pipeline import ai_fix
from app.pipeline import unit_tests as u

CALC = "def add(a, b):\n    return a - b\n"
TEST = "from calc import add\n\ndef test_add():\n    assert add(2, 2) == 4\n"
FAILING_OUTPUT = ("F\n    def test_add():\n>       assert add(2, 2) == 4\nE       assert 0 == 4\n\n"
                  "tests/test_calc.py:4: AssertionError\n1 failed in 0.01s\n")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_WORKSPACE", str(tmp_path / "ws"))
    root = tmp_path / "shop"
    (root / "tests").mkdir(parents=True)
    (root / "calc.py").write_text(CALC, encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8")
    return root


def failing(passed=0, failed=1, output=FAILING_OUTPUT):
    return {"source": "sandbox", "status": "failed", "passed": passed, "failed": failed, "output": output,
            "detail": f"Sandbox (pytest): {passed} passed, {failed} failed"}


FIX = {"explanation": "add() subtracted.", "edits": [{"file": "calc.py", "search": "a - b", "replace": "a + b"}]}


class FakeModel:
    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    async def generate_json(self, request):
        self.prompts.append(request.prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeSandbox:
    """Passes when calc.py adds, fails otherwise; records what it ran on."""

    def __init__(self):
        self.seen = []

    def __call__(self, root, plan):
        code = (root / "calc.py").read_text(encoding="utf-8")
        self.seen.append(code)
        if "a + b" in code:
            return {"status": "passed", "passed": 1, "failed": 0, "output": "1 passed", "detail": "1 passed"}
        return {"status": "failed", "passed": 0, "failed": 1, "output": "still 1 failed", "detail": "0 passed, 1 failed"}


def propose(repo, model, sandbox=None, result=None):
    sandbox = sandbox or FakeSandbox()
    plan = u.plan_for(repo)
    return asyncio.run(ai_fix.propose(repo, plan, result or failing(), client=model, sandbox=sandbox)), sandbox


# ── what may be changed ─────────────────────────────────────────────────


@pytest.mark.parametrize(("path", "is_test"), [
    ("tests/test_calc.py", True), ("calc_test.py", True), ("src/sum.test.js", True), ("src/a.spec.tsx", True),
    ("pkg/x_test.go", True), ("__tests__/a.js", True), ("calc.py", False), ("src/sum.js", False), ("pkg/x.go", False),
])
def test_test_files_are_recognised(path, is_test):
    assert ai_fix.is_test_file(path) is is_test


def test_the_model_sees_the_failing_output_and_the_code_under_test(repo):
    files = ai_fix.relevant_files(FAILING_OUTPUT, repo)
    assert files == ["calc.py", "tests/test_calc.py"]  # source first; the test as context
    prompt = ai_fix.build_prompt(FAILING_OUTPUT, repo, files)
    assert "<<<UNTRUSTED test output>>>" in prompt and "assert 0 == 4" in prompt
    assert "source file: calc.py" in prompt and "test file (do not edit): tests/test_calc.py" in prompt


def test_edits_are_refused_unless_safe(repo):
    E = ai_fix.Edit
    for edit, why in [
        (E(file="tests/test_calc.py", search="== 4", replace="== 0"), "test files are not changed"),
        (E(file="../outside.py", search="x", replace="y"), "not a file of the repository"),
        (E(file="missing.py", search="x", replace="y"), "not a file of the repository"),
        (E(file="calc.py", search="nothing like this", replace="y"), "occurs 0 times"),
        (E(file="calc.py", search="a", replace="y"), "occurs 3 times"),
    ]:
        with pytest.raises(ai_fix.EditError, match=why):
            ai_fix.apply_edits(repo, [edit])
    # All or nothing: one bad edit leaves even the good one unapplied
    with pytest.raises(ai_fix.EditError):
        ai_fix.apply_edits(repo, [E(file="calc.py", search="a - b", replace="a + b"),
                                  E(file="tests/test_calc.py", search="4", replace="0")])
    assert (repo / "calc.py").read_text(encoding="utf-8") == CALC


# ── propose: verified in the sandbox, or nothing ────────────────────────


def test_a_fix_is_kept_only_once_the_tests_pass_with_it(repo):
    result, sandbox = propose(repo, FakeModel(FIX))
    assert result["status"] == "verified" and result["attempts"] == 1
    assert result["before"] == {"passed": 0, "failed": 1} and result["after"] == {"passed": 1, "failed": 0}
    [changed] = result["files"]
    assert changed["path"] == "calc.py" and changed["content"] == "def add(a, b):\n    return a + b\n"
    assert "-    return a - b\n+    return a + b" in changed["diff"]
    assert sandbox.seen == ["def add(a, b):\n    return a + b\n"]
    assert (repo / "calc.py").read_text(encoding="utf-8") == CALC  # tried on a copy; the checkout is untouched
    assert list((repo.parent / "ws").iterdir()) == []  # and the copy is gone


def test_a_second_attempt_is_told_what_still_failed(repo):
    wrong = {"explanation": "guess", "edits": [{"file": "calc.py", "search": "a - b", "replace": "b - a"}]}
    model = FakeModel(wrong, FIX)
    result, sandbox = propose(repo, model)
    assert result["status"] == "verified" and result["attempts"] == 2
    assert "still 1 failed" in model.prompts[1] and "previous change did not make every test pass" in model.prompts[1]
    assert len(sandbox.seen) == 2


def test_weakening_a_test_is_refused_and_never_run(repo):
    cheat = {"explanation": "", "edits": [{"file": "tests/test_calc.py", "search": "== 4", "replace": "== 0"}]}
    result, sandbox = propose(repo, FakeModel(cheat, cheat))
    assert result["status"] == "not_found" and "test files are not changed" in result["note"]
    assert sandbox.seen == []


def test_no_fix_bad_answers_and_fewer_passing_tests_are_not_kept(repo):
    result, _ = propose(repo, FakeModel({"explanation": "It is the test that is wrong.", "edits": []}))
    assert result == {"status": "not_found", "attempts": 2,
                      "note": "the model found no fix: It is the test that is wrong."}

    result, _ = propose(repo, FakeModel({"edits": "not a list"}, TimeoutError()))
    assert result["status"] == "not_found" and "could not be used" in result["note"]

    # Passing, but with fewer tests passing than before (tests deleted or skipped): not a fix
    result, _ = propose(repo, FakeModel(FIX, FIX), result=failing(passed=5, failed=1))
    assert result["status"] == "not_found"


# ── for real: the sandbox verifies the fix (TESTSPHERE_SANDBOX_IT=1) ─────


@pytest.mark.skipif(os.getenv("TESTSPHERE_SANDBOX_IT") != "1" or shutil.which("docker") is None,
                    reason="runs real containers: set TESTSPHERE_SANDBOX_IT=1 with Docker available")
def test_real_sandbox_verifies_the_fix(repo, monkeypatch):
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", True)
    plan = u.plan_for(repo)
    before = u.run_in_sandbox(repo, plan)
    assert before["status"] == "failed", before["output"]
    result = asyncio.run(ai_fix.propose(repo, plan, before, client=FakeModel(FIX)))
    assert result["status"] == "verified", result
    assert result["after"] == {"passed": 1, "failed": 0}
