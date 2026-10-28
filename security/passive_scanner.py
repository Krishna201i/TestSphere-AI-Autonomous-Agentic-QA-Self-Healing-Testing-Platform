"""
security/passive_scanner.py
===========================
Passive security scanner — the first, safe slice of the Attacker Agent (5.3).

"Passive" means it only does what a normal browser visit does: one GET per
page (following redirects), plus an ``Origin`` header to observe the CORS
policy.  No payloads, no fuzzing, no form submission.  Every request, including
each redirect hop, is checked against the ``ScopePolicy`` first.

Usage::

    scanner = PassiveScanner(ScopePolicy.of("127.0.0.1"))
    findings = await scanner.scan("http://127.0.0.1:8000/")
    later = await scanner.retest(findings[0])   # after a fix: PASS / FAIL

Checks (``check_id``):

    SEC-HDR-CSP          missing Content-Security-Policy
    SEC-HDR-FRAME        no X-Frame-Options / frame-ancestors (clickjacking)
    SEC-HDR-XCTO         missing X-Content-Type-Options: nosniff
    SEC-HDR-REFERRER     missing Referrer-Policy
    SEC-HDR-HSTS         HTTPS page without Strict-Transport-Security
    SEC-DISCLOSURE       Server / X-Powered-By reveal software versions
    SEC-CORS             reflected origin, or wildcard with credentials
    SEC-CORS-WILDCARD    wildcard origin without credentials (info, never patched)
    SEC-COOKIE-FLAGS     cookie missing HttpOnly / Secure / SameSite
    SEC-TRANSPORT-HTTP   non-loopback page served over plain HTTP
    SEC-FORM-PASSWORD    password field sent over plain HTTP
    SEC-MIXED-CONTENT    HTTPS page loading http:// resources
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from .findings import (
    Finding,
    FindingSource,
    FindingStatus,
    RetestResult,
    Severity,
    dedupe,
)
from .scope import ScopePolicy, is_loopback

log = logging.getLogger(__name__)

USER_AGENT = "TestSphere-PassiveScanner/0.1"
# Unroutable origin (.invalid is reserved) used to see whether CORS reflects it
PROBE_ORIGIN = "https://scope-probe.invalid"


class ScanError(RuntimeError):
    """The target could not be fetched (network error, too many redirects, …)."""


# ---------------------------------------------------------------------------
# Fetched page
# ---------------------------------------------------------------------------


@dataclass
class PageSnapshot:
    requested_url: str
    url: str  # final URL after redirects
    status: int
    headers: httpx.Headers
    html: str

    @property
    def is_https(self) -> bool:
        return self.url.startswith("https://")


class _PageParser(HTMLParser):
    """Collects what the HTML checks need: forms, password inputs, resources."""

    _RESOURCE_ATTRS = {"script": "src", "img": "src", "iframe": "src", "link": "href"}

    def __init__(self) -> None:
        super().__init__()
        self.form_actions: list[str] = []
        self.has_password = False
        self.resources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "form":
            self.form_actions.append(a.get("action", ""))
        elif tag == "input" and a.get("type", "").lower() == "password":
            self.has_password = True
        attr = self._RESOURCE_ATTRS.get(tag)
        if attr and a.get(attr):
            if tag != "link" or "stylesheet" in a.get("rel", "").lower():
                self.resources.append(a[attr])


# ---------------------------------------------------------------------------
# Checks — each takes a snapshot and returns zero or more findings
# ---------------------------------------------------------------------------


def _finding(snap: PageSnapshot, check_id: str, **kwargs) -> Finding:
    kwargs.setdefault("component", snap.url)
    return Finding(check_id=check_id, source=FindingSource.SECURITY, target_url=snap.requested_url, **kwargs)


def check_csp(snap: PageSnapshot) -> list[Finding]:
    if "content-security-policy" in snap.headers:
        return []
    evidence = ["Content-Security-Policy header absent"]
    if "content-security-policy-report-only" in snap.headers:
        evidence.append("Only a Report-Only policy is set, which enforces nothing")
    return [_finding(
        snap, "SEC-HDR-CSP",
        title="Missing Content-Security-Policy",
        severity=Severity.MEDIUM,
        evidence=evidence,
        root_cause="The server does not restrict where scripts, styles and frames may load from.",
        recommendation="Send a Content-Security-Policy, starting from default-src 'self'.",
    )]


def check_framing(snap: PageSnapshot) -> list[Finding]:
    csp = snap.headers.get("content-security-policy", "")
    if "x-frame-options" in snap.headers or "frame-ancestors" in csp.lower():
        return []
    return [_finding(
        snap, "SEC-HDR-FRAME",
        title="Page can be framed by any site (clickjacking)",
        severity=Severity.MEDIUM,
        evidence=["No X-Frame-Options header", "No CSP frame-ancestors directive"],
        root_cause="Nothing tells the browser to refuse rendering this page inside another site's frame.",
        recommendation="Send X-Frame-Options: DENY or CSP frame-ancestors 'none'.",
    )]


def check_content_type_options(snap: PageSnapshot) -> list[Finding]:
    value = snap.headers.get("x-content-type-options", "")
    if value.strip().lower() == "nosniff":
        return []
    return [_finding(
        snap, "SEC-HDR-XCTO",
        title="Missing X-Content-Type-Options: nosniff",
        severity=Severity.LOW,
        evidence=[f"X-Content-Type-Options: {value!r}" if value else "Header absent"],
        root_cause="Browsers may MIME-sniff responses and execute content as a different type.",
        recommendation="Send X-Content-Type-Options: nosniff.",
    )]


def check_referrer_policy(snap: PageSnapshot) -> list[Finding]:
    if "referrer-policy" in snap.headers:
        return []
    return [_finding(
        snap, "SEC-HDR-REFERRER",
        title="Missing Referrer-Policy",
        severity=Severity.LOW,
        evidence=["Referrer-Policy header absent"],
        root_cause="Full URLs (possibly with tokens in query strings) may leak to third parties.",
        recommendation="Send Referrer-Policy: strict-origin-when-cross-origin (or stricter).",
    )]


def check_hsts(snap: PageSnapshot) -> list[Finding]:
    if not snap.is_https:
        return []
    value = snap.headers.get("strict-transport-security", "")
    match = re.search(r"max-age=(\d+)", value)
    if match and int(match.group(1)) > 0:
        return []
    return [_finding(
        snap, "SEC-HDR-HSTS",
        title="HTTPS page without HTTP Strict Transport Security",
        severity=Severity.MEDIUM,
        evidence=[f"Strict-Transport-Security: {value!r}" if value else "Header absent"],
        root_cause="Browsers may still try plain HTTP first, allowing SSL-stripping attacks.",
        recommendation="Send Strict-Transport-Security: max-age=31536000; includeSubDomains.",
    )]


def check_disclosure(snap: PageSnapshot) -> list[Finding]:
    leaks = [
        f"{name}: {snap.headers[name]}"
        for name in ("server", "x-powered-by", "x-aspnet-version")
        if name in snap.headers and re.search(r"\d", snap.headers[name])
    ]
    if not leaks:
        return []
    return [_finding(
        snap, "SEC-DISCLOSURE",
        title="Server software version disclosed",
        severity=Severity.LOW,
        evidence=leaks,
        root_cause="Response headers advertise exact software versions, easing targeted exploits.",
        recommendation="Strip version numbers from Server / X-Powered-By headers.",
    )]


def check_cors(snap: PageSnapshot) -> list[Finding]:
    origin = snap.headers.get("access-control-allow-origin", "")
    credentials = snap.headers.get("access-control-allow-credentials", "").lower() == "true"
    if origin == PROBE_ORIGIN:
        return [_finding(
            snap, "SEC-CORS",
            title="CORS reflects arbitrary origins" + (" with credentials" if credentials else ""),
            severity=Severity.HIGH if credentials else Severity.MEDIUM,
            confidence=0.9,
            evidence=[
                f"Request Origin: {PROBE_ORIGIN}",
                f"Access-Control-Allow-Origin: {origin}",
                f"Access-Control-Allow-Credentials: {str(credentials).lower()}",
            ],
            root_cause="The server echoes the caller's Origin instead of checking it against an allowlist.",
            recommendation="Only return Access-Control-Allow-Origin for an explicit list of trusted origins.",
        )]
    if origin == "*" and credentials:
        return [_finding(
            snap, "SEC-CORS",
            title="CORS wildcard origin combined with credentials",
            severity=Severity.HIGH,
            evidence=["Access-Control-Allow-Origin: *", "Access-Control-Allow-Credentials: true"],
            root_cause="Any site is allowed to read responses, and the server asks for credentials too.",
            recommendation="Replace * with an explicit origin allowlist.",
        )]
    if origin == "*":
        # Fine for public data; a risk only where access depends on where the
        # request comes from (an intranet, an IP allowlist).  Informational,
        # and never auto-patched: narrowing it would break a public API.
        return [_finding(
            snap, "SEC-CORS-WILDCARD",
            title="Any website can read this page's responses (CORS *)",
            severity=Severity.INFO,
            confidence=0.5,
            evidence=["Access-Control-Allow-Origin: *"],
            root_cause="The server allows every origin to read its responses (without cookies).",
            recommendation="Keep * only for public data. If this page is limited by network or IP "
                           "(intranet, VPN, allowlist), return Access-Control-Allow-Origin only for trusted origins.",
        )]
    return []


def _parse_cookie(raw: str) -> tuple[str, set[str]]:
    parts = [p.strip() for p in raw.split(";")]
    name = parts[0].split("=", 1)[0].strip()
    flags = {p.split("=", 1)[0].strip().lower() for p in parts[1:] if p}
    return name, flags


def check_cookies(snap: PageSnapshot) -> list[Finding]:
    findings = []
    for raw in snap.headers.get_list("set-cookie"):
        name, flags = _parse_cookie(raw)
        missing = []
        if "httponly" not in flags:
            missing.append("HttpOnly")
        if snap.is_https and "secure" not in flags:
            missing.append("Secure")
        if "samesite" not in flags:
            missing.append("SameSite")
        if not missing:
            continue
        findings.append(_finding(
            snap, "SEC-COOKIE-FLAGS",
            component=f"{snap.url} (cookie: {name})",
            title=f"Cookie '{name}' missing {', '.join(missing)}",
            severity=Severity.MEDIUM if {"HttpOnly", "Secure"} & set(missing) else Severity.LOW,
            # value redacted: session tokens must never end up in a report
            evidence=[f"Set-Cookie: {name}=…; {'; '.join(sorted(flags)) or '(no attributes)'}"],
            root_cause="The cookie is readable by scripts and/or sent in contexts where it should not be.",
            recommendation=f"Set {', '.join(missing)} on the '{name}' cookie.",
        ))
    return findings


def check_transport(snap: PageSnapshot) -> list[Finding]:
    if snap.is_https or is_loopback(snap.url):
        return []
    return [_finding(
        snap, "SEC-TRANSPORT-HTTP",
        title="Page served over plain HTTP",
        severity=Severity.HIGH,
        evidence=[f"Final URL: {snap.url}"],
        root_cause="Traffic is unencrypted and can be read or modified in transit.",
        recommendation="Serve the site over HTTPS and redirect HTTP to it.",
    )]


def check_password_forms(snap: PageSnapshot, page: _PageParser) -> list[Finding]:
    if not page.has_password:
        return []
    insecure_actions = [a for a in page.form_actions if a.startswith("http://")]
    page_insecure = not snap.is_https and not is_loopback(snap.url)
    if not (page_insecure or insecure_actions):
        return []
    evidence = ["Page contains an <input type=\"password\">"]
    if page_insecure:
        evidence.append(f"Page itself is served over HTTP: {snap.url}")
    evidence += [f"Form posts to {a}" for a in insecure_actions]
    return [_finding(
        snap, "SEC-FORM-PASSWORD",
        title="Password submitted over an unencrypted connection",
        severity=Severity.HIGH,
        evidence=evidence,
        root_cause="Credentials entered on this page travel over plain HTTP.",
        recommendation="Serve the page and its form action over HTTPS only.",
    )]


def check_mixed_content(snap: PageSnapshot, page: _PageParser) -> list[Finding]:
    if not snap.is_https:
        return []
    insecure = sorted({r for r in page.resources if r.startswith("http://")})
    if not insecure:
        return []
    return [_finding(
        snap, "SEC-MIXED-CONTENT",
        title="HTTPS page loads resources over HTTP",
        severity=Severity.MEDIUM,
        evidence=insecure[:10],
        root_cause="Resources fetched over HTTP can be tampered with, undermining the HTTPS page.",
        recommendation="Load every script, stylesheet, image and frame over HTTPS.",
    )]


HEADER_CHECKS: list[Callable[[PageSnapshot], list[Finding]]] = [
    check_csp, check_framing, check_content_type_options, check_referrer_policy,
    check_hsts, check_disclosure, check_cors, check_cookies, check_transport,
]
HTML_CHECKS: list[Callable[[PageSnapshot, _PageParser], list[Finding]]] = [
    check_password_forms, check_mixed_content,
]


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class PassiveScanner:
    """Scope-checked passive scanner.

    Parameters
    ----------
    scope:
        Hosts the scanner may contact.  Defaults to loopback only.
    timeout:
        Per-request timeout in seconds.
    max_redirects:
        Redirect hops to follow (each one scope-checked).
    transport:
        Optional ``httpx`` transport, used by tests to stub the network.
    """

    def __init__(
        self,
        scope: ScopePolicy | None = None,
        *,
        timeout: float = 10.0,
        max_redirects: int = 5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.scope = scope or ScopePolicy()
        self._timeout = timeout
        self._max_redirects = max_redirects
        self._transport = transport

    async def fetch(self, url: str) -> PageSnapshot:
        """GET *url*, following redirects manually so every hop is scope-checked."""
        self.scope.check(url)
        headers = {"User-Agent": USER_AGENT, "Origin": PROBE_ORIGIN}
        current = url

        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=False, transport=self._transport
        ) as http:
            for _ in range(self._max_redirects + 1):
                try:
                    response = await http.get(current, headers=headers)
                except httpx.RequestError as exc:
                    raise ScanError(f"Could not fetch {current}: {type(exc).__name__}") from exc

                location = response.headers.get("location")
                if response.is_redirect and location:
                    current = urljoin(current, location)
                    self.scope.check(current)  # never follow a redirect out of scope
                    continue

                content_type = response.headers.get("content-type", "")
                html = response.text if "html" in content_type else ""
                return PageSnapshot(url, str(response.url), response.status_code, response.headers, html)

        raise ScanError(f"Too many redirects (>{self._max_redirects}) starting at {url}")

    def analyze(self, snap: PageSnapshot) -> list[Finding]:
        """Run every check against an already-fetched page."""
        findings = [f for check in HEADER_CHECKS for f in check(snap)]
        if snap.html:
            page = _PageParser()
            page.feed(snap.html)
            findings += [f for check in HTML_CHECKS for f in check(snap, page)]
        return dedupe(findings)

    async def scan(self, url: str) -> list[Finding]:
        """Fetch *url* and return its findings, most severe first."""
        snap = await self.fetch(url)
        findings = self.analyze(snap)
        log.info("Passive scan of %s: %d findings", url, len(findings))
        return findings

    async def retest(self, finding: Finding) -> Finding:
        """Re-scan the finding's target and report whether it still reproduces."""
        current = {f.key for f in await self.scan(finding.target_url or finding.component)}
        still_there = finding.key in current
        return finding.model_copy(update={
            "retest_result": RetestResult.FAIL if still_there else RetestResult.PASS,
            "status": FindingStatus.OPEN if still_there else FindingStatus.RESOLVED,
        })
