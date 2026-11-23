"""The two production images: the backend ships the system tools it shells out
to, and the frontend's nginx serves the dashboard with the backend's security
headers and proxies the API (server-sent events unbuffered)."""

import re
from pathlib import Path

from app.http_hardening import CSP, HEADERS

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DOCKERFILE = ROOT / "backend" / "Dockerfile"
FRONTEND = ROOT / "frontend"


def _runtime_stage(dockerfile: Path) -> str:
    # Everything after the last FROM: the stage the server runs
    return re.split(r"(?m)^FROM ", dockerfile.read_text(encoding="utf-8"))[-1]


def test_the_backend_image_installs_git():
    # Ingestion clones with git; patches and deploy checks call it too
    assert re.search(r"apt-get install[^\n]*\bgit\b", _runtime_stage(BACKEND_DOCKERFILE)), "git missing from the image"


def test_the_backend_image_installs_chromium():
    assert "playwright install --with-deps chromium" in _runtime_stage(BACKEND_DOCKERFILE)


def test_the_backend_image_runs_unprivileged():
    assert re.search(r"(?m)^USER testsphere$", _runtime_stage(BACKEND_DOCKERFILE))


def test_the_frontend_image_is_nginx_serving_the_build():
    stage = _runtime_stage(FRONTEND / "Dockerfile")
    assert stage.startswith("nginxinc/nginx-unprivileged")
    assert "COPY --from=build /src/dist /usr/share/nginx/html" in stage


def test_nginx_proxies_the_api_unbuffered():
    conf = (FRONTEND / "nginx" / "default.conf.template").read_text(encoding="utf-8")
    api = conf[conf.index("location ~ ^/(api"):]
    api = api[: api.index("}")]
    assert "proxy_pass http://$backend;" in api  # URI passed through unchanged
    assert "proxy_buffering off;" in api  # live pipeline events (SSE)
    assert "X-Forwarded-Proto" in api


def test_nginx_sends_the_backends_security_headers():
    headers = (FRONTEND / "nginx" / "security-headers.conf").read_text(encoding="utf-8")
    assert f'Content-Security-Policy "{CSP}"' in headers
    for name, value in HEADERS:
        assert re.search(rf'{re.escape(name.decode())}\s+"{re.escape(value.decode())}"', headers, re.I), name
