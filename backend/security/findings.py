"""
security/findings.py
====================
The unified ``Finding`` record shared by QA and security results.

Fields follow Appendix B of the synopsis: severity, component, evidence,
root cause, confidence and retest result, plus what is needed to deduplicate
and track a finding through the remediate → retest loop.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field, computed_field, model_validator


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        """Lower = more severe; use as a sort key."""
        return list(Severity).index(self)


class FindingSource(str, Enum):
    SECURITY = "security"
    QA = "qa"


class FindingStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class RetestResult(str, Enum):
    PASS = "pass"  # issue no longer reproduces
    FAIL = "fail"  # issue still present


class Tier(str, Enum):
    """How much a finding proves, which decides how a report counts it.

    - ``proven``: the scan showed the harm itself (a script ran, a database error
      came back, a secret file downloaded).  Only these count in verdicts,
      severity totals and CI gates.
    - ``unconfirmed``: a real signal the scan could not prove; check it by hand.
    - ``hardening``: a missing defence (a header, a cookie flag, TLS) with no
      harm shown.  Worth fixing; never reported as a vulnerability.
    """

    PROVEN = "proven"
    UNCONFIRMED = "unconfirmed"
    HARDENING = "hardening"


# What each check demonstrates when it fires
_PROVEN_CHECKS = frozenset({
    "SEC-SQLI-ERROR", "SEC-OPEN-REDIRECT", "SEC-EXPOSED-GIT", "SEC-EXPOSED-ENV", "SEC-ERROR-DISCLOSURE",
    "SEC-DIR-LISTING", "SEC-CORS", "SEC-FORM-PASSWORD",
})
_UNCONFIRMED_CHECKS = frozenset({"SEC-CSRF"})


def tier_of(check_id: str, confidence: float = 1.0, source: str = "security") -> Tier:
    """The tier of a finding (also for stored ones written before tiers existed)."""
    if source == FindingSource.QA.value:
        return Tier.PROVEN  # a failing test is the harm itself
    if check_id == "SEC-XSS-REFLECTED":  # proven only once the script ran in a browser
        return Tier.PROVEN if confidence >= 1.0 else Tier.UNCONFIRMED
    if check_id in _PROVEN_CHECKS:
        return Tier.PROVEN
    if check_id in _UNCONFIRMED_CHECKS:
        return Tier.UNCONFIRMED
    return Tier.HARDENING


# Who can do it, answered once per check (Shannon-style question 2: what did it take?)
PREREQUISITES = {
    "SEC-XSS-REFLECTED": "None to send the link; a victim has to open it.",
    "SEC-SQLI-ERROR": "None: the request needs no account.",
    "SEC-OPEN-REDIRECT": "None to craft the link; a victim has to open it.",
    "SEC-EXPOSED-GIT": "None: anyone on the internet can download it.",
    "SEC-EXPOSED-ENV": "None: anyone on the internet can download it.",
    "SEC-ERROR-DISCLOSURE": "None: any visitor sees the error page.",
    "SEC-DIR-LISTING": "None: any visitor can browse the listing.",
    "SEC-CORS": "A signed-in victim has to visit the attacker's site.",
    "SEC-FORM-PASSWORD": "Someone on the same network as the user (public Wi-Fi, a proxy).",
    "SEC-CSRF": "A signed-in victim has to visit the attacker's site.",
}

# Why this severity, in the terms of what was shown (question 1 and 3: what is gained, how far it reaches)
SEVERITY_RATIONALE = {
    "SEC-XSS-REFLECTED": "Script runs in the victim's session on this site: it can read what the user sees and act "
                         "as them. Needs the victim to open a link, so High rather than Critical.",
    "SEC-SQLI-ERROR": "The input reaches a SQL query unescaped, with no account needed. Data extraction was not "
                      "attempted; rated Critical because the database is what the app exists to protect.",
    "SEC-OPEN-REDIRECT": "The site's own link can send users to any other site (phishing). No data is read or "
                         "changed on this site, so Medium.",
    "SEC-EXPOSED-GIT": "The source code and its history can be downloaded, including anything ever committed.",
    "SEC-EXPOSED-ENV": "The settings file with its secrets can be downloaded by anyone, without an account.",
    "SEC-ERROR-DISCLOSURE": "Visitors see internal details (stack trace, framework, paths) that help plan attacks; "
                            "nothing is read or changed by it alone.",
    "SEC-DIR-LISTING": "Visitors can list files that were not meant to be linked; impact depends on what is there.",
    "SEC-CORS": "Another site can read this site's responses with the user's cookies: the user's data on this site "
                "leaks to any page they visit.",
    "SEC-FORM-PASSWORD": "The password crosses the network unencrypted and can be read on the way.",
    "SEC-CSRF": "If the form changes data, another site could submit it as the signed-in user. Not demonstrated.",
}
HARDENING_RATIONALE = ("A missing defence, not a demonstrated attack: nothing was read or changed. "
                       "Fix it as hardening; it is not counted as a vulnerability.")


def code_location(url: str, routes: list[dict] | None) -> str:
    """The ``file:line`` of the codebase route that serves *url* (``/users/<id>``,
    ``/users/{id}`` and ``/users/:id`` match ``/users/42``), or "" if none does."""
    import re
    from urllib.parse import urlsplit

    path = (urlsplit(url).path or "/").rstrip("/") or "/"
    for route in routes or []:
        pattern = str(route.get("path", "")).rstrip("/") or "/"
        regex = re.sub(r"<[^>]+>|\\\{[^}]+\\\}|:\w+", "[^/]+", re.escape(pattern).replace(r"\:", ":"))
        if re.fullmatch(regex, path) and route.get("file"):
            return f"{route['file']}:{route.get('line') or 1}"
    return ""


def curl_command(method: str, url: str, params: dict[str, str] | None = None, *, body: bool = False,
                 headers_only: bool = False) -> str:
    """A copyable curl command for one request (single-quoted for a POSIX shell)."""
    from urllib.parse import urlencode

    def quote(text: str) -> str:
        return "'" + text.replace("'", "'\\''") + "'"

    parts = ["curl", "-s"]
    if headers_only:
        parts += ["-D", "-", "-o", "/dev/null"]
    if method.upper() == "POST" or body:
        parts += ["-X", "POST", "--data", quote(urlencode(params or {}))]
        parts.append(quote(url))
    else:
        query = urlencode(params or {})
        parts.append(quote(url + (("&" if "?" in url else "?") + query if query else "")))
    return " ".join(parts)


class Finding(BaseModel):
    """One validated issue, from either the QA or the security side."""

    check_id: str = Field(..., description="Stable id of the check that produced it, e.g. SEC-HDR-CSP")
    source: FindingSource
    title: str
    severity: Severity
    component: str = Field(..., description="Where it lives: URL, URL + cookie name, locator, …")
    target_url: str = Field("", description="What was scanned/tested to find it; retests re-run against this")
    evidence: list[str] = Field(default_factory=list, description="Observed facts backing the finding")
    root_cause: str = ""
    recommendation: str = ""
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    status: FindingStatus = FindingStatus.OPEN
    retest_result: RetestResult | None = None
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # How to see it for yourself, and why it is rated as it is (filled per check;
    # empty on findings stored before these fields existed)
    location: dict[str, str] = Field(default_factory=dict,
                                     description="method, url and parameter of the request that shows it")
    prerequisites: str = ""
    steps: list[str] = Field(default_factory=list, description="Numbered reproduction steps, in order")
    request: str = Field("", description="A copyable command that reproduces it")
    response_excerpt: str = Field("", description="The part of the response that shows it")
    severity_rationale: str = ""
    code_location: str = Field("", description="file:line from the ingested codebase, when matched")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tier(self) -> Tier:
        return tier_of(self.check_id, self.confidence, self.source.value)

    @model_validator(mode="after")
    def _explain(self) -> Finding:
        """Fill the per-check prerequisites and severity rationale a scanner did not set."""
        if not self.prerequisites and self.check_id in PREREQUISITES:
            self.prerequisites = PREREQUISITES[self.check_id]
        if not self.severity_rationale:
            self.severity_rationale = (SEVERITY_RATIONALE.get(self.check_id, "")
                                       if self.tier != Tier.HARDENING else HARDENING_RATIONALE)
        return self

    @property
    def key(self) -> str:
        """Deduplication key: same check on the same component = same finding."""
        return hashlib.sha1(f"{self.check_id}|{self.component}".encode(), usedforsecurity=False).hexdigest()[:16]  # nosemgrep: insecure-hash-algorithm-sha1 - stored dedup key; changing it would orphan existing findings


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Drop repeat findings (by ``key``), keeping the first, sorted most severe first."""
    unique: dict[str, Finding] = {}
    for f in findings:
        unique.setdefault(f.key, f)
    return sorted(unique.values(), key=lambda f: (f.severity.rank, f.check_id, f.component))
