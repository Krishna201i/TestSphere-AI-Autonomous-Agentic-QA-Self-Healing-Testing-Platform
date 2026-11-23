"""
TestSphere-AI — the repository's own unit tests (pipeline stage "unit").

Repository code is never run on the server itself.  Two ways:

* **CI.**  For a GitHub repository, the results of its own CI (check runs:
  GitHub Actions jobs and other apps' checks) on the run's commit are read,
  waiting up to ``UNIT_TESTS_CI_WAIT`` seconds for them to finish.
* **Sandbox.**  Otherwise (no CI checks, or not GitHub), when
  ``SANDBOX_ENABLED``: the repository is copied into a throwaway Docker
  volume, its dependencies are installed in one container (network, but on
  a dedicated network) and its tests run in a second one with **no network
  at all**.  Both are capped (memory, CPU, process count), run as nobody
  with every capability dropped, no privilege escalation and a read-only
  root filesystem, and get no secrets.  Before anything runs, a probe
  checks that the sandbox network cannot reach the cloud metadata service
  (where the server's credentials come from); if it can, nothing runs.

pytest, npm/yarn/pnpm ``test`` scripts (Jest, Vitest, Mocha...) and
``go test`` are recognised.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("testsphere.unit_tests")

# CI conclusions: these pass, the rest of the finished ones fail
_CI_OK = {"success", "neutral", "skipped"}
_CI_IGNORED = {"stale"}
# Checks of ours (commit statuses are not check runs, but a GitHub App could be named so)
_OURS = re.compile(r"^testsphere\b", re.I)
# A check run that has not appeared this long after the commit is taken as no CI
NO_CI_GRACE_S = 60

HELPER_IMAGE = "alpine:3.20"
METADATA_HOST = "169.254.169.254"
OUTPUT_TAIL = 8000
NOBODY = "65534:65534"


# ── CI ──────────────────────────────────────────────────────────────────


def summarize_checks(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Passed / failed / still running among a commit's check runs (ours left out)."""
    checks = []
    for run in runs:
        if _OURS.match(run.get("name") or "") or run.get("conclusion") in _CI_IGNORED:
            continue
        done = run.get("status") == "completed"
        state = ("passed" if run.get("conclusion") in _CI_OK else "failed") if done else "running"
        checks.append({"name": run.get("name"), "state": state, "conclusion": run.get("conclusion"),
                       "url": run.get("html_url") or run.get("details_url")})
    count = {k: sum(1 for c in checks if c["state"] == k) for k in ("passed", "failed", "running")}
    status = "failed" if count["failed"] else "pending" if count["running"] else "passed"
    return {"checks": checks, "status": status, **count}


async def from_ci(repo_url: str, token: str | None, sha: str | None, *, wait: int,
                  client_factory: Callable[[str | None], Any] | None = None,
                  sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                  clock: Callable[[], float] = time.monotonic) -> dict[str, Any] | None:
    """The CI results of *sha* (default: the default branch's newest commit) on
    GitHub, or None when the repository is not on GitHub or has no CI checks."""
    from app.github import GitHubClient, parse_repo

    repo = parse_repo(repo_url)
    if not repo:
        return None
    make = client_factory or GitHubClient
    start = clock()
    with make(token) as gh:
        sha = sha or await asyncio.to_thread(gh.head_commit, *repo)
        while True:
            summary = summarize_checks(await asyncio.to_thread(gh.check_runs, *repo, sha))
            waited = clock() - start
            if not summary["checks"]:
                if waited >= min(wait, NO_CI_GRACE_S):
                    return None
            elif summary["status"] != "pending" or waited >= wait:
                break
            await sleep(min(15.0, max(1.0, wait - waited)))
    return {"source": "ci", "commit": sha, **summary,
            "detail": _ci_detail(summary, sha, wait)}


def _ci_detail(s: dict[str, Any], sha: str, wait: int) -> str:
    head = f"CI on {sha[:7]}: {s['passed']} passed"
    if s["failed"]:
        names = ", ".join(c["name"] for c in s["checks"] if c["state"] == "failed")[:200]
        head += f", {s['failed']} failed ({names})"
    if s["running"]:
        head += f", {s['running']} still running after {wait // 60 or wait} {'min' if wait >= 60 else 's'}"
    return head


# ── Sandbox ─────────────────────────────────────────────────────────────


class SandboxError(Exception):
    """The sandbox cannot run (Docker missing, unsafe network, a step failed to start)."""


@dataclass(frozen=True)
class Plan:
    """How to install and test one kind of project inside the sandbox."""

    framework: str
    image: str
    install: str
    test: str
    no_tests_exit: int | None = None  # the exit code that means "no tests found"


_PY_REQS = ("requirements.txt", "requirements-dev.txt", "requirements-test.txt", "dev-requirements.txt",
            "test-requirements.txt", "requirements/test.txt", "requirements/dev.txt")


def plan_for(root: Path) -> Plan | None:
    """The test plan for the checkout at *root*, or None when it has no tests we can run."""
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            script = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}).get("test") or ""
        except (ValueError, OSError):
            script = ""
        if script and "no test specified" not in script:
            if (root / "pnpm-lock.yaml").is_file():
                pm, install = "pnpm", "corepack pnpm install --frozen-lockfile"
            elif (root / "yarn.lock").is_file():
                pm, install = "yarn", "corepack yarn install --frozen-lockfile"
            else:
                pm = "npm"
                install = ("npm ci" if (root / "package-lock.json").is_file() else "npm install") \
                    + " --no-audit --no-fund"
            test = "npm test" if pm == "npm" else f"corepack {pm} test"
            return Plan(f"{pm} test", "node:22-slim", install, test)
    if (root / "go.mod").is_file() and any(root.rglob("*_test.go")):
        return Plan("go test", "golang:1.23", "go mod download", "go test ./...")
    if any(_own(p, root) for pattern in ("test_*.py", "*_test.py") for p in root.rglob(pattern)):
        reqs = " ".join(f'"{r}"' for r in _PY_REQS)
        install = (
            "python -m venv /work/.ts/venv && . /work/.ts/venv/bin/activate"
            " && pip install -q --disable-pip-version-check pytest"
            f" && for f in {reqs}; do if [ -f \"$f\" ]; then pip install -q -r \"$f\" || exit 1; fi; done"
            " && if [ -f pyproject.toml ] || [ -f setup.py ]; then pip install -q -e . || echo 'note: the project itself"
            " did not install; testing from the source folder'; fi"
        )
        test = ". /work/.ts/venv/bin/activate && python -m pytest -q -p no:cacheprovider --color=no"
        return Plan("pytest", "python:3.12-slim", install, test, no_tests_exit=5)
    return None


_NOT_OURS = {".git", ".venv", "venv", "env", "node_modules", "site-packages", ".tox", "build", "dist"}


def _own(path: Path, root: Path) -> bool:
    """A file of the project itself (not of a virtualenv or an installed dependency)."""
    return not _NOT_OURS.intersection(path.relative_to(root).parts)


Runner = Callable[..., subprocess.CompletedProcess]


def _docker(args: list[str], timeout: float | None = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


def unavailable_reason(docker: Runner = _docker) -> str | None:
    """Why the sandbox cannot run here, or None when it can (Docker answers, the
    network exists and cannot reach the metadata service)."""
    if not settings.SANDBOX_ENABLED:
        return "the sandbox is off (SANDBOX_ENABLED)"
    if docker is _docker and shutil.which("docker") is None:
        return "Docker is not available to this server process"
    try:
        if docker(["info", "--format", "{{.ServerVersion}}"], timeout=20).returncode != 0:
            return "Docker is not reachable (is the Docker socket mounted?)"
        net = settings.SANDBOX_NETWORK
        if docker(["network", "inspect", net], timeout=20).returncode != 0:
            made = docker(["network", "create", "--driver", "bridge", "--label", "testsphere.sandbox=1",
                           "-o", "com.docker.network.bridge.name=ts-sandbox0", net], timeout=30)
            if made.returncode != 0:
                return f"could not create the sandbox network: {made.stderr.strip()[:200]}"
        # Reachable metadata = reachable cloud credentials: refuse to run untrusted code
        probe = docker(["run", "--rm", "--network", net, HELPER_IMAGE, "nc", "-z", "-w", "3", METADATA_HOST, "80"],
                       timeout=120)
        if probe.returncode == 0:
            return (f"the sandbox network can reach the cloud metadata service ({METADATA_HOST}); "
                    "install the firewall rule (deploy/aws-ec2/sandbox-firewall.sh) before running repository code")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Docker did not answer: {exc}"
    return None


def _limits(name: str, network: str) -> list[str]:
    return ["run", "--rm", "--name", name, "--network", network,
            "--memory", settings.SANDBOX_MEMORY, "--memory-swap", settings.SANDBOX_MEMORY,
            "--cpus", settings.SANDBOX_CPUS, "--pids-limit", "512",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
            "--tmpfs", "/tmp:rw,exec,size=512m", "--user", NOBODY,
            "-e", "HOME=/work/.ts/home", "-e", "CI=true", "-e", "COREPACK_HOME=/work/.ts/corepack",
            "-e", "GOPATH=/work/.ts/go", "-e", "GOCACHE=/work/.ts/gocache", "-e", "GOTOOLCHAIN=local",
            "-e", "GOFLAGS=-mod=mod", "-e", "npm_config_cache=/work/.ts/npm", "-e", "PIP_NO_CACHE_DIR=1"]


def _tail(text: str) -> str:
    return text[-OUTPUT_TAIL:]


_COUNT = re.compile(r"(\d+)\s+(passed|failed|errors?)\b", re.I)


def counts(output: str) -> dict[str, int]:
    """Passed / failed counts from the last summary line a runner prints (pytest,
    Jest, Vitest, Mocha), or from ``go test`` package lines."""
    out = {"passed": 0, "failed": 0}
    # TAP summary (node --test, tap): "# pass 3" / "# fail 1"
    tap = dict(re.findall(r"(?m)^# (pass|fail) (\d+)\s*$", output))
    if tap:
        return {"passed": int(tap.get("pass", 0)), "failed": int(tap.get("fail", 0))}
    for line in reversed(output.splitlines()):
        found = _COUNT.findall(line)
        if found:
            for n, word in found:
                key = "passed" if word.lower() == "passed" else "failed"
                out[key] += int(n)
            return out
    # go test: packages that passed; failing tests (or, when none are listed, failing packages)
    out["passed"] = len(re.findall(r"(?m)^ok\s", output))
    out["failed"] = len(re.findall(r"(?m)^\s*--- FAIL:", output)) or len(re.findall(r"(?m)^FAIL\s", output))
    return out


def run_in_sandbox(root: Path, plan: Plan, docker: Runner = _docker) -> dict[str, Any]:
    """Install and run *plan* for the checkout at *root* in throwaway containers.
    Raises ``SandboxError`` when the sandbox itself fails; a failing install or
    failing tests are results, not errors."""
    tag = f"ts-sb-{uuid.uuid4().hex[:10]}"
    volume, helper = tag, f"{tag}-copy"
    try:
        if docker(["volume", "create", "--label", "testsphere.sandbox=1", volume], timeout=30).returncode != 0:
            raise SandboxError("could not create the sandbox volume")
        made = docker(["create", "--name", helper, "-v", f"{volume}:/work", HELPER_IMAGE, "sh", "-c",
                       "mkdir -p /work/.ts/home && chown -R 65534:65534 /work"], timeout=120)
        if made.returncode != 0:
            raise SandboxError(f"could not prepare the sandbox: {made.stderr.strip()[:200]}")
        copied = docker(["cp", f"{root}{'/' if not str(root).endswith('/') else ''}.", f"{helper}:/work/src"], timeout=300)
        if copied.returncode != 0:
            raise SandboxError(f"could not copy the repository into the sandbox: {copied.stderr.strip()[:200]}")
        if docker(["start", "-a", helper], timeout=120).returncode != 0:
            raise SandboxError("could not prepare the sandbox folder")

        common = ["-v", f"{volume}:/work", "-w", "/work/src"]
        install = docker([*_limits(f"{tag}-install", settings.SANDBOX_NETWORK), *common, plan.image,
                          "sh", "-c", plan.install], timeout=settings.SANDBOX_TIMEOUT + 60)
        if install.returncode != 0:
            return {"source": "sandbox", "framework": plan.framework, "status": "error", "passed": 0, "failed": 0,
                    "exit_code": install.returncode, "output": _tail(install.stdout + install.stderr),
                    "detail": f"Sandbox ({plan.framework}): installing the dependencies failed "
                              f"(exit {install.returncode})"}
        # The tests themselves: no network at all
        test = docker([*_limits(f"{tag}-test", "none"), *common, plan.image, "sh", "-c", plan.test],
                      timeout=settings.SANDBOX_TIMEOUT + 60)
    except subprocess.TimeoutExpired:
        docker(["rm", "-f", f"{tag}-install", f"{tag}-test"], timeout=60)
        return {"source": "sandbox", "framework": plan.framework, "status": "error", "passed": 0, "failed": 0,
                "exit_code": None, "output": "",
                "detail": f"Sandbox ({plan.framework}): stopped after {settings.SANDBOX_TIMEOUT} s"}
    finally:
        docker(["rm", "-f", helper], timeout=60)
        docker(["volume", "rm", "-f", volume], timeout=60)

    output = test.stdout + test.stderr
    n = counts(output)
    if plan.no_tests_exit is not None and test.returncode == plan.no_tests_exit:
        status = "none"
    else:
        status = "passed" if test.returncode == 0 else "failed"
    detail = f"Sandbox ({plan.framework}): " + (
        "no tests were collected" if status == "none" else
        f"{n['passed']} passed, {n['failed']} failed" if n["passed"] or n["failed"] else
        ("passed" if status == "passed" else f"failed (exit {test.returncode})"))
    return {"source": "sandbox", "framework": plan.framework, "status": status, **n,
            "exit_code": test.returncode, "output": _tail(output), "detail": detail}
