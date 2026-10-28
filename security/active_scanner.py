"""
security/active_scanner.py
==========================
Active security scanner — the opt-in half of the Attacker Agent (5.3).

Unlike the passive scanner, this one sends crafted inputs to the target to
see how it behaves: reflected XSS, error-based SQL injection, and open
redirects.  It is a DAST scanner (what OWASP ZAP or Burp's scanner do), run
against applications you own.

Three rules keep it safe and authorized, all enforced in code:

* **Scope.** Every request, including every redirect hop and every form
  action, is checked against the ``ScopePolicy`` first (loopback plus the
  server's ``SECURITY_SCAN_ALLOWED_HOSTS``).  Nothing off the allowlist is
  ever contacted.
* **Non-destructive.** Payloads only *read* or *reflect*: a marker string, a
  single quote to provoke a database error, a redirect to an unroutable
  probe host.  No payload changes data, chains statements, runs commands,
  deletes, or carries a real external address.
* **Bounded.** One request at a time, a per-request timeout and a hard
  ``max_requests`` budget, so a scan cannot turn into a flood.

    scanner = ActiveScanner(ScopePolicy.of("127.0.0.1:8000"))
    findings = await scanner.scan("http://127.0.0.1:8000/search?q=hi")

Checks (``check_id``):

    SEC-XSS-REFLECTED     a parameter's value is reflected into HTML unescaped
    SEC-SQLI-ERROR        a parameter makes the app emit a database error
    SEC-OPEN-REDIRECT     a parameter controls the Location of a redirect
"""

from __future__ import annotations

import html
import logging
import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import httpx

from .findings import Finding, FindingSource, FindingStatus, RetestResult, Severity
from .scope import OutOfScopeError, ScopePolicy

log = logging.getLogger(__name__)

USER_AGENT = "TestSphere-ActiveScanner/0.1"
# Unroutable (.invalid is reserved): an open redirect that sends us here is real
REDIRECT_PROBE = "https://open-redirect.invalid/ts"
# Parameter names that commonly take a redirect destination
_REDIRECT_PARAMS = re.compile(r"(?:^|_)(?:next|url|redirect|return|dest|goto|continue|target|to|back)(?:_?url)?$", re.I)

# Database error signatures (error-based SQL injection); a single quote that
# reaches a query unescaped produces one of these
_SQL_ERRORS = [
    (re.compile(r"you have an error in your sql syntax", re.I), "MySQL"),
    (re.compile(r"warning:\s+mysqli?_", re.I), "MySQL"),
    (re.compile(r"unclosed quotation mark after the character string", re.I), "SQL Server"),
    (re.compile(r"quoted string not properly terminated", re.I), "Oracle"),
    (re.compile(r"\bORA-\d{5}\b"), "Oracle"),
    (re.compile(r"\bPG::\w*(?:Syntax|Error)", re.I), "PostgreSQL"),
    (re.compile(r"psycopg2\.\w+error", re.I), "PostgreSQL"),
    (re.compile(r"\bPSQLException\b"), "PostgreSQL"),
    (re.compile(r"syntax error at or near", re.I), "PostgreSQL"),
    (re.compile(r"sqlite3?\.\w*(?:Operational|Programming)Error", re.I), "SQLite"),
    (re.compile(r"\bSQLITE_ERROR\b|unrecognized token", re.I), "SQLite"),
    (re.compile(r"\bSQLSTATE\[", re.I), "SQL"),
    (re.compile(r"org\.hibernate\.exception", re.I), "JDBC/Hibernate"),
]


class ActiveScanError(RuntimeError):
    """A scan could not complete (not a finding about the target)."""


@dataclass
class _Form:
    method: str
    action: str
    fields: dict[str, str]  # name -> default value


class _FormParser(HTMLParser):
    """Collects forms with their method, action and named fields."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_Form] = []
        self._cur: _Form | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "form":
            self._cur = _Form(method=(a.get("method") or "get").lower(), action=a.get("action", ""), fields={})
        elif tag in ("input", "textarea", "select") and self._cur is not None:
            name = a.get("name")
            if name and a.get("type", "").lower() not in ("submit", "button", "image", "reset", "file"):
                self._cur.fields[name] = a.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._cur is not None:
            self.forms.append(self._cur)
            self._cur = None


@dataclass
class _Point:
    """One injectable request: a base request plus the one field being probed."""

    method: str
    url: str                     # for GET: no query of its own; params carry it
    params: dict[str, str]       # query (GET) or form body (POST)
    field: str                   # the field this point injects into
    is_body: bool                # params go in the body (POST) vs the query (GET)
    source_url: str              # the URL a retest re-scans to rediscover this point


def _points_from_url(url: str) -> list[_Point]:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    base = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    # Retest re-scans the full URL, so its query parameters are rediscovered
    return [_Point("GET", base, dict(query), name, False, url) for name in query]


def _points_from_form(page_url: str, form: _Form) -> list[_Point]:
    action = urljoin(page_url, form.action or "")
    method = "POST" if form.method == "post" else "GET"
    seed = {k: (v or "ts") for k, v in form.fields.items()}
    if method == "GET":  # the action's own query merges with the form fields
        parts = urlsplit(action)
        seed = dict(parse_qsl(parts.query, keep_blank_values=True)) | seed
        action = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    # Retest re-scans the page the form is on, so the form is rediscovered
    return [_Point(method, action, dict(seed), name, method == "POST", page_url) for name in form.fields]


class ActiveScanner:
    """Scope-checked active (DAST) scanner; see the module docstring."""

    def __init__(
        self,
        scope: ScopePolicy | None = None,
        *,
        timeout: float = 10.0,
        max_requests: int = 300,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.scope = scope or ScopePolicy()
        self._timeout = timeout
        self._max_requests = max_requests
        self._transport = transport
        self._sent = 0

    async def scan(self, url: str) -> list[Finding]:
        """Discover injectable points on *url* and probe each one."""
        self.scope.check(url)
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False,
                                     transport=self._transport, headers={"User-Agent": USER_AGENT}) as http:
            try:
                page = await http.get(url)
            except httpx.RequestError as exc:
                raise ActiveScanError(f"Could not fetch {url}: {type(exc).__name__}") from exc
            points = list(self._points(url, page))
            findings: list[Finding] = []
            for point in points:
                if self._sent >= self._max_requests:
                    log.warning("Active scan of %s hit the %d-request budget", url, self._max_requests)
                    break
                findings += await self._probe(http, point)
            # One check per (check_id, component); keep the most confident
            best: dict[str, Finding] = {}
            for f in findings:
                if f.key not in best or f.confidence > best[f.key].confidence:
                    best[f.key] = f
            return sorted(best.values(), key=lambda f: (f.severity.rank, -f.confidence))

    def _points(self, url: str, page: httpx.Response) -> Iterable[_Point]:
        yield from _points_from_url(url)
        if "html" in page.headers.get("content-type", ""):
            parser = _FormParser()
            parser.feed(page.text)
            for form in parser.forms:
                for point in _points_from_form(url, form):
                    if self.scope.allows(point.url):  # never submit a form that posts off-scope
                        yield point

    async def _request(self, http: httpx.AsyncClient, point: _Point, value: str) -> httpx.Response | None:
        """Send *point* with its field set to *value*; None if out of scope or unreachable."""
        params = dict(point.params)
        params[point.field] = value
        if point.is_body:
            target, data, query = point.url, params, None
        else:
            target, data, query = point.url, None, params
        try:
            self.scope.check(point.url)
        except OutOfScopeError:
            return None
        if self._sent >= self._max_requests:
            return None
        self._sent += 1
        try:
            return await http.request(point.method, target, params=query, data=data)
        except httpx.RequestError:
            return None

    async def _probe(self, http: httpx.AsyncClient, point: _Point) -> list[Finding]:
        findings: list[Finding] = []
        where = "body" if point.is_body else "query"
        component = f"{point.url} ({where} param {point.field!r})"

        # ── Reflected XSS: a marker with HTML-significant characters that comes
        #    back unescaped means the value lands in HTML without encoding
        token = secrets.token_hex(4)
        marker = f"ts{token}<img/src=x>"
        resp = await self._request(http, point, marker)
        if resp is not None and "html" in resp.headers.get("content-type", "") and marker in resp.text:
            # Reflected *and* unescaped (the escaped form would not contain '<img')
            if html.escape(marker) not in resp.text or resp.text.count(marker) > resp.text.count(html.escape(marker)):
                findings.append(Finding(
                    check_id="SEC-XSS-REFLECTED", source=FindingSource.SECURITY,
                    title="Reflected cross-site scripting (XSS)", severity=Severity.HIGH, confidence=0.9,
                    component=component, target_url=point.source_url,
                    evidence=[f"The {where} parameter {point.field!r} was reflected into the HTML response "
                              f"without escaping (sent {marker!r}, found it verbatim in the page)."],
                    root_cause="User input is written into the HTML page without output encoding.",
                    recommendation="HTML-escape all user input before rendering it, or use a templating engine that "
                                   "auto-escapes. Add a Content-Security-Policy as defence in depth.",
                ))

        # ── Error-based SQL injection: a single quote that reaches a query
        #    unescaped produces a database error only the quote triggers
        quoted = await self._request(http, point, f"ts{token}'")
        safe = await self._request(http, point, f"ts{token}")
        if quoted is not None and safe is not None:
            for pattern, engine in _SQL_ERRORS:
                if pattern.search(quoted.text) and not pattern.search(safe.text):
                    findings.append(Finding(
                        check_id="SEC-SQLI-ERROR", source=FindingSource.SECURITY,
                        title="SQL injection (database error exposed)", severity=Severity.CRITICAL, confidence=0.9,
                        component=component, target_url=point.source_url,
                        evidence=[f"A single quote in the {where} parameter {point.field!r} produced a {engine} "
                                  "error that a quote-free value did not."],
                        root_cause="User input is concatenated into a SQL query instead of being passed as a parameter.",
                        recommendation="Use parameterised queries (bind variables) for every value, and stop the app "
                                       "returning raw database errors to clients.",
                    ))
                    break

        # ── Open redirect: a destination parameter that sends the browser to an
        #    external, unroutable probe host
        if _REDIRECT_PARAMS.search(point.field):
            resp = await self._request(http, point, REDIRECT_PROBE)
            location = resp.headers.get("location", "") if resp is not None and resp.is_redirect else ""
            if location and (urlsplit(location).hostname or "") == "open-redirect.invalid":
                findings.append(Finding(
                    check_id="SEC-OPEN-REDIRECT", source=FindingSource.SECURITY,
                    title="Open redirect", severity=Severity.MEDIUM, confidence=0.9,
                    component=component, target_url=point.source_url,
                    evidence=[f"The {where} parameter {point.field!r} set the redirect Location to the external "
                              f"host {location!r}."],
                    root_cause="A redirect destination comes straight from user input without an allowlist.",
                    recommendation="Redirect only to a fixed allowlist of paths or hosts; never to a raw user value.",
                ))
        return findings


    async def retest(self, finding: Finding) -> Finding:
        """Re-probe the finding's target and report whether it still reproduces."""
        self._sent = 0
        current = {f.key for f in await self.scan(finding.target_url or finding.component)}
        still_there = finding.key in current
        return finding.model_copy(update={
            "retest_result": RetestResult.FAIL if still_there else RetestResult.PASS,
            "status": FindingStatus.OPEN if still_there else FindingStatus.RESOLVED,
        })


ACTIVE_CHECK_IDS = frozenset({"SEC-XSS-REFLECTED", "SEC-SQLI-ERROR", "SEC-OPEN-REDIRECT"})
