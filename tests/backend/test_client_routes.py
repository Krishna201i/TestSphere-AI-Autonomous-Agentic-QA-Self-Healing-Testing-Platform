"""
A single-page app's own pages, and the ones it protects.

Measured on a real Vite + React Router app: ingestion reported its component
files (src/pages/AuthPage.tsx) as routes "/AuthPage" and "/LandingPage" and
missed the router's real pages (/auth, /app ...), so the run only ever tested
the landing page.  Its host answers every path with the same HTML, and the
router sends a signed-out visitor from /app back to /.  Now: the router's
pages are found and marked as client routes, the catch-all check leaves them
alone, and a protected page gets a test that it stays protected.
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.config import settings
from backend.pipeline import runner
from ingestion.analyzer import _client_routes, analyze_repo

# One HTML page for every path; its "router" draws the page or redirects
INDEX = b"""<!doctype html><title>MaintAI</title><div id="root"></div><script>
const signedIn = localStorage.getItem('user');
const root = document.getElementById('root');
const path = location.pathname;
if (path.startsWith('/app') && !signedIn) history.replaceState(null, '', '/');
if (location.pathname === '/auth') root.innerHTML = '<h1>Secure Access</h1><input type="email" placeholder="you@example.com"><button>Login</button>';
else if (location.pathname.startsWith('/app')) root.innerHTML = '<h1>System Overview</h1>';
else root.innerHTML = '<h1>Eliminate Downtime</h1><button>Launch Console</button>';
</script>"""

APP_TSX = """import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
export default function App() {
  return (<BrowserRouter><Routes>
    <Route
      path="/"
      element={<LandingPage />}
    />
    <Route path="/auth" element={<AuthPage />} />
    <Route element={user ? <Layout /> : <Navigate to="/" replace />}>
      <Route path="/app" element={<Dashboard />} />
      <Route path="/app/equipment/:id" element={<EquipmentPage />} />
    </Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></BrowserRouter>);
}"""


@pytest.fixture(scope="module")
def spa():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(INDEX)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_the_router_pages_are_found_as_client_routes():
    routes = _client_routes(APP_TSX, "frontend/src/App.tsx", ".tsx")
    assert [(r.path, r.line) for r in routes] == [("/", 4), ("/auth", 8), ("/app", 10), ("/app/equipment/<id>", 11)]
    assert all(r.client for r in routes)
    # Sidebar-style objects without element/component are links, not route definitions
    assert _client_routes("const items = [{ label: 'Home', path: '/app' }]; // react-router", "x.ts", ".ts") == []
    # Vue Router and createBrowserRouter configs
    vue = "import { createRouter } from 'vue-router'; const routes = [{ path: '/about', component: About }]"
    assert [r.path for r in _client_routes(vue, "router.js", ".js")] == ["/about"]


def test_component_files_are_not_routes_outside_next(tmp_path):
    (tmp_path / "frontend/src/pages").mkdir(parents=True)
    (tmp_path / "frontend/src/pages/AuthPage.tsx").write_text("export default function AuthPage() {}")
    (tmp_path / "frontend/src/App.tsx").write_text(APP_TSX)
    (tmp_path / "frontend/package.json").write_text('{"dependencies": {"react-router-dom": "^7"}}')
    paths = {r.path for r in analyze_repo(tmp_path).routes}
    assert "/AuthPage" not in paths and {"/auth", "/app"} <= paths

    # In a Next.js app the same folder is its router
    (tmp_path / "frontend/package.json").write_text('{"dependencies": {"next": "^15"}}')
    assert "/AuthPage" in {r.path for r in analyze_repo(tmp_path).routes}


def test_a_protected_page_is_tested_to_stay_protected_and_client_pages_are_kept(fresh_store, spa, monkeypatch):
    from backend.services.project_service import ProjectService
    from backend.services.url_analyzer import URLAnalyzerService

    monkeypatch.setattr(settings, "ANALYZE_VISIBILITY", True)
    analysis = asyncio.run(URLAnalyzerService.analyze_live_website(spa + "/"))
    blueprint = {"routes": [{"method": "GET", "path": "/auth", "client": True},
                            {"method": "GET", "path": "/app", "client": True},
                            {"method": "GET", "path": "/api/health"},  # an API: never a page to open
                            {"method": "GET", "path": "/health"}]}     # a server route the host does not serve
    project = ProjectService.create_project(fresh_store, name="SPA", owner_uid="local-dev", app_url=spa + "/")
    _, tests, detail = asyncio.run(runner._plan(fresh_store, project, analysis, blueprint))
    names = {t["name"] for t in tests}

    assert "Code route: GET /app: a signed-out visitor is sent to /" in names
    assert "Code route: GET /auth" in names
    assert "GET /health (answers with the site's catch-all page: not served here)" in detail
    assert "/auth (answers" not in detail and "/app (answers" not in detail

    # The /auth page's own check reads what the router drew
    auth = next(t for t in tests if t["name"] == "Code route: GET /auth")
    assert "Secure Access" in auth["description"]
