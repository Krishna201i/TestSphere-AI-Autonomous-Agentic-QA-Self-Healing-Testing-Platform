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
    SEC-CSP-WEAK         a CSP whose scripts may still be inline, from anywhere or over HTTP
    SEC-COOKIE-SAMESITE-NONE  cookie sent cross-site (SameSite=None) without Secure
    SEC-ERROR-DISCLOSURE stack trace or framework debug page shown to visitors
    SEC-DIR-LISTING      web server lists a directory's files
    SEC-CSRF             state-changing form without an anti-CSRF token (medium confidence)
    SEC-EXPOSED-GIT      /.git/ downloadable (source code and history)
    SEC-EXPOSED-ENV      /.env downloadable (secrets)

The two SEC-EXPOSED checks are the only extra requests (two GETs at the site's
root, on a scan of the app URL); every check needs more than one signal before
it reports, so an app answering every path with its index page is not flagged.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from .findings import (
    Finding,
    FindingSource,
    FindingStatus,
    RetestResult,
    Severity,
    curl_command,
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
    # Found by the requests a scan of the app URL adds (exposed /.git, /.env)
    exposures: list[Finding] = field(default_factory=list)

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
        # (method, action, field names) of each form
        self.forms: list[tuple[str, str, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "form":
            self.form_actions.append(a.get("action", ""))
            self.forms.append(((a.get("method") or "get").lower(), a.get("action", ""), []))
        elif tag in ("input", "textarea", "select", "button") and self.forms and a.get("name"):
            self.forms[-1][2].append(a["name"])
        if tag == "input" and a.get("type", "").lower() == "password":
            self.has_password = True
        if tag == "meta" and a.get("name", "").lower() in ("csrf-token", "csrf-param", "_csrf"):
            self.forms.append(("meta", "", [a["name"]]))  # a page-wide token (Rails, Laravel)
        attr = self._RESOURCE_ATTRS.get(tag)
        if attr and a.get(attr):
            if tag != "link" or "stylesheet" in a.get("rel", "").lower():
                self.resources.append(a[attr])


# ---------------------------------------------------------------------------
# Checks — each takes a snapshot and returns zero or more findings
# ---------------------------------------------------------------------------


# Response headers worth showing next to a header finding (what is there, and what is not)
_SHOWN_HEADERS = ("content-security-policy", "strict-transport-security", "x-frame-options", "x-content-type-options",
                  "referrer-policy", "server", "x-powered-by", "access-control-allow-origin",
                  "access-control-allow-credentials", "set-cookie", "location")


def _headers_excerpt(snap: PageSnapshot) -> str:
    """The status and the security-relevant headers of the response, cookie values hidden."""
    lines = [f"HTTP {snap.status}"]
    for name in _SHOWN_HEADERS:
        for value in snap.headers.get_list(name):
            if name == "set-cookie":  # the cookie's name and flags, never its value
                cookie, _, flags = value.partition(";")
                value = f"{cookie.split('=', 1)[0]}=…;{flags}" if flags else f"{cookie.split('=', 1)[0]}=…"
            lines.append(f"{name}: {value[:160]}")
    return "\n".join(lines)


def _finding(snap: PageSnapshot, check_id: str, **kwargs) -> Finding:
    kwargs.setdefault("component", snap.url)
    # Reproduce it: the request a browser makes, and the headers that show it
    url = kwargs["component"] if str(kwargs["component"]).startswith("http") else snap.url
    request = curl_command("GET", url.split(" ")[0], headers_only=True)
    kwargs.setdefault("location", {"method": "GET", "url": url.split(" ")[0], "parameter": ""})
    kwargs.setdefault("request", request)
    kwargs.setdefault("steps", [f"Request the page and look at its response headers: {request}",
                                "Compare them with the evidence above."])
    kwargs.setdefault("response_excerpt", _headers_excerpt(snap))
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


# ── Checks that need more than one signal ──────────────────────────────────


def _csp_directive(csp: str, name: str) -> str | None:
    for part in csp.split(";"):
        bits = part.strip().split(None, 1)
        if bits and bits[0].lower() == name:
            return bits[1] if len(bits) > 1 else ""
    return None


def check_csp_strength(snap: PageSnapshot) -> list[Finding]:
    csp = snap.headers.get("content-security-policy", "")
    if not csp:
        return []  # absent: SEC-HDR-CSP says so
    scripts = _csp_directive(csp, "script-src")
    if scripts is None:
        scripts = _csp_directive(csp, "default-src")
    if scripts is None:
        return [_finding(snap, "SEC-CSP-WEAK", title="Content-Security-Policy does not restrict scripts",
                         severity=Severity.MEDIUM, evidence=[f"Content-Security-Policy: {csp[:200]}",
                                                             "No script-src or default-src directive"],
                         root_cause="Scripts may load from anywhere, so the policy does not stop injected scripts.",
                         recommendation="Add script-src 'self' (plus nonces or hashes for inline scripts).")]
    sources = scripts.lower().split()
    nonce_or_hash = any(t.startswith(("'nonce-", "'sha256-", "'sha384-", "'sha512-")) for t in sources)
    weak = []
    if "'unsafe-inline'" in sources and not nonce_or_hash:  # with a nonce/hash, browsers ignore it
        weak.append("'unsafe-inline' (inline scripts run, so injected ones do too)")
    if "*" in sources:
        weak.append("* (scripts from any host)")
    weak += [f"{t} (scripts over plain HTTP)" for t in sources if t in ("http:", "http://*")]
    if "data:" in sources:
        weak.append("data: (scripts from data: URLs)")
    if not weak:
        return []
    return [_finding(snap, "SEC-CSP-WEAK", title="Content-Security-Policy allows injected scripts to run",
                     severity=Severity.MEDIUM, evidence=[f"script sources: {scripts[:200]}", *weak],
                     root_cause="The policy is present but permits the script sources an attacker would use.",
                     recommendation="Remove 'unsafe-inline', *, http: and data: from script-src; use nonces or hashes.")]


def check_samesite_none(snap: PageSnapshot) -> list[Finding]:
    findings = []
    for raw in snap.headers.get_list("set-cookie"):
        name, flags = _parse_cookie(raw)
        samesite = re.search(r";\s*samesite\s*=\s*(\w+)", raw, re.IGNORECASE)
        if samesite and samesite.group(1).lower() == "none" and "secure" not in flags:
            findings.append(_finding(
                snap, "SEC-COOKIE-SAMESITE-NONE", component=f"{snap.url} (cookie: {name})",
                title=f"Cookie '{name}' is sent cross-site without Secure",
                severity=Severity.MEDIUM,
                evidence=[f"Set-Cookie: {name}=…; SameSite=None without Secure"],
                root_cause="SameSite=None cookies go with requests from other sites; without Secure they also "
                           "travel over plain HTTP (current browsers reject such cookies outright).",
                recommendation=f"Add Secure to the '{name}' cookie, or use SameSite=Lax if it need not be cross-site."))
    return findings


# Signatures of stack traces and framework debug pages: each one is specific
# enough that ordinary page text does not contain it
_ERROR_SIGNATURES = [
    ("Python traceback", re.compile(r"Traceback \(most recent call last\):")),
    ("Django debug page", re.compile(r"You(?:&#x27;|&#39;|')re seeing this error because you have\s+<code>DEBUG = True")),
    ("Werkzeug debugger", re.compile(r"Werkzeug Debugger|The debugger caught an exception in your WSGI application")),
    ("Java stack trace", re.compile(r"(?:Exception|Error)(?::[^\n<]*)?\s+at [\w$.]+\([\w$]+\.java:\d+\)")),
    (".NET stack trace", re.compile(r"\[\w+(?:\.\w+)*Exception: .*?\]\s*(?:<[^>]+>\s*)*\s*\w+(?:\.\w+)+\(", re.DOTALL)),
    ("PHP error", re.compile(r"<b>(?:Fatal error|Parse error|Warning)</b>:\s.+? in <b>/[^<]+\.php</b> on line <b>\d+</b>")),
    ("Node.js stack trace", re.compile(r"(?:Error|TypeError|ReferenceError): [^\n<]+\n\s+at .+? \((?:/|[A-Z]:\\\\).+?:\d+:\d+\)")),
    ("Rails exception page", re.compile(r"Action Controller: Exception caught")),
]


def check_error_disclosure(snap: PageSnapshot) -> list[Finding]:
    found = [label for label, pattern in _ERROR_SIGNATURES if pattern.search(snap.html)]
    if not found:
        return []
    return [_finding(snap, "SEC-ERROR-DISCLOSURE", title="Error details shown to visitors",
                     severity=Severity.MEDIUM, evidence=[f"The page shows a {label}" for label in found],
                     root_cause="Errors are rendered with internals (code paths, versions, sometimes settings).",
                     recommendation="Turn off debug mode in production and show a generic error page; log the details.")]


def check_directory_listing(snap: PageSnapshot) -> list[Finding]:
    title = re.search(r"<title>\s*Index of /", snap.html, re.IGNORECASE)
    body = re.search(r"<h1>\s*Index of /|>\s*Parent Directory\s*<", snap.html, re.IGNORECASE)
    if not (title and body):
        return []
    return [_finding(snap, "SEC-DIR-LISTING", title="Directory listing is enabled", severity=Severity.MEDIUM,
                     evidence=["The page is a server-generated 'Index of /' listing"],
                     root_cause="The web server lists files of a directory without an index page.",
                     recommendation="Turn off directory listing (nginx autoindex off; Apache Options -Indexes).")]


_TOKEN_FIELD = re.compile(r"csrf|xsrf|_token|authenticity|nonce|requestverification|__requestverif", re.IGNORECASE)


def check_csrf(snap: PageSnapshot, page: _PageParser) -> list[Finding]:
    if any(method == "meta" for method, _, _ in page.forms):
        return []  # a page-wide token the app's scripts send
    unprotected = [(action, fields) for method, action, fields in page.forms
                   if method == "post" and not any(_TOKEN_FIELD.search(f) for f in fields)]
    if not unprotected:
        return []
    cookies = " ".join(snap.headers.get_list("set-cookie")).lower()
    if re.search(r"samesite\s*=\s*(?:lax|strict)", cookies):
        return []  # its cookies are not sent with another site's form post
    return [_finding(snap, "SEC-CSRF", title="Form without an anti-CSRF token", severity=Severity.MEDIUM,
                     confidence=0.5,
                     evidence=[f"POST form to {action or '(this page)'} has no token field "
                               f"(fields: {', '.join(fields[:8]) or 'none'})" for action, fields in unprotected[:5]]
                     + ["No cookie on this page sets SameSite=Lax or Strict (browsers default to Lax, "
                        "so check the session cookie before acting on this)"],
                     root_cause="Another site could make a signed-in visitor's browser submit this form.",
                     recommendation="Add a per-session anti-CSRF token to the form (most frameworks have one), "
                                    "and set SameSite=Lax on the session cookie.")]


def _env_finding(snap: PageSnapshot, url: str, body: str) -> Finding | None:
    names = re.findall(r"(?m)^\s*(?:export\s+)?([A-Z][A-Z0-9_]{1,63})\s*=", body)
    secret = [n for n in names if re.search(r"PASS|SECRET|KEY|TOKEN|DATABASE_URL|DSN|PRIVATE", n)]
    if len(names) < 2 or not secret:
        return None
    request = curl_command("GET", url)
    return _finding(snap, "SEC-EXPOSED-ENV", component=url, title="Environment file (.env) is downloadable",
                    severity=Severity.CRITICAL, request=request,
                    steps=[f"Download it: {request}", f"It lists {len(names)} settings, including "
                           f"{', '.join(secret[:5])} (TestSphere does not record the values)."],
                    response_excerpt="\n".join(f"{n}=…" for n in names[:8]),
                    evidence=[f"{url} returns {len(names)} settings, including {', '.join(secret[:5])} "
                              "(values not recorded)"],
                    root_cause="The project's .env file is served as a static file.",
                    recommendation="Block dotfiles in the web server, move .env out of the web root, "
                                   "and rotate every secret it holds.")


def _git_finding(snap: PageSnapshot, url: str, body: str) -> Finding | None:
    if not re.match(r"\s*(?:ref: refs/[\w./-]+|[0-9a-f]{40})\s*$", body):
        return None
    request = curl_command("GET", url)
    return _finding(snap, "SEC-EXPOSED-GIT", component=url, title="Git repository (.git) is downloadable",
                    request=request, response_excerpt=body.strip()[:80],
                    steps=[f"Download the repository's HEAD: {request}",
                           "It answers with a Git reference: the rest of .git (objects, history) is reachable too."],
                    severity=Severity.HIGH, evidence=[f"{url} returns a Git HEAD: {body.strip()[:60]}"],
                    root_cause="The .git folder is served, so the source code and its history can be downloaded.",
                    recommendation="Block /.git in the web server and deploy without the .git folder.")


EXPOSURE_PROBES = [("/.git/HEAD", _git_finding), ("/.env", _env_finding)]
EXPOSURE_CHECK_IDS = frozenset({"SEC-EXPOSED-GIT", "SEC-EXPOSED-ENV"})


HEADER_CHECKS: list[Callable[[PageSnapshot], list[Finding]]] = [
    check_csp, check_framing, check_content_type_options, check_referrer_policy,
    check_hsts, check_disclosure, check_cors, check_cookies, check_transport,
    check_csp_strength, check_samesite_none,
]
HTML_CHECKS: list[Callable[[PageSnapshot, _PageParser], list[Finding]]] = [
    check_password_forms, check_mixed_content, check_csrf,
]
# HTML-text checks (no parsing needed)
TEXT_CHECKS: list[Callable[[PageSnapshot], list[Finding]]] = [check_error_disclosure, check_directory_listing]


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

    async def fetch(self, url: str, *, probe_files: bool = False) -> PageSnapshot:
        """GET *url*, following redirects manually so every hop is scope-checked.
        With *probe_files*, also look for an exposed /.git and /.env at the
        site's root (two more GETs; done for the app URL, not every page)."""
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
                snap = PageSnapshot(url, str(response.url), response.status_code, response.headers, html)
                if probe_files:
                    snap.exposures = await self._probe_files(http, snap)
                return snap

        raise ScanError(f"Too many redirects (>{self._max_redirects}) starting at {url}")

    async def _probe_files(self, http: httpx.AsyncClient, snap: PageSnapshot) -> list[Finding]:
        """Findings for files that must never be served (no redirects followed)."""
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(snap.url)
        found = []
        for path, judge in EXPOSURE_PROBES:
            url = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
            try:
                self.scope.check(url)
                response = await http.get(url, headers={"User-Agent": USER_AGENT})
            except Exception as exc:  # noqa: BLE001 - out of scope, refused or unreachable: no finding
                log.debug("Exposure probe %s skipped: %s", url, exc)
                continue
            if response.status_code != 200 or "html" in response.headers.get("content-type", ""):
                continue  # an app answering every path with its index page serves HTML
            if finding := judge(snap, url, response.text[:20_000]):
                found.append(finding)
        return found

    def analyze(self, snap: PageSnapshot) -> list[Finding]:
        """Run every check against an already-fetched page."""
        findings = [f for check in HEADER_CHECKS for f in check(snap)]
        if snap.html:
            page = _PageParser()
            page.feed(snap.html)
            findings += [f for check in HTML_CHECKS for f in check(snap, page)]
            findings += [f for check in TEXT_CHECKS for f in check(snap)]
        findings += snap.exposures
        return dedupe(findings)

    async def scan(self, url: str) -> list[Finding]:
        """Fetch *url* (and probe for exposed files) and return its findings, most severe first."""
        snap = await self.fetch(url, probe_files=True)
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
