"""
ingestion/analyzer.py
=====================
Static analysis of a source tree into a project ``Blueprint`` (module 5.1).

Pure filesystem work — nothing in the repository is executed.  The blueprint
records what the rest of the pipeline needs to know about a codebase:
languages, frameworks, dependencies, existing test suites, entry points,
HTTP routes (candidate targets for QA and the Attacker Agent) and risks found
statically (committed secrets, committed .env files, debug flags).
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build", ".next",
    ".nuxt", "coverage", ".pytest_cache", ".mypy_cache", "target", "vendor", ".idea", ".vscode",
}
MAX_FILES = 20_000
MAX_TEXT_BYTES = 1_000_000

LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java", ".kt": "Kotlin", ".go": "Go",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".rs": "Rust", ".swift": "Swift", ".c": "C",
    ".h": "C", ".cpp": "C++", ".hpp": "C++", ".html": "HTML", ".css": "CSS", ".scss": "CSS",
    ".vue": "Vue", ".svelte": "Svelte", ".sql": "SQL", ".sh": "Shell", ".ps1": "PowerShell",
}

# dependency name -> framework label
FRAMEWORKS = {
    "react": "React", "next": "Next.js", "vue": "Vue", "@angular/core": "Angular", "svelte": "Svelte",
    "express": "Express", "fastify": "Fastify", "@nestjs/core": "NestJS", "vite": "Vite",
    "tailwindcss": "Tailwind CSS", "fastapi": "FastAPI", "django": "Django", "flask": "Flask",
    "sqlalchemy": "SQLAlchemy", "langchain-core": "LangChain", "langgraph": "LangGraph",
    "playwright": "Playwright", "@playwright/test": "Playwright", "pytest": "pytest", "jest": "Jest",
    "vitest": "Vitest", "cypress": "Cypress", "spring-boot-starter-web": "Spring Boot", "rails": "Rails",
    "laravel/framework": "Laravel", "github.com/gin-gonic/gin": "Gin",
}

ROUTE_PATTERNS = [
    # FastAPI / Flask / APIRouter:  @app.get("/x"), @router.post('/x'), @bp.route("/x")
    (re.compile(r"@(?P<var>\w+)\.(get|post|put|patch|delete|route)\(\s*['\"]([^'\"]*)['\"]"), "python"),
    # Express / Fastify:  app.get('/x', ...), router.post("/x", ...)
    (re.compile(r"\b(?:app|router|server|api)\.(get|post|put|patch|delete|all)\(\s*['\"`]([^'\"`]+)['\"`]"), "js"),
    # Spring:  @GetMapping("/x")
    (re.compile(r"@(Get|Post|Put|Patch|Delete|Request)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?['\"]([^'\"]+)['\"]"), "java"),
    # Django:  path("x/", view), re_path(r"^x/$", view), url(r"^x/?$", view)
    (re.compile(r"\b(path|re_path|url)\(\s*r?['\"]([^'\"]*)['\"]\s*,"), "django"),
    # Django REST framework:  router.register(r"articles", ViewSet)
    (re.compile(r"\b\w+\.(register)\(\s*r?['\"]([^'\"]+)['\"]\s*,"), "django"),
]

# Flask:  @bp.route("/x", methods=["POST", "DELETE"])
_FLASK_METHODS = re.compile(r"methods\s*=\s*[\[(]([^\])]*)[\])]")

SECRET_PATTERNS = [
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b")),
    ("Hardcoded credential", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|access[_-]?key)\b\s*[:=]\s*['\"]([^'\"\s]{8,})['\"]")),
]
_PLACEHOLDER = re.compile(r"(?i)(example|changeme|your[_-]|xxx|<|\$\{|\{|placeholder|dummy|test|sample|\*\*\*)")

# FastAPI:  router = APIRouter(prefix="/security", ...)
ROUTER_PREFIX = re.compile(r"(\w+)\s*=\s*APIRouter\([^)]*?prefix\s*=\s*['\"]([^'\"]+)['\"]", re.S)

TEST_FILE = re.compile(r"(^test_.*\.py$|_test\.py$|\.(test|spec)\.[jt]sx?$|_test\.go$|Test\.java$|Tests?\.cs$)")


class LanguageStat(BaseModel):
    files: int = 0
    lines: int = 0


class TestSuite(BaseModel):
    framework: str
    files: int
    examples: list[str] = Field(default_factory=list)


class Route(BaseModel):
    method: str
    path: str
    file: str
    line: int


class Risk(BaseModel):
    kind: str
    file: str
    line: int | None = None
    detail: str


class Blueprint(BaseModel):
    name: str
    source: str
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    files_total: int = 0
    truncated: bool = False
    languages: dict[str, LanguageStat] = Field(default_factory=dict)
    frameworks: list[str] = Field(default_factory=list)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    test_suites: list[TestSuite] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)

    @property
    def primary_language(self) -> str | None:
        code = {k: v for k, v in self.languages.items() if k not in ("HTML", "CSS")}
        pool = code or self.languages
        return max(pool, key=lambda k: pool[k].lines) if pool else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_repo(root: Path, *, source: str | None = None, name: str | None = None) -> Blueprint:
    """Walk *root* and build its ``Blueprint``."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    bp = Blueprint(name=name or root.name, source=source or str(root))
    files = _list_files(root, bp)
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731

    langs: dict[str, LanguageStat] = {}
    tests: dict[str, list[str]] = {}

    for path in files:
        r = rel(path)
        lang = LANGUAGES.get(path.suffix.lower())
        text = _read_text(path) if lang or _is_config(path) or path.name.startswith(".env") else None

        if lang:
            stat = langs.setdefault(lang, LanguageStat())
            stat.files += 1
            if text is not None:
                stat.lines += text.count("\n") + 1

        suite = _test_framework(path, r)
        if suite:
            tests.setdefault(suite, []).append(r)

        if _is_config(path):
            bp.config_files.append(r)

        if path.name.startswith(".env") and not path.name.endswith((".example", ".sample", ".template")):
            bp.risks.append(Risk(kind="Committed .env file", file=r, detail="Environment files often hold secrets; keep them out of version control."))

        if text is not None and lang:
            if not suite:  # fixtures in tests are not the app's real routes
                bp.routes += _routes(text, r, path.suffix.lower())
            bp.risks += _secrets(text, r, in_tests=bool(suite) or "/tests/" in f"/{r}" or r.startswith("test"))
            bp.risks += _debug_flags(text, r)
        elif text is not None and path.name.startswith(".env"):
            bp.risks += _secrets(text, r)

    bp.languages = dict(sorted(langs.items(), key=lambda kv: -kv[1].lines))
    bp.test_suites = [TestSuite(framework=f, files=len(v), examples=v[:5]) for f, v in sorted(tests.items())]
    bp.dependencies = _dependencies(root)
    bp.frameworks = _frameworks(bp.dependencies, tests)
    bp.entry_points = _entry_points(root, files, rel)
    bp.routes = bp.routes[:500]
    return bp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_files(root: Path) -> list[Path] | None:
    """Tracked + untracked-but-not-ignored files when *root* is a git checkout (respects .gitignore)."""
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    files = []
    for rel in result.stdout.decode("utf-8", errors="ignore").split("\0"):
        if not rel or any(part in SKIP_DIRS for part in rel.split("/")[:-1]):
            continue
        p = root / rel
        if p.is_file() and not p.is_symlink():
            files.append(p)
    return sorted(files)


def _list_files(root: Path, bp: Blueprint) -> list[Path]:
    tracked = _git_files(root)
    if tracked is not None:
        bp.truncated = len(tracked) > MAX_FILES
        out = tracked[:MAX_FILES]
        bp.files_total = len(out)
        return out

    out: list[Path] = []
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for p in entries:
            if p.is_symlink():
                continue  # never follow links out of the repository
            if p.is_dir():
                if p.name not in SKIP_DIRS:
                    stack.append(p)
            elif p.is_file():
                if len(out) >= MAX_FILES:
                    bp.truncated = True
                    bp.files_total = len(out)
                    return out
                out.append(p)
    bp.files_total = len(out)
    return out


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


_CONFIG_NAMES = {
    "package.json", "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "pom.xml", "build.gradle",
    "go.mod", "Gemfile", "composer.json", "Cargo.toml", "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "vercel.json", "render.yaml", "netlify.toml", "tsconfig.json", "vite.config.js", "vite.config.ts",
    "playwright.config.ts", "playwright.config.js", "jest.config.js", "vitest.config.ts", "pytest.ini", "tox.ini",
}


def _is_config(path: Path) -> bool:
    return path.name in _CONFIG_NAMES or (path.parent.name == "workflows" and path.suffix in (".yml", ".yaml"))


def _test_framework(path: Path, rel: str) -> str | None:
    name = path.name
    if name.startswith("playwright.config") or "/e2e/" in f"/{rel}" and path.suffix in (".ts", ".js"):
        return "Playwright"
    if name.startswith("cypress.config") or rel.startswith("cypress/"):
        return "Cypress"
    if not TEST_FILE.search(name):
        return None
    if path.suffix == ".py":
        return "pytest"
    if path.suffix == ".go":
        return "go test"
    if path.suffix == ".java":
        return "JUnit"
    if path.suffix == ".cs":
        return ".NET test"
    return "Jest/Vitest"


def _routes(text: str, rel: str, suffix: str) -> list[Route]:
    routes = []
    prefixes = dict(ROUTER_PREFIX.findall(text)) if suffix == ".py" else {}
    for pattern, kind in ROUTE_PATTERNS:
        if kind == "python" and suffix != ".py":
            continue
        if kind == "js" and suffix not in (".js", ".ts", ".mjs", ".cjs"):
            continue
        if kind == "java" and suffix not in (".java", ".kt"):
            continue
        if kind == "django" and not (suffix == ".py" and rel.endswith("urls.py")):
            continue
        for m in pattern.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            if text[line_start:m.start()].lstrip().startswith(("#", "//", "*", "/*")):
                continue  # example in a comment, not a real route
            groups = m.groups()[-2:]  # (method, path); python pattern has a leading router-variable group
            method = groups[0].upper()
            method = {"ROUTE": "ANY", "ALL": "ANY", "REQUEST": "ANY", "PATH": "ANY", "RE_PATH": "ANY",
                      "URL": "ANY", "REGISTER": "ANY"}.get(method, method)
            path = groups[1]
            if kind == "python":
                path = prefixes.get(m.group("var"), "") + path
            if kind == "django":
                path = re.sub(r"^\^|/?\??\$$", "", path)  # regex anchors: ^articles/feed/?$ -> articles/feed
                path = re.sub(r"\(\?P<(\w+)>[^)]*\)", r"<\1>", path)  # (?P<slug>[-\w]+) -> <slug>
                path = "/" + path.lstrip("/")
            path = path or "/"
            methods = [method]
            if method == "ANY" and kind == "python":
                call = text[m.end(): text.find(")", m.end()) + 1]
                listed = _FLASK_METHODS.search(call)
                if listed:
                    methods = [x.strip(" '\"").upper() for x in listed.group(1).split(",") if x.strip(" '\"")] or methods
            line = text.count("\n", 0, m.start()) + 1
            routes += [Route(method=meth, path=path, file=rel, line=line) for meth in methods]
    return routes


def _redact(value: str) -> str:
    return value[:4] + "…" if len(value) > 4 else "…"


def _secrets(text: str, rel: str, in_tests: bool = False) -> list[Risk]:
    risks = []
    for label, pattern in SECRET_PATTERNS:
        if label == "Hardcoded credential" and in_tests:
            continue  # test fixtures use fake keys on purpose; high-confidence patterns still apply
        for m in pattern.finditer(text):
            value = m.group(1) if pattern.groups else m.group(0)
            if label == "Hardcoded credential" and _PLACEHOLDER.search(value):
                continue
            risks.append(Risk(
                kind=label, file=rel, line=text.count("\n", 0, m.start()) + 1,
                detail=f"Looks like a {label.lower()} ({_redact(value)}); move it to a secret store and rotate it.",
            ))
    return risks[:50]


_DEBUG = re.compile(r"^\s*DEBUG\s*=\s*True\b", re.M)


def _in_docstring(text: str, pos: int) -> bool:
    before = text[:pos]
    return before.count('"""') % 2 == 1 or before.count("\'\'\'") % 2 == 1


def _debug_flags(text: str, rel: str) -> list[Risk]:
    return [
        Risk(kind="Debug mode enabled", file=rel, line=text.count("\n", 0, m.start()) + 1,
             detail="DEBUG = True in code; make sure it is off in production.")
        for m in _DEBUG.finditer(text)
        if not _in_docstring(text, m.start())
    ]


def _dependencies(root: Path) -> dict[str, list[str]]:
    deps: dict[str, set[str]] = {}

    for pkg in [root / "package.json", *root.glob("*/package.json")]:
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        names = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        deps.setdefault("npm", set()).update(names)

    for req in [root / "requirements.txt", *root.glob("*/requirements.txt")]:
        try:
            for line in req.read_text(encoding="utf-8").splitlines():
                name = re.split(r"[<>=!~\[;\s]", line.strip(), maxsplit=1)[0]
                if name and not name.startswith(("#", "-")):
                    deps.setdefault("pip", set()).add(name.lower())
        except OSError:
            continue

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = data.get("project", {})
            entries = list(project.get("dependencies", []))
            for extra in project.get("optional-dependencies", {}).values():
                entries += extra
            for group in data.get("dependency-groups", {}).values():  # PEP 735 (uv, pdm)
                entries += [e for e in group if isinstance(e, str)]
            for entry in entries:
                name = re.split(r"[<>=!~\[;\s]", entry.strip(), maxsplit=1)[0]
                if name:
                    deps.setdefault("pip", set()).add(name.lower())
            poetry = data.get("tool", {}).get("poetry", {})
            tables = [poetry.get("dependencies", {}), poetry.get("dev-dependencies", {}),
                      *(g.get("dependencies", {}) for g in poetry.get("group", {}).values())]
            for table in tables:
                deps.setdefault("pip", set()).update(n.lower() for n in table if n.lower() != "python")
        except (OSError, tomllib.TOMLDecodeError):
            pass

    gomod = root / "go.mod"
    if gomod.is_file():
        for m in re.finditer(r"^\s*([\w./-]+\.[\w./-]+)\s+v", gomod.read_text(encoding="utf-8", errors="ignore"), re.M):
            deps.setdefault("go", set()).add(m.group(1))

    pom = root / "pom.xml"
    if pom.is_file():
        for m in re.finditer(r"<artifactId>([^<]+)</artifactId>", pom.read_text(encoding="utf-8", errors="ignore")):
            deps.setdefault("maven", set()).add(m.group(1))

    return {eco: sorted(names) for eco, names in sorted(deps.items())}


def _frameworks(deps: dict[str, list[str]], tests: dict[str, list[str]]) -> list[str]:
    found = Counter()
    for names in deps.values():
        for n in names:
            label = FRAMEWORKS.get(n.lower())
            if label:
                found[label] += 1
    for suite in tests:
        if suite in ("Playwright", "Cypress", "pytest"):
            found[suite] += 1
    return sorted(found)


_ENTRY_NAMES = {"main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "server.js", "server.ts", "index.js",
                "app.js", "main.go", "main.ts", "main.jsx", "main.tsx", "Program.cs", "Application.java"}


def _entry_points(root: Path, files: list[Path], rel) -> list[str]:
    entries = [rel(p) for p in files if p.name in _ENTRY_NAMES and rel(p).count("/") <= 3]
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            if data.get("main"):
                entries.append(f"package.json main: {data['main']}")
            for script in ("start", "dev"):
                if data.get("scripts", {}).get(script):
                    entries.append(f"npm run {script}: {data['scripts'][script]}")
        except (OSError, ValueError):
            pass
    return sorted(dict.fromkeys(entries))[:25]
