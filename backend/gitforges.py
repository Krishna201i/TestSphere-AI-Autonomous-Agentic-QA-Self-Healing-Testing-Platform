"""
TestSphere-AI — Fix patches as GitLab merge requests and Bitbucket pull requests.

The GitHub flow lives in ``backend/github.py``; this module gives gitlab.com
and bitbucket.org the same ``open_fix_pr``: the patched files are committed on
a new branch made from the commit the patch was built against, and a merge /
pull request to the default branch is opened.  The credentials are the ones
saved under Profile → Integrations → Git credentials.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from backend.github import GitHubError

GITLAB_API = "https://gitlab.com/api/v4"
BITBUCKET_API = "https://api.bitbucket.org/2.0"

# https://gitlab.com/group/subgroup/project(.git) and https://bitbucket.org/workspace/repo(.git)
_GITLAB_RE = re.compile(r"^https://gitlab\.com/((?:[\w.-]+/)+[\w.-]+?)(?:\.git)?/?$")
_BITBUCKET_RE = re.compile(r"^https://bitbucket\.org/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def parse_forge_repo(url: str | None) -> tuple[str, str] | None:
    """``("gitlab", "group/project")`` or ``("bitbucket", "workspace/repo")``, else None."""
    url = (url or "").strip()
    if m := _GITLAB_RE.match(url):
        return "gitlab", m.group(1)
    if m := _BITBUCKET_RE.match(url):
        return "bitbucket", f"{m.group(1)}/{m.group(2)}"
    return None


class _ForgeClient:
    name = "Git host"

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> _ForgeClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubError(f"Could not reach {self.name}: {exc}") from exc
        if resp.status_code < 300:
            return resp.json() if resp.content else None
        try:
            body = resp.json()
            detail = body.get("message") or (body.get("error") or {}).get("message") or str(body)[:200]
        except (ValueError, AttributeError):
            detail = resp.text[:200]
        if resp.status_code == 401:
            raise GitHubError(f"{self.name} rejected the saved credential (expired or revoked). "
                              "Save it again under Profile → Integrations.", 401)
        if resp.status_code in (403, 404):
            raise GitHubError(f"The saved {self.name} credential cannot do this on that repository. "
                              f"It needs write access to the repository ({detail}).", resp.status_code)
        raise GitHubError(f"{self.name} answered {resp.status_code}: {detail}", resp.status_code)


class GitLabClient(_ForgeClient):
    """Merge requests on gitlab.com with a personal, project or group access token."""

    name = "GitLab"

    def __init__(self, token: str, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(httpx.Client(base_url=GITLAB_API, timeout=20, transport=transport, follow_redirects=False,
                                      headers={"PRIVATE-TOKEN": token, "User-Agent": "TestSphere-AI"}))

    def open_fix_pr(self, path: str, base_sha: str, files: list[tuple[str, str]],
                    branch: str, title: str, body: str) -> dict[str, Any]:
        project = f"/projects/{quote(path, safe='')}"
        info = self._call("GET", project)
        name = branch
        for attempt in range(1, 6):
            try:
                self._call("POST", f"{project}/repository/branches", json={"branch": name, "ref": base_sha})
                break
            except GitHubError as exc:
                if exc.status != 400 or attempt == 5:  # 400 = branch exists already
                    raise
                name = f"{branch}-{attempt + 1}"
        self._call("POST", f"{project}/repository/commits", json={
            "branch": name, "commit_message": title,
            "actions": [{"action": "update", "file_path": p, "content": c} for p, c in files],
        })
        mr = self._call("POST", f"{project}/merge_requests", json={
            "source_branch": name, "target_branch": info["default_branch"], "title": title, "description": body,
            "remove_source_branch": True,
        })
        return {"url": mr["web_url"], "number": mr["iid"], "branch": name, "base": info["default_branch"]}


class BitbucketClient(_ForgeClient):
    """Pull requests on bitbucket.org with an access token or an app password."""

    name = "Bitbucket"

    def __init__(self, username: str, token: str, transport: httpx.BaseTransport | None = None) -> None:
        # An access token goes as a bearer token (saved with the x-token-auth user);
        # an app password with the account's user name
        auth = None if username == "x-token-auth" else httpx.BasicAuth(username, token)
        headers = {"User-Agent": "TestSphere-AI"} | ({"Authorization": f"Bearer {token}"} if auth is None else {})
        super().__init__(httpx.Client(base_url=BITBUCKET_API, timeout=20, transport=transport,
                                      follow_redirects=False, auth=auth, headers=headers))

    def open_fix_pr(self, path: str, base_sha: str, files: list[tuple[str, str]],
                    branch: str, title: str, body: str) -> dict[str, Any]:
        repo = f"/repositories/{path}"
        info = self._call("GET", repo)
        base = (info.get("mainbranch") or {}).get("name") or "main"
        name = branch
        for attempt in range(1, 6):
            existing = self._call("GET", f"{repo}/refs/branches", params={"q": f'name="{name}"'})
            if not (existing or {}).get("values"):
                break
            name = f"{branch}-{attempt + 1}"
        # One form post commits every file on a new branch whose parent is the base commit;
        # "/path" keeps a file named like a form field (message, branch) a file
        self._call("POST", f"{repo}/src", data={"message": title, "branch": name, "parents": base_sha,
                                                **{f"/{p}": c for p, c in files}})
        pr = self._call("POST", f"{repo}/pullrequests", json={
            "title": title, "description": body, "close_source_branch": True,
            "source": {"branch": {"name": name}}, "destination": {"branch": {"name": base}},
        })
        return {"url": pr["links"]["html"]["href"], "number": pr["id"], "branch": name, "base": base}


# Run result -> each host's commit status state
_GITLAB_STATES = {"success": "success", "failure": "failed", "error": "failed", "pending": "running"}
_BITBUCKET_STATES = {"success": "SUCCESSFUL", "failure": "FAILED", "error": "FAILED", "pending": "INPROGRESS"}


def set_gitlab_status(client: GitLabClient, path: str, sha: str, state: str, description: str,
                      target_url: str | None) -> None:
    """TestSphere's result on a pushed commit, shown next to it in GitLab."""
    payload = {"state": _GITLAB_STATES[state], "name": "TestSphere", "description": description[:140]}
    if target_url:
        payload["target_url"] = target_url
    client._call("POST", f"/projects/{quote(path, safe='')}/statuses/{sha}", json=payload)


def set_bitbucket_status(client: BitbucketClient, path: str, sha: str, state: str, description: str,
                         target_url: str | None) -> None:
    """The same on Bitbucket (which needs a link: none without DASHBOARD_URL)."""
    if not target_url:
        return
    client._call("POST", f"/repositories/{path}/commit/{sha}/statuses/build", json={
        "key": "testsphere", "name": "TestSphere", "state": _BITBUCKET_STATES[state],
        "description": description[:140], "url": target_url,
    })
