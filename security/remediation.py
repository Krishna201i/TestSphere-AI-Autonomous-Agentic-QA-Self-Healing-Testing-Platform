"""
security/remediation.py
=======================
Fix proposals for passive-scan findings (module 5.5, first slice).

For header-level findings the proposal is a real diff: the left side is the
response headers the target actually sent, the right side is the same block
with the fix applied.  Each proposal also carries ready-to-paste config for
common servers.  Findings that need a code or infrastructure change (plain
HTTP, mixed content, password forms) get a manual proposal with guidance only.

Nothing here touches the target: a human approves the proposal, applies it,
and the scanner's ``retest`` confirms the fix.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .findings import Finding

# Redact header values that may carry secrets before they leave the backend
_REDACT = {"set-cookie", "authorization", "cookie"}

# check_id -> (header to set, value).  None value = remove the header.
_HEADER_FIXES: dict[str, tuple[str, str | None]] = {
    "SEC-HDR-CSP": ("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'"),
    "SEC-HDR-FRAME": ("X-Frame-Options", "DENY"),
    "SEC-HDR-XCTO": ("X-Content-Type-Options", "nosniff"),
    "SEC-HDR-REFERRER": ("Referrer-Policy", "strict-origin-when-cross-origin"),
    "SEC-HDR-HSTS": ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
    "SEC-CORS": ("Access-Control-Allow-Origin", "https://your-trusted-origin.example"),
}


class DiffLine(BaseModel):
    kind: str = Field(..., description="'context', 'removed' or 'added'")
    text: str


class RemediationProposal(BaseModel):
    finding_key: str
    kind: str = Field(..., description="'header' (diff + config) or 'manual' (guidance only)")
    summary: str
    diff: list[DiffLine] = Field(default_factory=list)
    snippets: dict[str, str] = Field(default_factory=dict, description="server name -> config to apply")


def redact_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(k, "…redacted…" if k.lower() in _REDACT else v) for k, v in headers]


def propose(finding: Finding, response_headers: list[tuple[str, str]]) -> RemediationProposal:
    """Build a fix proposal for *finding* given the target's observed headers."""
    headers = redact_headers(response_headers)

    if finding.check_id in _HEADER_FIXES:
        name, value = _HEADER_FIXES[finding.check_id]
        return _header_proposal(finding, headers, set_headers={name: value})
    if finding.check_id == "SEC-DISCLOSURE":
        leaking = {k for k, v in headers if k.lower() in ("server", "x-powered-by", "x-aspnet-version")}
        return _header_proposal(finding, headers, remove=leaking)
    if finding.check_id == "SEC-COOKIE-FLAGS":
        return _cookie_proposal(finding, headers)
    return RemediationProposal(
        finding_key=finding.key,
        kind="manual",
        summary=finding.recommendation or "Requires a code or infrastructure change.",
    )


def _header_proposal(
    finding: Finding,
    headers: list[tuple[str, str]],
    set_headers: dict[str, str] | None = None,
    remove: set[str] | None = None,
) -> RemediationProposal:
    set_headers = set_headers or {}
    remove_lower = {h.lower() for h in (remove or set())}
    replace_lower = {h.lower() for h in set_headers}

    diff: list[DiffLine] = []
    for k, v in headers:
        line = f"{k}: {v}"
        if k.lower() in remove_lower or k.lower() in replace_lower:
            diff.append(DiffLine(kind="removed", text=line))
        else:
            diff.append(DiffLine(kind="context", text=line))
    diff += [DiffLine(kind="added", text=f"{k}: {v}") for k, v in set_headers.items()]

    return RemediationProposal(
        finding_key=finding.key,
        kind="header",
        summary=finding.recommendation,
        diff=diff,
        snippets=_snippets(set_headers, remove_lower),
    )


def _cookie_proposal(finding: Finding, headers: list[tuple[str, str]]) -> RemediationProposal:
    name = finding.component.rsplit("(cookie: ", 1)[-1].rstrip(")")
    secure = "; Secure" if finding.component.startswith("https://") else ""
    fixed = f"{name}=…; Path=/; HttpOnly{secure}; SameSite=Lax"
    diff = [
        DiffLine(kind="removed" if k.lower() == "set-cookie" else "context", text=f"{k}: {v}")
        for k, v in headers
    ]
    diff.append(DiffLine(kind="added", text=f"Set-Cookie: {fixed}"))
    return RemediationProposal(
        finding_key=finding.key,
        kind="header",
        summary=finding.recommendation,
        diff=diff,
        snippets={
            "FastAPI / Starlette": (
                f'response.set_cookie("{name}", value, httponly=True, '
                f'secure={bool(secure)}, samesite="lax")'
            ),
            "Express": f'res.cookie("{name}", value, {{ httpOnly: true, secure: {str(bool(secure)).lower()}, sameSite: "lax" }})',
        },
    )


def _snippets(set_headers: dict[str, str], remove_lower: set[str]) -> dict[str, str]:
    fastapi = ["@app.middleware(\"http\")", "async def security_headers(request, call_next):",
               "    response = await call_next(request)"]
    fastapi += [f'    response.headers["{k}"] = "{v}"' for k, v in set_headers.items()]
    fastapi += [f'    response.headers.pop("{k}", None)' for k in sorted(remove_lower)]
    fastapi.append("    return response")

    nginx = [f"add_header {k} \"{v}\" always;" for k, v in set_headers.items()]
    if "server" in remove_lower:
        nginx.append("server_tokens off;")
    nginx += [f"proxy_hide_header {k};" for k in sorted(remove_lower - {'server'})]

    return {"FastAPI / Starlette": "\n".join(fastapi), "nginx": "\n".join(nginx)}
