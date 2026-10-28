"""
security/patcher.py
===================
Turn passive-scan findings into a real patch against the app's own source.

Given a checkout of the repository and the open findings for its live site,
``build_patch`` finds where the app is configured and edits those files:

* FastAPI / Starlette — an ``@app.middleware("http")`` that sets the missing
  headers, ``allow_origins`` of ``CORSMiddleware`` narrowed to the site's own
  origin, cookie flags on ``set_cookie(...)``, ``server_header=False`` on
  ``uvicorn.run(...)``.
* Flask — an ``@app.after_request`` hook, cookie flags.
* Django — the matching ``SECURE_*`` / ``X_FRAME_OPTIONS`` / cookie / CORS
  settings in ``settings.py``.
* Express — ``app.disable("x-powered-by")``, a header middleware right after
  ``express()``, ``cors()`` narrowed to the site's origin, cookie options.
* Next.js — ``async headers()`` for every path and ``poweredByHeader: false``
  in ``next.config.*`` (left to a manual change when it already has headers()).
* nginx — ``add_header ... always;`` and ``server_tokens off;`` in the first
  ``server { }`` block (used when no app code is found).

The result is a unified diff (``git apply``-able), the list of fixes applied
and where, the findings that still need a manual change and why, and whether
each edited file still parses.  Nothing is written to the checkout.
"""

from __future__ import annotations

import ast
import difflib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .remediation import _HEADER_FIXES

FUNC_NAME = "testsphere_security_headers"
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "env", "site-packages", "dist", "build", "__pycache__",
             "tests", "test", ".tox", "migrations", "vendor", ".next", "coverage"}
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 5000
LEAKY_HEADERS = ("Server", "X-Powered-By", "X-AspNet-Version")


@dataclass
class Fix:
    """What the findings ask for, independent of framework."""

    set_headers: dict[str, str] = field(default_factory=dict)       # header -> value
    remove_headers: set[str] = field(default_factory=set)
    cors: bool = False
    cookies: set[str] = field(default_factory=set)                  # cookie names ("*" = any)
    sources: dict[str, str] = field(default_factory=dict)           # header / topic -> check_id


@dataclass
class Applied:
    check_id: str
    file: str
    how: str


@dataclass
class Manual:
    check_id: str
    reason: str


@dataclass
class FileChange:
    path: str
    diff: str
    verified: bool | None  # None = no checker for this file type
    check_note: str | None = None
    content: str | None = None  # the whole patched file (for a pull request)


@dataclass
class PatchResult:
    frameworks: list[str]
    files: list[FileChange]
    applied: list[Applied]
    manual: list[Manual]

    @property
    def patch(self) -> str:
        return "".join(f.diff for f in self.files)


def fixes_for(findings: list[dict]) -> tuple[Fix, list[Manual]]:
    """Group findings into one Fix; the ones no patch can address go to manual."""
    fix, manual = Fix(), []
    for f in findings:
        cid = f["check_id"]
        if cid == "SEC-CORS":
            fix.cors = True
            fix.sources["cors"] = cid
        elif cid in _HEADER_FIXES:
            name, value = _HEADER_FIXES[cid]
            fix.set_headers[name] = value
            fix.sources[name] = cid
        elif cid == "SEC-DISCLOSURE":
            evidence = " ".join(f.get("evidence") or []).lower()
            leaking = {h for h in LEAKY_HEADERS if h.lower() in evidence} or {"Server", "X-Powered-By"}
            fix.remove_headers |= leaking
            for h in leaking:
                fix.sources[h] = cid
        elif cid == "SEC-COOKIE-FLAGS":
            component = f.get("component") or ""
            name = component.rsplit("(cookie: ", 1)[-1].rstrip(")") if "(cookie: " in component else "*"
            fix.cookies.add(name)
            fix.sources["cookie"] = cid
        else:
            manual.append(Manual(cid, f.get("recommendation") or "Needs a change no config patch can make."))
    return fix, manual


# ── Repository scan ────────────────────────────────────────────────────────

def _files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(suffixes) or (suffixes == (".conf",) and name == "nginx.conf"):
                p = Path(dirpath) / name
                try:
                    if p.stat().st_size <= MAX_FILE_BYTES:
                        out.append(p)
                except OSError:
                    continue
            if len(out) >= MAX_FILES:
                return out
    return out


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def _rank(path: Path, root: Path) -> tuple[int, int, str]:
    """Prefer shallow, conventionally named entry files."""
    rel = path.relative_to(root)
    preferred = {"main.py", "app.py", "server.py", "asgi.py", "wsgi.py", "app.js", "server.js", "index.js",
                 "main.js", "app.ts", "server.ts", "index.ts", "main.ts"}
    return (0 if path.name in preferred else 1, len(rel.parts), str(rel))


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _python_apps(root: Path) -> list[tuple[Path, str, str, int, str]]:
    """(file, framework, app variable, line of the assignment's end, its indentation)
    for each app object: module-level ``app = FastAPI()`` or one built inside a
    factory such as Flask's ``create_app()`` or ``get_application()``."""
    found = []
    for path in _files(root, (".py",)):
        try:
            tree = ast.parse(_read(path))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                target, value = node.target, node.value
            else:
                continue
            kind = _call_name(value) if isinstance(value, ast.Call) else ""
            if kind in ("FastAPI", "Starlette", "Flask"):
                found.append((path, kind.lower(), target.id, node.end_lineno, " " * node.col_offset))
    # Prefer module-level apps, then entry-like files
    return sorted(found, key=lambda f: (len(f[4]) > 0, *_rank(f[0], root)))


def _django_settings(root: Path) -> list[Path]:
    hits = [p for p in _files(root, (".py",)) if p.name == "settings.py" or p.parent.name == "settings"]
    hits = [p for p in hits if "INSTALLED_APPS" in _read(p) or "MIDDLEWARE" in _read(p)]
    return sorted(hits, key=lambda p: _rank(p, root))


# const app = express();  /  const app: Express = express();  /  let app: express.Application = express()
EXPRESS_RE = re.compile(r"^(?P<indent>[ \t]*)(?:const|let|var)\s+(?P<var>\w+)\s*(?::\s*[\w.<>]+\s*)?=\s*express\(\s*\)\s*;?[ \t]*$", re.M)


def _express_apps(root: Path) -> list[tuple[Path, re.Match]]:
    found = []
    for path in _files(root, (".js", ".mjs", ".cjs", ".ts")):
        m = EXPRESS_RE.search(_read(path))
        if m:
            found.append((path, m))
    return sorted(found, key=lambda f: _rank(f[0], root))


# The exported config object: const nextConfig = {, module.exports = {, export default {
_NEXT_CONFIG_OBJECT = re.compile(
    r"^(?P<indent>[ \t]*)(?:(?:const|let|var)\s+\w+\s*(?::\s*[\w.]+)?\s*=|module\.exports\s*=|export\s+default)\s*\{[ \t]*$",
    re.M)


def _next_configs(root: Path) -> list[Path]:
    return sorted((p for p in _files(root, (".js", ".mjs", ".cjs", ".ts"))
                   if re.fullmatch(r"next\.config\.[cm]?[jt]s", p.name)), key=lambda p: _rank(p, root))


def _patch_next(text: str, fix: Fix, ids: str) -> tuple[str, list[tuple[str, str]]]:
    m = _NEXT_CONFIG_OBJECT.search(text)
    if not m:
        return text, []
    inner = m.group("indent") + "  "
    done: list[tuple[str, str]] = []
    block: list[str] = []
    if "X-Powered-By" in fix.remove_headers and "poweredByHeader" not in text:
        block.append(f"{inner}poweredByHeader: false,")
        done.append(("X-Powered-By", "poweredByHeader: false"))
    if fix.set_headers and not re.search(r"\bheaders\s*[(:]", text):
        block += [f"{inner}async headers() {{",
                  f'{inner}  return [{{ source: "/(.*)", headers: [',
                  *[f'{inner}    {{ key: "{h}", value: "{_q(v)}" }},' for h, v in fix.set_headers.items()],
                  f"{inner}  ] }}];",
                  f"{inner}}},"]
        done += [(h, "next.config headers()") for h in fix.set_headers]
    if block:
        line_no = text[: m.end()].count("\n") + 1
        text = _insert_after_line(text, line_no, "\n".join([f"{inner}// Security headers from TestSphere fix proposals ({ids})", *block]))
    return text, done


def _nginx_confs(root: Path) -> list[Path]:
    return [p for p in _files(root, (".conf",)) if re.search(r"^\s*server\s*\{", _read(p), re.M)]


# ── Edits ──────────────────────────────────────────────────────────────────

def _insert_after_line(text: str, line_no: int, block: str) -> str:
    lines = text.split("\n")
    return "\n".join(lines[:line_no] + block.split("\n") + lines[line_no:])


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _patch_python_headers(text: str, framework: str, var: str, end_line: int,
                          fix: Fix, indent: str = "") -> tuple[str, list[str], list[str]]:
    """Add or extend the header hook.  Returns (text, headers set, headers removed)."""
    tree = ast.parse(text)
    already = text.lower()
    wanted = {h: v for h, v in fix.set_headers.items() if f'"{h.lower()}"' not in already and f"'{h.lower()}'" not in already}
    removing = sorted(h for h in fix.remove_headers if h != "Server")  # Server is added by the ASGI/WSGI server
    if framework == "flask":
        set_lines = [f'    response.headers["{h}"] = "{_q(v)}"' for h, v in wanted.items()]
        del_lines = [f'    response.headers.pop("{h}", None)' for h in removing]
    else:
        set_lines = [f'    response.headers["{h}"] = "{_q(v)}"' for h, v in wanted.items()]
        del_lines = [f'    if "{h}" in response.headers:\n        del response.headers["{h}"]' for h in removing]
    body = set_lines + del_lines
    if not body:
        return text, [], []

    existing = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
                     and n.name == FUNC_NAME), None)
    if existing:
        ret = next((n for n in existing.body if isinstance(n, ast.Return)), None)
        if ret is not None:
            lines = text.split("\n")
            pad = " " * max(ret.col_offset - 4, 0)  # the hook may be nested in a factory
            added = [pad + line for line in "\n".join(body).split("\n")]
            new = lines[: ret.lineno - 1] + added + lines[ret.lineno - 1:]
            return "\n".join(new), list(wanted), removing

    ids = ", ".join(sorted({fix.sources[h] for h in [*wanted, *removing] if h in fix.sources}))
    doc = f'    """Security headers from TestSphere fix proposals ({ids})."""'
    if framework == "flask":
        block = ["", "", f"@{var}.after_request", f"def {FUNC_NAME}(response):", doc, *body, "    return response"]
    else:
        block = ["", "", f'@{var}.middleware("http")', f"async def {FUNC_NAME}(request, call_next):", doc,
                 "    response = await call_next(request)", *body, "    return response"]
    if indent:  # inside a factory function: nest the hook, one blank line around it
        block = [""] + [indent + line if line else "" for line in block[2:]]
    lines = text.split("\n")
    if end_line < len(lines) and lines[end_line].strip():
        block += [""] if indent else ["", ""]  # blank lines before the code that follows
    return _insert_after_line(text, end_line, "\n".join(block)), list(wanted), removing


def _patch_python_cors(text: str, origin: str) -> str | None:
    """Narrow CORSMiddleware's allow_origins to *origin*; None when not found."""
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == "add_middleware" and node.args \
                and _call_name(node.args[0]) == "CORSMiddleware":
            kw = next((k for k in node.keywords if k.arg == "allow_origins"), None)
            if kw is None or any(k.arg == "allow_origin_regex" for k in node.keywords):
                return None
            return _replace_node(text, kw.value, f'["{_q(origin)}"]')
    return None


def _replace_node(text: str, node: ast.AST, replacement: str) -> str:
    lines = text.split("\n")
    start = sum(len(x) + 1 for x in lines[: node.lineno - 1]) + _col(lines[node.lineno - 1], node.col_offset)
    end = sum(len(x) + 1 for x in lines[: node.end_lineno - 1]) + _col(lines[node.end_lineno - 1], node.end_col_offset)
    return text[:start] + replacement + text[end:]


def _col(line: str, byte_offset: int) -> int:
    """ast offsets count UTF-8 bytes; convert to a str index."""
    return len(line.encode("utf-8")[:byte_offset].decode("utf-8", errors="ignore"))


def _patch_python_cookies(text: str, names: set[str], secure: bool) -> tuple[str, int]:
    """Add missing httponly / secure / samesite to set_cookie calls; returns (text, calls changed)."""
    count = 0
    while True:
        tree = ast.parse(text)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "set_cookie":
                first = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "key"), None)
                name = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
                if "*" not in names and name not in names:
                    continue
                have = {k.arg for k in node.keywords}
                missing = [f"{k}={v}" for k, v in (("httponly", "True"), ("secure", "True" if secure else None),
                                                    ("samesite", '"lax"')) if v and k not in have]
                if missing:
                    target = (node, missing)
                    break
        if target is None:
            return text, count
        node, missing = target
        lines = text.split("\n")
        end = sum(len(x) + 1 for x in lines[: node.end_lineno - 1]) + _col(lines[node.end_lineno - 1], node.end_col_offset) - 1
        before = text[:end].rstrip()
        sep = " " if before.endswith((",", "(")) else ", "
        text = before + sep + ", ".join(missing) + text[end:]
        count += 1


def _patch_uvicorn(text: str) -> str | None:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run" \
                and _call_name(node.func.value) == "uvicorn" and not any(k.arg == "server_header" for k in node.keywords):
            lines = text.split("\n")
            end = sum(len(x) + 1 for x in lines[: node.end_lineno - 1]) + _col(lines[node.end_lineno - 1], node.end_col_offset) - 1
            before = text[:end].rstrip()
            sep = " " if before.endswith((",", "(")) else ", "
            return before + sep + "server_header=False" + text[end:]
    return None


DJANGO_SETTINGS = {
    "X-Frame-Options": lambda v: [("X_FRAME_OPTIONS", f'"{v}"')],
    "X-Content-Type-Options": lambda v: [("SECURE_CONTENT_TYPE_NOSNIFF", "True")],
    "Referrer-Policy": lambda v: [("SECURE_REFERRER_POLICY", f'"{v}"')],
    "Strict-Transport-Security": lambda v: [("SECURE_HSTS_SECONDS", "31536000"), ("SECURE_HSTS_INCLUDE_SUBDOMAINS", "True")],
}


def _set_setting(text: str, name: str, value: str, added: list[str]) -> str:
    pattern = re.compile(rf"^{name}\s*=.*$", re.M)
    if pattern.search(text):
        return pattern.sub(f"{name} = {value}", text, count=1)
    added.append(f"{name} = {value}")
    return text


def _patch_django(text: str, fix: Fix, origin: str | None, secure: bool) -> tuple[str, list[tuple[str, str]]]:
    """Returns the new text and (topic, how) pairs."""
    added: list[str] = []
    done: list[tuple[str, str]] = []
    for header in list(fix.set_headers):
        if header in DJANGO_SETTINGS:
            for name, value in DJANGO_SETTINGS[header](fix.set_headers[header]):
                text = _set_setting(text, name, value, added)
            done.append((header, ", ".join(n for n, _ in DJANGO_SETTINGS[header](fix.set_headers[header]))))
    if fix.cors and origin and re.search(r"^CORS_(ALLOW_ALL_ORIGINS|ORIGIN_ALLOW_ALL)\s*=\s*True", text, re.M):
        text = re.sub(r"^(CORS_(?:ALLOW_ALL_ORIGINS|ORIGIN_ALLOW_ALL))\s*=\s*True.*$", r"\1 = False", text, flags=re.M)
        text = _set_setting(text, "CORS_ALLOWED_ORIGINS", f'["{origin}"]', added)
        done.append(("cors", "CORS_ALLOWED_ORIGINS"))
    if fix.cookies:
        if secure:
            text = _set_setting(text, "SESSION_COOKIE_SECURE", "True", added)
            text = _set_setting(text, "CSRF_COOKIE_SECURE", "True", added)
        text = _set_setting(text, "SESSION_COOKIE_HTTPONLY", "True", added)
        text = _set_setting(text, "SESSION_COOKIE_SAMESITE", '"Lax"', added)
        done.append(("cookie", "SESSION_COOKIE_* settings"))
    if added:
        text = text.rstrip("\n") + "\n\n# Security settings from TestSphere fix proposals\n" + "\n".join(added) + "\n"
    return text, done


def _patch_express(text: str, m: re.Match, fix: Fix, origin: str | None, secure: bool,
                   ids: str) -> tuple[str, list[tuple[str, str]]]:
    indent, var = m.group("indent"), m.group("var")
    done: list[tuple[str, str]] = []
    lower = text.lower()
    block: list[str] = []
    if "X-Powered-By" in fix.remove_headers and "x-powered-by" not in lower:
        block.append(f'{indent}{var}.disable("x-powered-by");')
        done.append(("X-Powered-By", f'{var}.disable("x-powered-by")'))
    wanted = {h: v for h, v in fix.set_headers.items() if f'"{h.lower()}"' not in lower and f"'{h.lower()}'" not in lower}
    if wanted:
        block += [f"{indent}{var}.use((req, res, next) => {{"]
        block += [f'{indent}  res.setHeader("{h}", "{_q(v)}");' for h, v in wanted.items()]
        block += [f"{indent}  next();", f"{indent}}});"]
        done += [(h, f"{var}.use(...) header middleware") for h in wanted]
    if block:
        line_no = text[: m.end()].count("\n") + 1
        text = _insert_after_line(text, line_no, "\n".join([f"{indent}// Security headers from TestSphere fix proposals ({ids})", *block]))
    if fix.cors and origin:
        new = re.sub(r"\bcors\(\s*\)", f'cors({{ origin: ["{_q(origin)}"], credentials: true }})', text)
        new = re.sub(r"(\bcors\(\s*\{[^}]*?\borigin\s*:\s*)(true|\"\*\"|'\*')", rf'\1["{_q(origin)}"]', new)
        if new != text:
            text = new
            done.append(("cors", "cors({ origin: [...] })"))
    if fix.cookies:
        opts = f'{{ httpOnly: true{", secure: true" if secure else ""}, sameSite: "lax" }}'
        count = 0
        for name in fix.cookies:
            name_re = r"[^'\"]+" if name == "*" else re.escape(name)
            text, n = re.subn(rf"(\bres\.cookie\(\s*(['\"]){name_re}\2\s*,\s*[^,()]+?)\s*\)", rf"\1, {opts})", text)
            count += n
        if count:
            done.append(("cookie", f"options on {count} res.cookie(...) call(s)"))
    return text, done


def _patch_nginx(text: str, fix: Fix) -> tuple[str, list[tuple[str, str]]]:
    done: list[tuple[str, str]] = []
    m = re.search(r"^(?P<indent>[ \t]*)server\s*\{[ \t]*$", text, re.M)
    if not m:
        return text, done
    inner = m.group("indent") + "    "
    block: list[str] = []
    for h, v in fix.set_headers.items():
        existing = re.compile(rf"^([ \t]*)add_header\s+{re.escape(h)}\s+[^;]*;", re.M | re.I)
        if existing.search(text):
            text = existing.sub(rf'\1add_header {h} "{_q(v)}" always;', text, count=1)
        else:
            block.append(f'{inner}add_header {h} "{_q(v)}" always;')
        done.append((h, "add_header"))
    if "Server" in fix.remove_headers and not re.search(r"^\s*server_tokens\s+off\s*;", text, re.M):
        block.append(f"{inner}server_tokens off;")
        done.append(("Server", "server_tokens off"))
    for h in sorted(fix.remove_headers - {"Server"}):
        block.append(f"{inner}proxy_hide_header {h};")
        done.append((h, "proxy_hide_header"))
    if block:
        m = re.search(r"^(?P<indent>[ \t]*)server\s*\{[ \t]*$", text, re.M)
        line_no = text[: m.end()].count("\n") + 1
        text = _insert_after_line(text, line_no, "\n".join([f"{inner}# Security headers from TestSphere fix proposals", *block]))
    return text, done


# ── Verification and diff ──────────────────────────────────────────────────

# TypeScript: strip the types with Node's built-in stripTypeScriptTypes (Node 22.13+),
# then syntax-check the result as a JavaScript module.
_TS_CHECK = r"""
const m = require("node:module");
if (!m.stripTypeScriptTypes) process.exit(3);
const fs = require("node:fs"), os = require("node:os"), path = require("node:path"), cp = require("node:child_process");
let js;
try { js = m.stripTypeScriptTypes(fs.readFileSync(process.argv[1], "utf8"), { mode: "transform" }); }
catch (e) { console.error(e.message); process.exit(1); }
const out = path.join(os.tmpdir(), "tscheck-" + process.pid + ".mjs");
fs.writeFileSync(out, js);
const r = cp.spawnSync(process.execPath, ["--check", out], { encoding: "utf8" });
fs.unlinkSync(out);
if (r.status) { console.error(r.stderr.split("\\n").filter(Boolean).slice(-2).join(" ")); process.exit(1); }
"""


def _verify(path: Path, text: str) -> tuple[bool | None, str | None]:
    if path.suffix == ".py":
        try:
            compile(text, str(path), "exec")
            return True, None
        except SyntaxError as exc:
            return False, f"Python syntax error at line {exc.lineno}: {exc.msg}"
    if path.suffix in (".ts", ".mts", ".cts") and shutil.which("node"):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / f"check{path.suffix}"
            probe.write_text(text, encoding="utf-8")
            try:
                res = subprocess.run(["node", "-e", _TS_CHECK, str(probe)], capture_output=True, text=True, timeout=30,
                                     env={**os.environ, "NODE_NO_WARNINGS": "1"})
            except (OSError, subprocess.TimeoutExpired):
                return None, "Could not run the TypeScript check"
        if res.returncode == 3:
            return None, "TypeScript not checked (needs Node 22.13 or newer)"
        return (True, None) if res.returncode == 0 else (False, res.stderr.strip()[-300:] or "TypeScript syntax error")
    if path.suffix in (".js", ".mjs", ".cjs") and shutil.which("node"):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / f"check{path.suffix}"
            probe.write_text(text, encoding="utf-8")
            try:
                res = subprocess.run(["node", "--check", str(probe)], capture_output=True, text=True, timeout=20)
            except (OSError, subprocess.TimeoutExpired):
                return None, "Could not run node --check"
        return (True, None) if res.returncode == 0 else (False, res.stderr.strip().splitlines()[-1] if res.stderr.strip() else "node --check failed")
    return None, None


def _diff(rel: str, old: str, new: str) -> str:
    if not old.endswith("\n"):
        old += "\n"
    if not new.endswith("\n"):
        new += "\n"
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))


# ── Entry point ────────────────────────────────────────────────────────────

def build_patch(root: Path, findings: list[dict], site_url: str | None = None) -> PatchResult:
    """A patch for *findings* against the checkout at *root* (read-only)."""
    root = root.resolve()
    fix, manual = fixes_for(findings)
    origin = None
    secure = True
    if site_url:
        parts = urlsplit(site_url)
        origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else None
        secure = parts.scheme == "https"
    ids = ", ".join(sorted(set(fix.sources.values())))
    edited: dict[Path, tuple[str, str]] = {}   # path -> (original, current)
    applied: list[Applied] = []
    handled: set[str] = set()
    frameworks: list[str] = []

    def current(path: Path) -> str:
        return edited[path][1] if path in edited else _read(path)

    def save(path: Path, new: str) -> None:
        original = edited[path][0] if path in edited else _read(path)
        edited[path] = (original, new)

    def mark(topic: str, path: Path, how: str) -> None:
        handled.add(topic)
        applied.append(Applied(fix.sources.get(topic, topic), path.relative_to(root).as_posix(), how))

    py_apps = _python_apps(root)
    express = _express_apps(root)
    django = _django_settings(root)
    nextjs = _next_configs(root)
    nginx = _nginx_confs(root)
    frameworks += sorted({a[1] for a in py_apps})
    if django:
        frameworks.append("django")
    if express:
        frameworks.append("express")
    if nextjs:
        frameworks.append("nextjs")
    if nginx:
        frameworks.append("nginx")

    # Headers: in app code if there is any, else in nginx
    if py_apps and (fix.set_headers or fix.remove_headers):
        path, kind, var, end_line, indent = py_apps[0]
        new, set_h, removed = _patch_python_headers(current(path), kind, var, end_line, fix, indent)
        if new != current(path):
            save(path, new)
        hook = "after_request hook" if kind == "flask" else "HTTP middleware"
        for h in set_h:
            note = " (check that scripts, styles and embeds still load)" if h == "Content-Security-Policy" else ""
            mark(h, path, f"{hook} sets {h}{note}")
        for h in removed:
            mark(h, path, f"{hook} removes {h}")
        for h in fix.set_headers.keys() - set(set_h):
            mark(h, path, f"{h} is already set here; the deployed version may predate it")
        if "Server" in fix.remove_headers:
            for p in [path, *[a[0] for a in py_apps[1:]], *_files(root, (".py",))]:
                patched = _patch_uvicorn(current(p))
                if patched:
                    save(p, patched)
                    mark("Server", p, "uvicorn.run(..., server_header=False)")
                    break
    elif express and (fix.set_headers or fix.remove_headers or fix.cors or fix.cookies):
        path, m = express[0]
        new, done = _patch_express(current(path), m, fix, origin, secure, ids)
        if new != current(path):
            save(path, new)
        for topic, how in done:
            mark(topic, path, how)
    elif django:
        path = django[0]
        new, done = _patch_django(current(path), fix, origin, secure)
        if new != current(path):
            save(path, new)
        for topic, how in done:
            mark(topic, path, how)
    elif nextjs and (fix.set_headers or fix.remove_headers):
        path = nextjs[0]
        new, done = _patch_next(current(path), fix, ids)
        if new != current(path):
            save(path, new)
        for topic, how in done:
            mark(topic, path, how)
    if nginx and not (py_apps or express or django or nextjs):
        path = nginx[0]
        new, done = _patch_nginx(current(path), fix)
        if new != current(path):
            save(path, new)
        for topic, how in done:
            mark(topic, path, how)

    # CORS and cookies in Python code
    if fix.cors and origin and "cors" not in handled:
        for p in [a[0] for a in py_apps] + _files(root, (".py",)):
            try:
                patched = _patch_python_cors(current(p), origin)
            except SyntaxError:
                continue
            if patched:
                save(p, patched)
                mark("cors", p, f"CORSMiddleware allow_origins = [\"{origin}\"]")
                break
    if fix.cookies and "cookie" not in handled and (py_apps or not (express or django)):
        for p in _files(root, (".py",)):
            try:
                new, n = _patch_python_cookies(current(p), fix.cookies, secure)
            except SyntaxError:
                continue
            if n:
                save(p, new)
                mark("cookie", p, f"httponly/secure/samesite on {n} set_cookie(...) call(s)")

    for topic, cid in fix.sources.items():
        if topic not in handled and not any(m.check_id == cid for m in manual):
            reason = {
                "cors": "No CORS configuration this patcher can edit was found (CORSMiddleware(allow_origins=...), cors(), "
                        "or Django CORS_ALLOW_ALL_ORIGINS). Restrict Access-Control-Allow-Origin to trusted origins by hand.",
                "cookie": "No set_cookie(...) / res.cookie(name, value) call for this cookie was found.",
                "Server": "The Server header is added by the web server (e.g. run uvicorn with --no-server-header, "
                          "or server_tokens off in nginx).",
            }.get(topic, f"No supported app or server configuration was found to set {topic}.")
            manual.append(Manual(cid, reason))

    files = []
    for path, (original, new) in sorted(edited.items(), key=lambda kv: str(kv[0])):
        rel = path.relative_to(root).as_posix()
        ok, note = _verify(path, new)
        files.append(FileChange(rel, _diff(rel, original, new), ok, note, new if new.endswith("\n") else new + "\n"))
    return PatchResult(frameworks, files, applied, manual)
