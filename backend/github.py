"""
TestSphere-AI — GitHub REST client for the integrations a team uses daily.

* ``open_fix_pr``: turn a fix patch into a pull request.  The branch starts
  at the commit the patch was built against, the patched files go in as one
  commit (git data API: blobs -> tree -> commit -> ref), and the pull request
  targets the repository's default branch.  Nothing on an existing branch is
  rewritten; if the default branch moved on, GitHub shows any conflict.
* ``set_commit_status``: TestSphere's result on a pushed commit, shown on
  the commit and its pull requests.

Only https://api.github.com is ever called, with the user's own token.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

API = "https://api.github.com"
_REPO_RE = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


class GitHubError(Exception):
    """A readable failure (bad token, no access, conflict...)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def parse_repo(url: str | None) -> tuple[str, str] | None:
    """(owner, name) of an https://github.com/owner/name URL, else None."""
    m = _REPO_RE.match((url or "").strip())
    return (m.group(1), m.group(2)) if m else None


class GitHubClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(
            base_url=API, timeout=20, transport=transport, follow_redirects=False,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "TestSphere-AI"},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubError(f"Could not reach GitHub: {exc}") from exc
        if resp.status_code < 300:
            return resp.json() if resp.content else None
        try:
            detail = resp.json().get("message", "")
        except ValueError:
            detail = resp.text[:200]
        if resp.status_code == 401:
            raise GitHubError("GitHub rejected the token (expired or revoked). Connect GitHub again.", 401)
        if resp.status_code in (403, 404):
            raise GitHubError(
                "The token cannot do this on that repository. Give it access to the repository with "
                "Contents and Pull requests set to Read and write.", resp.status_code)
        raise GitHubError(f"GitHub answered {resp.status_code}: {detail}", resp.status_code)

    # ── Account ─────────────────────────────────────────────────────────
    def user(self) -> dict[str, Any]:
        return self._call("GET", "/user")

    # ── Pull request from a patch ───────────────────────────────────────
    def open_fix_pr(self, owner: str, repo: str, base_sha: str, files: list[tuple[str, str]],
                    branch: str, title: str, body: str) -> dict[str, Any]:
        info = self._call("GET", f"/repos/{owner}/{repo}")
        if not (info.get("permissions") or {}).get("push"):
            raise GitHubError(f"The token cannot push to {owner}/{repo}. Give it Contents: Read and write.", 403)
        base = self._call("GET", f"/repos/{owner}/{repo}/git/commits/{base_sha}")
        entries = []
        for path, content in files:
            blob = self._call("POST", f"/repos/{owner}/{repo}/git/blobs", json={"content": content, "encoding": "utf-8"})
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = self._call("POST", f"/repos/{owner}/{repo}/git/trees", json={"base_tree": base["tree"]["sha"], "tree": entries})
        commit = self._call("POST", f"/repos/{owner}/{repo}/git/commits",
                            json={"message": title, "tree": tree["sha"], "parents": [base_sha]})
        name = branch
        for attempt in range(1, 6):
            try:
                self._call("POST", f"/repos/{owner}/{repo}/git/refs", json={"ref": f"refs/heads/{name}", "sha": commit["sha"]})
                break
            except GitHubError as exc:
                if exc.status != 422 or attempt == 5:  # 422 = branch exists already
                    raise
                name = f"{branch}-{attempt + 1}"
        pr = self._call("POST", f"/repos/{owner}/{repo}/pulls", json={
            "title": title, "head": name, "base": info["default_branch"], "body": body, "maintainer_can_modify": True,
        })
        return {"url": pr["html_url"], "number": pr["number"], "branch": name, "base": info["default_branch"]}

    # ── Commit status ───────────────────────────────────────────────────
    def set_commit_status(self, owner: str, repo: str, sha: str, state: str, description: str,
                          target_url: str | None = None, context: str = "TestSphere") -> None:
        payload = {"state": state, "description": description[:140], "context": context}
        if target_url:
            payload["target_url"] = target_url
        self._call("POST", f"/repos/{owner}/{repo}/statuses/{sha}", json=payload)
