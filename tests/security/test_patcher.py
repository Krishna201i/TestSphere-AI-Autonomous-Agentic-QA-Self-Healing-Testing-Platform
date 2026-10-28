"""
Fix patches against real source: each framework gets a patch that applies
with ``git apply`` and, where the framework is installed, actually changes
the response headers.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from security.patcher import build_patch, fixes_for

SITE = "https://shop.example"


def finding(check_id, **extra):
    return {"check_id": check_id, "recommendation": f"fix {check_id}", **extra}


HEADERS = [finding("SEC-HDR-FRAME"), finding("SEC-HDR-XCTO"), finding("SEC-HDR-REFERRER")]


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return root


def git_apply(root: Path, patch: str) -> None:
    """The patch must apply to the untouched checkout exactly as git would."""
    if not shutil.which("git"):
        pytest.skip("git not installed")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "fix.patch").write_text(patch, encoding="utf-8", newline="\n")
    res = subprocess.run(["git", "apply", "--whitespace=nowarn", "fix.patch"], cwd=root, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FASTAPI_APP = """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    app = FastAPI(
        title="Shop",
    )
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)


    @app.get("/")
    def home():
        return {"ok": True}


    @app.get("/login")
    def login():
        resp = JSONResponse({"ok": True})
        resp.set_cookie("session", "abc")
        return resp
"""


def test_fastapi_patch_applies_and_really_sets_the_headers(tmp_path):
    root = write(tmp_path / "repo", {"app/main.py": FASTAPI_APP, "app/__init__.py": ""})
    findings = [*HEADERS, finding("SEC-CORS"), finding("SEC-COOKIE-FLAGS", component="https://shop.example/ (cookie: session)")]
    result = build_patch(root, findings, SITE)

    assert result.frameworks == ["fastapi"]
    assert [f.path for f in result.files] == ["app/main.py"]
    assert result.files[0].verified is True
    assert result.manual == []
    assert {a.check_id for a in result.applied} == {"SEC-HDR-FRAME", "SEC-HDR-XCTO", "SEC-HDR-REFERRER", "SEC-CORS", "SEC-COOKIE-FLAGS"}
    assert '+@app.middleware("http")' in result.patch
    assert '+    allow_origins=' not in result.patch  # replaced in place, not added
    assert 'allow_origins=["https://shop.example"]' in result.patch

    git_apply(root, result.patch)
    from fastapi.testclient import TestClient

    client = TestClient(load(root / "app" / "main.py", "patched_fastapi_app").app)
    resp = client.get("/")
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    cookie = client.get("/login").headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    evil = client.get("/", headers={"Origin": "https://evil.example"})
    assert evil.headers.get("access-control-allow-origin") != "https://evil.example"


def test_patching_twice_only_adds_what_is_missing(tmp_path):
    root = write(tmp_path / "repo", {"main.py": FASTAPI_APP})
    first = build_patch(root, HEADERS[:1], SITE)
    git_apply(root, first.patch)
    second = build_patch(root, HEADERS, SITE)
    assert second.patch.count("@app.middleware") == 0  # the existing hook is extended
    assert '+    response.headers["X-Content-Type-Options"] = "nosniff"' in second.patch
    assert "X-Frame-Options" not in "".join(l for l in second.patch.splitlines() if l.startswith("+"))
    assert any("already set" in a.how for a in second.applied if a.check_id == "SEC-HDR-FRAME")


def test_uvicorn_server_header_and_disclosure(tmp_path):
    root = write(tmp_path / "repo", {"main.py": textwrap.dedent(FASTAPI_APP) + '\nimport uvicorn\n\nif __name__ == "__main__":\n    uvicorn.run(app, host="0.0.0.0")\n'})
    result = build_patch(root, [finding("SEC-DISCLOSURE", evidence=["server: uvicorn"])], SITE)
    assert 'uvicorn.run(app, host="0.0.0.0", server_header=False)' in result.patch
    assert result.manual == []


def test_flask_after_request_hook(tmp_path):
    root = write(tmp_path / "repo", {"app.py": """
        from flask import Flask

        app = Flask(__name__)


        @app.route("/")
        def home():
            return "ok"
    """})
    result = build_patch(root, HEADERS, SITE)
    assert result.frameworks == ["flask"]
    assert "+@app.after_request" in result.patch and result.files[0].verified is True
    git_apply(root, result.patch)
    if importlib.util.find_spec("flask"):
        client = load(root / "app.py", "patched_flask_app").app.test_client()
        assert client.get("/").headers["X-Frame-Options"] == "DENY"


def test_django_settings(tmp_path):
    root = write(tmp_path / "repo", {"shop/settings.py": """
        INSTALLED_APPS = ["django.contrib.admin", "corsheaders"]
        MIDDLEWARE = ["django.middleware.security.SecurityMiddleware"]
        X_FRAME_OPTIONS = "SAMEORIGIN"
        CORS_ALLOW_ALL_ORIGINS = True
    """})
    findings = [*HEADERS, finding("SEC-HDR-HSTS"), finding("SEC-CORS"),
                finding("SEC-COOKIE-FLAGS", component="https://shop.example/ (cookie: sessionid)")]
    result = build_patch(root, findings, SITE)
    text = result.patch
    assert '+X_FRAME_OPTIONS = "DENY"' in text and '-X_FRAME_OPTIONS = "SAMEORIGIN"' in text  # replaced, not duplicated
    assert "+SECURE_CONTENT_TYPE_NOSNIFF = True" in text
    assert "+SECURE_HSTS_SECONDS = 31536000" in text
    assert "+CORS_ALLOW_ALL_ORIGINS = False" in text and '+CORS_ALLOWED_ORIGINS = ["https://shop.example"]' in text
    assert "+SESSION_COOKIE_SECURE = True" in text
    assert result.files[0].verified is True and result.manual == []
    git_apply(root, text)


EXPRESS_APP = """
    const express = require("express");
    const cors = require("cors");

    const app = express();
    app.use(cors());

    app.get("/login", (req, res) => {
      res.cookie("session", token);
      res.send("ok");
    });

    app.listen(3000);
"""


def test_express_middleware_cors_and_cookies(tmp_path):
    root = write(tmp_path / "repo", {"server.js": EXPRESS_APP, "package.json": '{"name": "shop"}'})
    findings = [*HEADERS, finding("SEC-CORS"), finding("SEC-DISCLOSURE", evidence=["x-powered-by: Express"]),
                finding("SEC-COOKIE-FLAGS", component="https://shop.example/ (cookie: session)")]
    result = build_patch(root, findings, SITE)
    text = result.patch
    assert result.frameworks == ["express"]
    assert '+app.disable("x-powered-by");' in text
    assert '+  res.setHeader("X-Frame-Options", "DENY");' in text
    assert 'cors({ origin: ["https://shop.example"], credentials: true })' in text
    assert 'res.cookie("session", token, { httpOnly: true, secure: true, sameSite: "lax" });' in text
    assert result.manual == []
    if shutil.which("node"):
        assert result.files[0].verified is True
    git_apply(root, text)


def test_nginx_when_there_is_no_app_code(tmp_path):
    root = write(tmp_path / "repo", {"deploy/nginx.conf": """
        events {}
        http {
            server {
                listen 80;
                add_header X-Frame-Options SAMEORIGIN;
                location / { root /srv; }
            }
        }
    """})
    result = build_patch(root, [*HEADERS, finding("SEC-DISCLOSURE", evidence=["server: nginx/1.25"])], SITE)
    text = result.patch
    assert result.frameworks == ["nginx"]
    assert '+        add_header X-Frame-Options "DENY" always;' in text  # existing line updated
    assert '+        add_header X-Content-Type-Options "nosniff" always;' in text
    assert "+        server_tokens off;" in text
    assert result.files[0].verified is None  # no checker for nginx
    git_apply(root, text)


def test_unsupported_findings_and_repos_explain_why(tmp_path):
    root = write(tmp_path / "repo", {"README.md": "docs only"})
    result = build_patch(root, [*HEADERS, finding("SEC-TRANSPORT-HTTP")], SITE)
    assert result.files == [] and result.patch == ""
    reasons = {m.check_id: m.reason for m in result.manual}
    assert "SEC-TRANSPORT-HTTP" in reasons
    assert "No supported app" in reasons["SEC-HDR-FRAME"]


def test_findings_group_into_one_fix():
    fix, manual = fixes_for([finding("SEC-HDR-CSP"), finding("SEC-DISCLOSURE", evidence=["x-powered-by: PHP"]),
                             finding("SEC-MIXED-CONTENT")])
    assert "Content-Security-Policy" in fix.set_headers
    assert fix.remove_headers == {"X-Powered-By"}
    assert [m.check_id for m in manual] == ["SEC-MIXED-CONTENT"]


def test_skips_dependencies_tests_and_unparsable_files(tmp_path):
    root = write(tmp_path / "repo", {
        "node_modules/pkg/server.js": EXPRESS_APP,
        "tests/test_app.py": FASTAPI_APP,
        "broken.py": "def (:\n",
        "src/main.py": FASTAPI_APP,
    })
    result = build_patch(root, HEADERS, SITE)
    assert [f.path for f in result.files] == ["src/main.py"]


def test_inserted_hook_is_separated_from_following_code_and_names_only_its_checks(tmp_path):
    root = write(tmp_path / "repo", {"main.py": FASTAPI_APP})
    result = build_patch(root, [finding("SEC-HDR-FRAME"), finding("SEC-TRANSPORT-HTTP")], SITE)
    git_apply(root, result.patch)
    text = (root / "main.py").read_text()
    assert "    return response\n\n\napp.add_middleware" in text
    assert "(SEC-HDR-FRAME)" in text and "SEC-TRANSPORT-HTTP" not in text


def test_flask_app_factory_gets_a_nested_hook(tmp_path):
    root = write(tmp_path / "repo", {"app/__init__.py": """
        from flask import Flask


        def create_app(config_class=None):
            app = Flask(__name__)
            app.config.from_object(config_class)

            @app.route("/")
            def home():
                return "ok"

            return app
    """})
    result = build_patch(root, HEADERS, SITE)
    assert result.frameworks == ["flask"] and result.files[0].verified is True
    assert "+    @app.after_request" in result.patch
    git_apply(root, result.patch)
    if importlib.util.find_spec("flask"):
        module = load(root / "app" / "__init__.py", "patched_flask_factory")
        client = module.create_app().test_client()
        assert client.get("/").headers["X-Frame-Options"] == "DENY"


def test_fastapi_get_application_factory(tmp_path):
    root = write(tmp_path / "repo", {"app/main.py": """
        from fastapi import FastAPI


        def get_application() -> FastAPI:
            application = FastAPI(title="Conduit")

            @application.get("/")
            def home():
                return {"ok": True}

            return application


        app = get_application()
    """})
    result = build_patch(root, HEADERS, SITE)
    assert result.frameworks == ["fastapi"] and result.files[0].verified is True
    git_apply(root, result.patch)
    from fastapi.testclient import TestClient

    client = TestClient(load(root / "app" / "main.py", "patched_fastapi_factory").app)
    assert client.get("/").headers["x-content-type-options"] == "nosniff"
    # a second patch extends the nested hook instead of adding another
    again = build_patch(root, [finding("SEC-HDR-CSP")], SITE)
    assert "@application.middleware" not in again.patch and "Content-Security-Policy" in again.patch


def test_typescript_express_patches_are_syntax_checked(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    root = write(tmp_path / "repo", {"src/main.ts": """
        import express, { Express } from "express";

        const app: Express = express();
        app.get("/", (req, res) => res.send("ok"));
        app.listen(3000);
    """})
    result = build_patch(root, HEADERS, SITE)
    assert result.frameworks == ["express"]
    assert result.files[0].verified in (True, None)  # None only on Node older than 22.13
    if result.files[0].verified is None:
        assert "Node 22.13" in result.files[0].check_note


def test_nextjs_config_gets_headers_and_no_powered_by(tmp_path):
    root = write(tmp_path / "repo", {
        "next.config.mjs": """
            /** @type {import('next').NextConfig} */
            export default {
              reactStrictMode: true,
            };
        """,
        "package.json": '{"name": "shop", "dependencies": {"next": "15.0.0"}}',
    })
    result = build_patch(root, [*HEADERS, finding("SEC-DISCLOSURE", evidence=["x-powered-by: Next.js"])], SITE)
    text = result.patch
    assert result.frameworks == ["nextjs"]
    assert "+  poweredByHeader: false," in text
    assert '+      { key: "X-Frame-Options", value: "DENY" },' in text
    assert result.manual == []
    git_apply(root, text)
    if shutil.which("node"):
        assert result.files[0].verified is True
        # The patched config really answers every path with the headers
        script = ("import(process.argv[1]).then(async (m) => console.log(JSON.stringify("
                  "{ powered: m.default.poweredByHeader, rules: await m.default.headers() })));")
        out = subprocess.run(["node", "-e", script, (root / "next.config.mjs").as_uri()],
                             capture_output=True, text=True, timeout=30, check=True).stdout
        loaded = json.loads(out)
        assert loaded["powered"] is False
        assert loaded["rules"][0]["source"] == "/(.*)"
        assert {"key": "X-Content-Type-Options", "value": "nosniff"} in loaded["rules"][0]["headers"]


def test_nextjs_typescript_config(tmp_path):
    root = write(tmp_path / "repo", {"next.config.ts": """
        import type { NextConfig } from "next";

        const nextConfig: NextConfig = {
          images: { unoptimized: true },
        };

        export default nextConfig;
    """})
    result = build_patch(root, HEADERS, SITE)
    assert "+  async headers() {" in result.patch
    git_apply(root, result.patch)


def test_nextjs_config_with_its_own_headers_is_left_to_a_manual_change(tmp_path):
    root = write(tmp_path / "repo", {"next.config.js": """
        module.exports = {
          async headers() {
            return [{ source: "/api/(.*)", headers: [{ key: "Cache-Control", value: "no-store" }] }];
          },
        };
    """})
    result = build_patch(root, HEADERS, SITE)
    assert result.files == []  # never merged into a headers() it did not write
    assert {m.check_id for m in result.manual} == {"SEC-HDR-FRAME", "SEC-HDR-XCTO", "SEC-HDR-REFERRER"}
