"""The repository's own unit tests: CI results from GitHub, or the sandbox
(throwaway, locked-down Docker containers; the test phase has no network)."""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import settings
from app.pipeline import unit_tests as u

# ── CI ──────────────────────────────────────────────────────────────────


def check(name, status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion, "html_url": f"https://ci/{name}"}


def test_checks_are_summarized_without_ours_or_stale_ones():
    s = u.summarize_checks([check("pytest"), check("lint", conclusion="failure"), check("e2e", "in_progress", None),
                            check("TestSphere", conclusion="failure"), check("old", conclusion="stale"),
                            check("docs", conclusion="skipped")])
    assert [(c["name"], c["state"]) for c in s["checks"]] == [
        ("pytest", "passed"), ("lint", "failed"), ("e2e", "running"), ("docs", "passed")]
    assert (s["passed"], s["failed"], s["running"], s["status"]) == (2, 1, 1, "failed")
    assert u.summarize_checks([check("a"), check("b", "queued", None)])["status"] == "pending"
    assert u.summarize_checks([check("a")])["status"] == "passed"


class FakeGitHub:
    def __init__(self, answers, head="f" * 40):
        self.answers, self.head, self.calls = list(answers), head, []

    def __call__(self, token):
        self.token = token
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def head_commit(self, owner, repo):
        self.calls.append(("head", owner, repo))
        return self.head

    def check_runs(self, owner, repo, sha):
        self.calls.append(("checks", sha))
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.t += s


def ci(gh, sha=None, wait=300, repo="https://github.com/acme/shop"):
    clock = Clock()
    return asyncio.run(u.from_ci(repo, "tok", sha, wait=wait, client_factory=gh, sleep=clock.sleep, clock=clock)), clock


def test_ci_waits_for_running_checks_and_reports_them():
    gh = FakeGitHub([[check("pytest", "in_progress", None)], [check("pytest", "in_progress", None)],
                     [check("pytest", conclusion="failure")]])
    result, clock = ci(gh, sha="a" * 40)
    assert result["status"] == "failed" and result["commit"] == "a" * 40 and result["source"] == "ci"
    assert result["detail"] == "CI on aaaaaaa: 0 passed, 1 failed (pytest)"
    assert result["checks"][0]["url"] == "https://ci/pytest"
    assert 0 < clock.t < 300 and gh.token == "tok"


def test_ci_uses_the_default_branch_head_without_a_commit():
    gh = FakeGitHub([[check("pytest")]], head="b" * 40)
    result, _ = ci(gh)
    assert gh.calls[0] == ("head", "acme", "shop") and result["commit"] == "b" * 40 and result["status"] == "passed"


def test_ci_still_running_after_the_wait_is_pending_not_failed():
    result, clock = ci(FakeGitHub([[check("slow", "in_progress", None)]]), sha="c" * 40, wait=120)
    assert result["status"] == "pending" and clock.t >= 120
    assert "1 still running after 2 min" in result["detail"]


def test_no_checks_or_not_github_is_no_ci():
    result, clock = ci(FakeGitHub([[]]), sha="d" * 40)
    assert result is None and clock.t >= u.NO_CI_GRACE_S
    assert ci(FakeGitHub([[check("x")]]), repo="https://gitlab.com/acme/shop")[0] is None


# ── what the sandbox runs ───────────────────────────────────────────────


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def test_plans_for_python_node_and_go(tmp_path):
    py = u.plan_for(write(tmp_path / "py", {"tests/test_a.py": "", "requirements.txt": "x"}))
    assert (py.framework, py.image, py.no_tests_exit) == ("pytest", "python:3.12-slim", 5)
    assert '"requirements.txt"' in py.install and "pytest -q" in py.test

    def node(lock):
        files = {"package.json": json.dumps({"scripts": {"test": "vitest run"}})}
        if lock:
            files[lock] = ""
        return u.plan_for(write(tmp_path / f"node-{lock}", files))

    assert node(None).install.startswith("npm install") and node(None).test == "npm test"
    assert node("package-lock.json").install.startswith("npm ci")
    assert node("yarn.lock").install == "corepack yarn install --frozen-lockfile"
    assert node("pnpm-lock.yaml").test == "corepack pnpm test"

    go = u.plan_for(write(tmp_path / "go", {"go.mod": "module x", "x_test.go": ""}))
    assert (go.framework, go.test) == ("go test", "go test ./...")


def test_nothing_to_run_is_no_plan(tmp_path):
    npm_init = {"package.json": json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}})}
    assert u.plan_for(write(tmp_path / "a", npm_init)) is None
    # Tests inside a virtualenv or installed packages are not the project's
    assert u.plan_for(write(tmp_path / "b", {".venv/lib/x/test_x.py": "", "node_modules/y/test_y.py": ""})) is None


@pytest.mark.parametrize(("output", "expected"), [
    ("..F\n1 failed, 2 passed in 0.1s\n", (2, 1)),                                  # pytest
    ("=== 3 passed, 1 error in 1s ===", (3, 1)),                                     # pytest with an error
    ("Tests:       1 failed, 4 passed, 5 total\nTime: 1s", (4, 1)),                  # Jest
    (" Tests  2 failed | 7 passed (9)\n", (7, 2)),                                   # Vitest
    ("# tests 3\n# pass 2\n# fail 1\n", (2, 1)),                                     # node --test (TAP)
    ("ok  \tex/a\t0.1s\n--- FAIL: TestB\nFAIL\tex/b\t0.2s\n", (1, 1)),               # go test: 1 package ok, 1 test failed
    ("ok  \tex/a\t0.1s\nFAIL\tex/b [build failed]\n", (1, 1)),                       # go test: a package that did not build
])
def test_counts_from_each_runners_summary(output, expected):
    n = u.counts(output)
    assert (n["passed"], n["failed"]) == expected


# ── the sandbox, with Docker faked ──────────────────────────────────────


class FakeDocker:
    """Records docker calls; answers by the first argument (and the image run)."""

    def __init__(self, **codes):
        self.calls, self.codes = [], codes

    def __call__(self, args, timeout=60):
        self.calls.append(args)
        key = args[0]
        if key == "run":
            key = "test" if "none" in args else "install" if "sh" in args else "probe"
        if key == "network" and args[1] == "inspect":
            key = "inspect"
        code = self.codes.get(key, 0)
        if isinstance(code, Exception):
            raise code
        out = self.codes.get(f"{key}_out", "")
        return subprocess.CompletedProcess(args, code, out, "")

    def run_of(self, kind):
        return next(a for a in self.calls if a[0] == "run" and (("none" in a) == (kind == "test")) and "sh" in a)


@pytest.fixture
def sandbox_on(monkeypatch):
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", True)


def test_the_sandbox_is_refused_when_off_unreachable_or_unsafe(sandbox_on, monkeypatch):
    assert u.unavailable_reason(FakeDocker(probe=1)) is None
    # The probe reached the metadata service: refuse to run repository code
    assert "can reach the cloud metadata service" in u.unavailable_reason(FakeDocker(probe=0))
    assert "not reachable" in u.unavailable_reason(FakeDocker(info=1))
    created = FakeDocker(inspect=1, probe=1)
    assert u.unavailable_reason(created) is None
    assert ["network", "create"] == created.calls[2][:2] and "com.docker.network.bridge.name=ts-sandbox0" in created.calls[2]
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", False)
    assert u.unavailable_reason(FakeDocker(probe=1)) == "the sandbox is off (SANDBOX_ENABLED)"


def test_tests_run_locked_down_and_offline_and_everything_is_removed(sandbox_on, tmp_path):
    plan = u.plan_for(write(tmp_path, {"test_a.py": ""}))
    docker = FakeDocker(test=1, test_out="F.\n1 failed, 1 passed in 0.1s\n")
    result = u.run_in_sandbox(tmp_path, plan, docker)

    assert result["status"] == "failed" and (result["passed"], result["failed"]) == (1, 1)
    assert result["detail"] == "Sandbox (pytest): 1 passed, 1 failed" and "1 failed, 1 passed" in result["output"]
    install, test = docker.run_of("install"), docker.run_of("test")
    for args in (install, test):
        flags = " ".join(args)
        for needed in ("--cap-drop ALL", "--security-opt no-new-privileges", "--read-only", "--user 65534:65534",
                       f"--memory {settings.SANDBOX_MEMORY}", "--pids-limit 512"):
            assert needed in flags
        assert not any(a.startswith(("-e GITHUB", "--privileged")) for a in args)
        assert "/var/run/docker.sock" not in flags
    assert install[install.index("--network") + 1] == settings.SANDBOX_NETWORK
    assert test[test.index("--network") + 1] == "none"  # the tests themselves: no network at all
    assert docker.calls[-2][:2] == ["rm", "-f"] and docker.calls[-1][:3] == ["volume", "rm", "-f"]


def test_install_failure_timeout_and_no_tests_are_results(sandbox_on, tmp_path):
    plan = u.plan_for(write(tmp_path, {"test_a.py": ""}))
    failed_install = u.run_in_sandbox(tmp_path, plan, FakeDocker(install=1, install_out="No matching distribution"))
    assert failed_install["status"] == "error" and "installing the dependencies failed" in failed_install["detail"]

    none = u.run_in_sandbox(tmp_path, plan, FakeDocker(test=5))
    assert none["status"] == "none" and none["detail"] == "Sandbox (pytest): no tests were collected"

    slow = FakeDocker(test=subprocess.TimeoutExpired("docker", 1))
    result = u.run_in_sandbox(tmp_path, plan, slow)
    assert result["status"] == "error" and "stopped after" in result["detail"]
    assert any(a[:2] == ["rm", "-f"] and any(x.endswith("-test") for x in a) for a in slow.calls)
    assert slow.calls[-1][:3] == ["volume", "rm", "-f"]


def test_a_sandbox_that_cannot_start_raises_and_still_cleans_up(sandbox_on, tmp_path):
    plan = u.plan_for(write(tmp_path, {"test_a.py": ""}))
    docker = FakeDocker(cp=1)
    with pytest.raises(u.SandboxError, match="could not copy"):
        u.run_in_sandbox(tmp_path, plan, docker)
    assert docker.calls[-1][:3] == ["volume", "rm", "-f"]


# ── for real (Docker needed): TESTSPHERE_SANDBOX_IT=1 ───────────────────


real_docker = pytest.mark.skipif(
    os.getenv("TESTSPHERE_SANDBOX_IT") != "1" or shutil.which("docker") is None,
    reason="runs real containers: set TESTSPHERE_SANDBOX_IT=1 with Docker available")


@real_docker
def test_real_sandbox_runs_tests_and_contains_them(sandbox_on, tmp_path):
    write(tmp_path, {
        "calc.py": "def add(a, b):\n    return a + b\n",
        "tests/test_calc.py": "from calc import add\n\ndef test_ok():\n    assert add(2, 2) == 4\n\n"
                              "def test_wrong():\n    assert add(2, 2) == 5\n",
        "tests/test_escape.py": (
            "import os, socket, pytest\n\n"
            "def test_no_network():\n    with pytest.raises(OSError):\n"
            "        socket.create_connection(('1.1.1.1', 53), timeout=3)\n\n"
            "def test_no_metadata():\n    with pytest.raises(OSError):\n"
            "        socket.create_connection(('169.254.169.254', 80), timeout=3)\n\n"
            "def test_nobody_and_read_only():\n    assert os.getuid() == 65534\n"
            "    with pytest.raises(OSError):\n        open('/etc/x', 'w')\n\n"
            "def test_no_server_secrets():\n    assert 'GITHUB_TOKEN' not in os.environ\n"),
    })
    assert u.unavailable_reason() is None
    result = u.run_in_sandbox(tmp_path, u.plan_for(tmp_path))
    assert result["status"] == "failed", result["output"]
    assert (result["passed"], result["failed"]) == (5, 1), result["output"]
    assert "test_wrong" in result["output"]
