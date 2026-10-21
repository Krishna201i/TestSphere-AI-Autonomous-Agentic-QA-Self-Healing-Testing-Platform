"""
ingestion/source.py
===================
Resolve an ingestion source (Git URL or local path) to a directory.

Safety:
- Git URLs must be ``https://`` on an allowed host (GitHub, GitLab, Bitbucket by
  default) — no ``file://``, ``ssh``, ``ext::`` or internal hosts, so a request
  cannot make the server read local repositories or reach internal services.
- Clones are shallow, time-limited, run with hooks and credential prompts
  disabled, and land in a dedicated workspace directory.
- Local paths are only accepted when explicitly enabled (development).
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_GIT_HOSTS = frozenset({"github.com", "gitlab.com", "bitbucket.org"})
CLONE_TIMEOUT_S = 120


class SourceError(ValueError):
    """The source cannot be ingested (invalid, not allowed, or fetch failed)."""


def is_git_url(source: str) -> bool:
    return source.strip().lower().startswith(("http://", "https://", "git@", "ssh://", "git://", "file://"))


def repo_name(source: str) -> str:
    if is_git_url(source):
        path = urlsplit(source.strip()).path.rstrip("/")
        return re.sub(r"\.git$", "", path.rsplit("/", 1)[-1]) or "repository"
    return Path(source).resolve().name


def validate_git_url(url: str, allowed_hosts: frozenset[str] = DEFAULT_GIT_HOSTS) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise SourceError("Only https:// Git URLs are supported (e.g. https://github.com/owner/repo).")
    host = (parts.hostname or "").lower()
    if host not in allowed_hosts:
        raise SourceError(f"Git host {host or '?'} is not allowed ({', '.join(sorted(allowed_hosts))}).")
    if parts.username or parts.password:
        raise SourceError("Do not put credentials in the URL; only public repositories are supported.")
    if not re.fullmatch(r"/[\w.-]+/[\w.-]+(?:\.git)?/?", parts.path):
        raise SourceError("Expected a repository URL like https://github.com/owner/repo.")
    return url


def _remove_tree(path: Path) -> bool:
    """Delete *path*, including git's read-only object files on Windows."""
    def make_writable_and_retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if path.exists():
        shutil.rmtree(path, onerror=make_writable_and_retry)
    return not path.exists()


def clone(url: str, workspace: Path, allowed_hosts: frozenset[str] = DEFAULT_GIT_HOSTS) -> Path:
    """Shallow-clone *url* into *workspace* and return the checkout directory."""
    url = validate_git_url(url, allowed_hosts)
    workspace.mkdir(parents=True, exist_ok=True)
    target = workspace / f"{repo_name(url)}-{hashlib.sha1(url.encode()).hexdigest()[:8]}"
    try:
        removed = _remove_tree(target)  # re-ingest: start from a fresh checkout
    except OSError:
        removed = False
    if not removed:  # e.g. a file is locked by another process
        target = target.with_name(f"{target.name}-{int(time.time())}")

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
    cmd = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.longpaths=true", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
           "clone", "--depth", "1", "--single-branch", "--no-tags", url, str(target)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=CLONE_TIMEOUT_S, env=env)
    except FileNotFoundError as exc:
        raise SourceError("git is not installed on the server.") from exc
    except subprocess.TimeoutExpired as exc:
        _remove_tree(target)
        raise SourceError(f"Clone timed out after {CLONE_TIMEOUT_S}s.") from exc
    if result.returncode != 0:
        _remove_tree(target)
        detail = (result.stderr.strip().splitlines() or ["unknown error"])[-1]
        raise SourceError(f"Clone failed: {detail}")
    return target


def resolve_local(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise SourceError(f"Folder not found: {p}")
    return p
