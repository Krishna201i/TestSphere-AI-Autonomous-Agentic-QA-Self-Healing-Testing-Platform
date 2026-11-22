"""
ingestion/vulns.py
==================
Known vulnerabilities in a repository's dependencies, from OSV.dev.

Only exact versions can be checked, so they are read from what pins them:
``package-lock.json`` (npm), ``requirements*.txt`` lines with ``==``,
``poetry.lock`` / ``uv.lock`` / ``Pipfile.lock`` (PyPI) and ``go.mod`` (Go).
Each package is sent to the OSV batch API (name, ecosystem, version; never
code), and every advisory found is described with its CVE ids, severity and
the first version that fixes it.

Network failures never fail an ingestion: the result says what went wrong.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

OSV_API = "https://api.osv.dev/v1"
MAX_PACKAGES = 3000
MAX_DETAILS = 250  # advisories described in full; the rest are listed by id

_SEVERITY = {"CRITICAL": "critical", "HIGH": "high", "MODERATE": "medium", "MEDIUM": "medium", "LOW": "low"}


def pinned_packages(root: Path) -> list[dict[str, str]]:
    """``[{"ecosystem", "name", "version", "file"}]`` for every exactly pinned dependency."""
    found: dict[tuple[str, str, str], str] = {}

    def add(eco: str, name: str, version: str, file: Path) -> None:
        version = version.strip().lstrip("v=") if eco != "Go" else version.strip()
        if name and version and re.match(r"^v?\d", version):
            found.setdefault((eco, name.strip(), version), str(file.relative_to(root)).replace("\\", "/"))

    for lock in _files(root, "package-lock.json"):
        data = _json(lock)
        for path, info in (data.get("packages") or {}).items():  # lockfile v2/v3
            if path and isinstance(info, dict) and info.get("version"):
                add("npm", info.get("name") or path.rsplit("node_modules/", 1)[-1], info["version"], lock)
        for name, info in (data.get("dependencies") or {}).items():  # lockfile v1
            if isinstance(info, dict) and info.get("version"):
                add("npm", name, info["version"], lock)

    for req in _files(root, "requirements*.txt"):
        for line in _text(req).splitlines():
            m = re.match(r"^\s*([A-Za-z0-9][\w.-]*)(?:\[[^\]]*\])?\s*==\s*([\w.+!-]+)", line)
            if m:
                add("PyPI", m.group(1).lower(), m.group(2), req)

    for lock in [*_files(root, "poetry.lock"), *_files(root, "uv.lock")]:
        try:
            data = tomllib.loads(_text(lock))
        except tomllib.TOMLDecodeError:
            continue
        for pkg in data.get("package", []):
            if pkg.get("name") and pkg.get("version"):
                add("PyPI", str(pkg["name"]).lower(), str(pkg["version"]), lock)

    for lock in _files(root, "Pipfile.lock"):
        data = _json(lock)
        for section in ("default", "develop"):
            for name, info in (data.get(section) or {}).items():
                version = (info or {}).get("version", "") if isinstance(info, dict) else ""
                if version.startswith("=="):
                    add("PyPI", name.lower(), version[2:], lock)

    for mod in _files(root, "go.mod"):
        for m in re.finditer(r"^\s*(?:require\s+)?([\w./-]+\.[\w./-]+)\s+(v[\w.+-]+)", _text(mod), re.M):
            add("Go", m.group(1), m.group(2), mod)

    return [{"ecosystem": e, "name": n, "version": v, "file": f}
            for (e, n, v), f in sorted(found.items())][:MAX_PACKAGES]


def _files(root: Path, pattern: str) -> Iterable[Path]:
    """*pattern* at the root and one level down, never inside dependency folders."""
    for path in [*root.glob(pattern), *root.glob(f"*/{pattern}")]:
        if path.is_file() and not ({"node_modules", ".venv", "venv", "vendor"} & set(path.parts)):
            yield path


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(_text(path))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def check_dependencies(packages: list[dict[str, str]], *, transport: httpx.BaseTransport | None = None,
                       timeout: float = 20.0) -> dict[str, Any]:
    """Known advisories for *packages*.

    Returns ``{"checked", "vulnerable", "advisories": [...], "error"}``; each
    advisory names the package, version, id, CVE aliases, severity, summary,
    the fixed version (when one exists) and a link.
    """
    result: dict[str, Any] = {"checked": len(packages), "vulnerable": 0, "advisories": [], "error": None}
    if not packages:
        return result
    try:
        with httpx.Client(base_url=OSV_API, timeout=timeout, transport=transport) as client:
            hits: list[tuple[dict[str, str], str]] = []
            for start in range(0, len(packages), 1000):
                batch = packages[start:start + 1000]
                resp = client.post("/querybatch", json={"queries": [
                    {"package": {"name": p["name"], "ecosystem": p["ecosystem"]}, "version": p["version"]} for p in batch]})
                resp.raise_for_status()
                for pkg, res in zip(batch, resp.json().get("results", []), strict=False):
                    hits += [(pkg, v["id"]) for v in (res or {}).get("vulns", []) if v.get("id")]
            ids = list(dict.fromkeys(vid for _, vid in hits))[:MAX_DETAILS]

            def detail(vid: str) -> dict[str, Any]:
                r = client.get(f"/vulns/{vid}")
                return r.json() if r.status_code == 200 else {}

            with ThreadPoolExecutor(max_workers=10) as pool:
                details = dict(zip(ids, pool.map(detail, ids), strict=True))
    except (httpx.HTTPError, ValueError) as exc:
        result["error"] = f"Could not check dependencies against OSV.dev: {exc}"
        return result

    for pkg, vid in hits:
        result["advisories"].append(_describe(pkg, vid, details.get(vid) or {}))
    result["vulnerable"] = len({(a["ecosystem"], a["package"], a["version"]) for a in result["advisories"]})
    order = ["critical", "high", "medium", "low", "unknown"]
    result["advisories"].sort(key=lambda a: (order.index(a["severity"]), a["package"], a["id"]))
    return result


def _describe(pkg: dict[str, str], vid: str, vuln: dict[str, Any]) -> dict[str, Any]:
    aliases = [a for a in vuln.get("aliases", []) if a.startswith("CVE-")]
    severity = _SEVERITY.get(str((vuln.get("database_specific") or {}).get("severity", "")).upper(), "unknown")
    fixes = [e["fixed"] for affected in vuln.get("affected", [])
             if (affected.get("package") or {}).get("name", "").lower() == pkg["name"].lower()
             for rng in affected.get("ranges", []) for e in rng.get("events", []) if "fixed" in e]
    # The first fix above the installed version (an advisory can list fixes for several release lines)
    newer = sorted((f for f in fixes if _version_key(f) > _version_key(pkg["version"])), key=_version_key)
    fixed = newer[0] if newer else None
    return {
        "id": vid, "cves": aliases, "ecosystem": pkg["ecosystem"], "package": pkg["name"], "version": pkg["version"],
        "file": pkg["file"], "severity": severity, "summary": (vuln.get("summary") or vuln.get("details") or "")[:300],
        "fixed_in": fixed, "url": f"https://osv.dev/vulnerability/{vid}",
    }


def _version_key(version: str) -> tuple[int, ...]:
    """Loose ordering for versions of any ecosystem: the numbers in it, in order."""
    return tuple(int(n) for n in re.findall(r"\d+", version.split("+")[0])[:4])


def as_findings(scan: dict[str, Any], repo: str) -> list[dict[str, Any]]:
    """Advisories as security findings (one per package and advisory), keyed like scanner findings."""
    from security.findings import Finding, FindingSource, Severity

    out = []
    for a in scan.get("advisories", []):
        sev = a["severity"] if a["severity"] != "unknown" else "medium"
        upgrade = f"Upgrade {a['package']} to {a['fixed_in']} or later." if a["fixed_in"] else \
            f"No fixed version of {a['package']} is published yet; see the advisory for workarounds."
        f = Finding(
            check_id=f"SEC-DEP-{a['id']}", source=FindingSource.SECURITY,
            title=f"{a['package']} {a['version']}: {', '.join(a['cves']) or a['id']}",
            severity=Severity(sev), component=f"{a['ecosystem']}:{a['package']}@{a['version']} ({a['file']})",
            target_url=repo, evidence=[a["summary"] or a["id"], a["url"]], root_cause="Known vulnerable dependency version",
            recommendation=upgrade,
        )
        out.append(f.model_dump(mode="json") | {"key": f.key, "remediation": {
            "finding_key": f.key, "kind": "dependency", "summary": upgrade, "diff": [], "snippets": {}}})
    return out
