"""
TestSphere-AI — A small login and sign-up site with bugs that can be switched on.

The generation eval (``scripts/generation_eval.py``) plans tests against the
healthy site, then replays them with one bug switched on: a suite that still
passes missed that bug.

Pages (server-rendered HTML, plain forms, no scripts):

- ``/login``          email + password, "Sign in"; a wrong password shows an
                      error (``role=alert``) and keeps the form
- ``/store/login``    the same form under a store header with its own search
                      form and "Search" button first in the page, like many
                      real sites
- ``/signup``         name, email, password, confirm, terms; "Create account"
- ``/account``        signed-in page ("Signed in as ...", "Log out")
- ``/welcome``        after signing up
- ``/logout``

One registered user: ``demo@testsphere.test`` / ``Correct-Horse-7``.

    app = AuthApp(); base = app.start()
    app.set_mutant("login-accepts-wrong-password"); ...; app.stop()
"""

from __future__ import annotations

import html
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

USER_EMAIL = "demo@testsphere.test"
USER_PASSWORD = "Correct-Horse-7"
LOGIN_GOAL = f"log in with {USER_EMAIL} / {USER_PASSWORD}"

# name → what the bug does; "page" says which flow it breaks
MUTANTS: dict[str, dict[str, str]] = {
    "login-rejects-valid": {"page": "login", "bug": "The correct email and password are refused."},
    "login-accepts-wrong-password": {"page": "login", "bug": "Any password signs in."},
    "login-no-error-message": {"page": "login", "bug": "A wrong password shows no error; the form just reloads."},
    "login-empty-submit": {"page": "login", "bug": "Empty fields are not required and sign in."},
    "password-visible": {"page": "login", "bug": "The password field shows what is typed (type=text)."},
    "session-lost-on-reload": {"page": "login", "bug": "The account page signs you out when reloaded."},
    "logout-broken": {"page": "login", "bug": "Log out keeps you signed in."},
    "signup-broken": {"page": "signup", "bug": "Creating an account ends in a server error."},
    "signup-mismatch-accepted": {"page": "signup", "bug": "Different password and confirmation are accepted."},
    "signup-invalid-email-accepted": {"page": "signup", "bug": "An email without @ is accepted."},
    "signup-duplicate-crash": {"page": "signup", "bug": "An email already registered ends in a server error."},
    "signup-no-confirmation": {"page": "signup", "bug": "Success shows the empty form again, no account made."},
}

# Not bugs: things that stop automation.  A test should report them, not fail the site.
BLOCKERS: dict[str, str] = {
    "captcha": "A CAPTCHA must be solved before the form is accepted.",
}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_STORE_HEADER = """<header class="site-header">
  <a href="/store" class="logo">Acme Store</a>
  <form action="/search" method="get" class="search">
    <input type="search" name="q" placeholder="Search products">
    <button type="submit">Search</button>
  </form>
  <nav><a href="/store">Shop</a> <a href="/signup">Create account</a></nav>
</header>"""

_CAPTCHA = """<div class="g-recaptcha" data-sitekey="6Lc-test">
  <iframe title="reCAPTCHA" src="about:blank" width="304" height="78"></iframe>
</div>"""


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>{title}</title></head>"
            f"<body>{body}</body></html>")


def _error(message: str | None) -> str:
    return f'<p class="error" role="alert">{html.escape(message)}</p>' if message else ""


class AuthApp:
    """The site, its users and sessions, and the bug switched on (if any)."""

    def __init__(self) -> None:
        self.mutant: str | None = None
        self.users: dict[str, dict[str, str]] = {}
        self.sessions: dict[str, str] = {}
        self._server: ThreadingHTTPServer | None = None
        self._lock = threading.Lock()
        self.reset()

    # ── control ────────────────────────────────────────────────────────────
    def reset(self) -> None:
        """Only the demo user, nobody signed in."""
        with self._lock:
            self.users = {USER_EMAIL: {"name": "Demo User", "password": USER_PASSWORD}}
            self.sessions = {}

    def set_mutant(self, name: str | None) -> None:
        if name is not None and name not in MUTANTS and name not in BLOCKERS:
            raise ValueError(f"Unknown mutant {name!r}")
        self.mutant = name

    def start(self) -> str:
        app = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server API
                app._handle(self, "GET")

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                app._handle(self, "POST")

            def log_message(self, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # ── requests ───────────────────────────────────────────────────────────
    def _handle(self, req: BaseHTTPRequestHandler, method: str) -> None:
        url = urlparse(req.path)
        form: dict[str, str] = {}
        if method == "POST":
            raw = req.rfile.read(int(req.headers.get("Content-Length") or 0)).decode("utf-8", "replace")
            form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
        sid = self._cookie(req, "sid")
        path = url.path.rstrip("/") or "/"
        routes = {
            ("GET", "/"): lambda: self._redirect(req, "/login"),
            ("GET", "/login"): lambda: self._send(req, 200, self._login_page("/login")),
            ("GET", "/store/login"): lambda: self._send(req, 200, self._login_page("/store/login", store=True)),
            ("POST", "/login"): lambda: self._login(req, form, "/login"),
            ("POST", "/store/login"): lambda: self._login(req, form, "/store/login", store=True),
            ("GET", "/signup"): lambda: self._send(req, 200, self._signup_page()),
            ("POST", "/signup"): lambda: self._signup(req, form),
            ("GET", "/account"): lambda: self._account(req, sid),
            ("GET", "/welcome"): lambda: self._send(req, 200, _page(
                "Welcome", "<main><h1>Account created</h1><p>Welcome aboard. Check your email to confirm it.</p>"
                           '<a href="/login">Sign in</a></main>')),
            ("GET", "/logout"): lambda: self._logout(req, sid),
            ("GET", "/store"): lambda: self._send(req, 200, _page("Acme Store", f"{_STORE_HEADER}<main><h1>Shop</h1></main>")),
            ("GET", "/search"): lambda: self._send(req, 200, _page("Search", f"{_STORE_HEADER}<main><h1>Results</h1></main>")),
        }
        handler = routes.get((method, path))
        if handler is None:
            self._send(req, 404, _page("Not found", "<h1>Not found</h1>"))
        else:
            handler()

    def _login_page(self, action: str, *, store: bool = False, error: str | None = None, email: str = "") -> str:
        required = "" if self.mutant == "login-empty-submit" else " required"
        ptype = "text" if self.mutant == "password-visible" else "password"
        body = f"""{_STORE_HEADER if store else ""}
<main class="auth">
  <h1>Sign in to your account</h1>
  {_error(error)}
  <form action="{action}" method="post" class="login-form">
    <label for="email">Email</label>
    <input id="email" name="email" type="email" autocomplete="username" value="{html.escape(email)}"{required}>
    <label for="password">Password</label>
    <input id="password" name="password" type="{ptype}" autocomplete="current-password"{required}>
    {_CAPTCHA if self.mutant == "captcha" else ""}
    <button type="submit">Sign in</button>
  </form>
  <p><a href="/signup">Create an account</a></p>
</main>"""
        return _page("Sign in · Acme", body)

    def _signup_page(self, error: str | None = None) -> str:
        body = f"""<main class="auth">
  <h1>Create your account</h1>
  {_error(error)}
  <form action="/signup" method="post" class="signup-form">
    <label for="name">Full name</label>
    <input id="name" name="name" type="text" autocomplete="name" required>
    <label for="email">Email</label>
    <input id="email" name="email" type="email" autocomplete="email" required>
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="new-password" minlength="8" required>
    <label for="confirm">Confirm password</label>
    <input id="confirm" name="confirm" type="password" autocomplete="new-password" required>
    <label><input id="terms" name="terms" type="checkbox" required> I accept the terms</label>
    {_CAPTCHA if self.mutant == "captcha" else ""}
    <button type="submit">Create account</button>
  </form>
  <p><a href="/login">Already have an account? Sign in</a></p>
</main>"""
        return _page("Create account · Acme", body)

    def _login(self, req: BaseHTTPRequestHandler, form: dict[str, str], action: str, *, store: bool = False) -> None:
        email, password = form.get("email", "").strip(), form.get("password", "")
        if self.mutant == "captcha":
            self._send(req, 200, self._login_page(action, store=store, error="Please complete the CAPTCHA.", email=email))
            return
        user = self.users.get(email.lower())
        ok = bool(user and user["password"] == password)
        if self.mutant == "login-rejects-valid":
            ok = False
        elif self.mutant == "login-accepts-wrong-password" and user:
            ok = True
        elif self.mutant == "login-empty-submit" and not email and not password:
            ok, email = True, USER_EMAIL
        if not ok:
            error = None if self.mutant == "login-no-error-message" else "Invalid email or password."
            self._send(req, 200, self._login_page(action, store=store, error=error, email=email))
            return
        sid = secrets.token_hex(8)
        with self._lock:
            self.sessions[sid] = email.lower()
        self._redirect(req, "/account", cookie=f"sid={sid}; Path=/; HttpOnly; SameSite=Lax")

    def _signup(self, req: BaseHTTPRequestHandler, form: dict[str, str]) -> None:
        name, email = form.get("name", "").strip(), form.get("email", "").strip().lower()
        password, confirm = form.get("password", ""), form.get("confirm", "")
        if self.mutant == "captcha":
            self._send(req, 200, self._signup_page("Please complete the CAPTCHA."))
            return
        if self.mutant == "signup-broken":
            self._send(req, 500, _page("Server error", "<h1>500 Internal Server Error</h1>"))
            return
        error = None
        if not name or not email or not password or not form.get("terms"):
            error = "Please fill in every field and accept the terms."
        elif not _EMAIL.match(email) and self.mutant != "signup-invalid-email-accepted":
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Use at least 8 characters for the password."
        elif password != confirm and self.mutant != "signup-mismatch-accepted":
            error = "The passwords do not match."
        elif email in self.users:
            if self.mutant == "signup-duplicate-crash":
                self._send(req, 500, _page("Server error", "<h1>500 Internal Server Error</h1>"))
                return
            error = "An account with this email already exists."
        if error:
            self._send(req, 200, self._signup_page(error))
            return
        if self.mutant == "signup-no-confirmation":
            self._send(req, 200, self._signup_page())
            return
        with self._lock:
            self.users[email] = {"name": name, "password": password}
        self._redirect(req, "/welcome")

    def _account(self, req: BaseHTTPRequestHandler, sid: str | None) -> None:
        email = self.sessions.get(sid or "")
        if not email:
            self._redirect(req, "/login")
            return
        if self.mutant == "session-lost-on-reload":
            with self._lock:
                self.sessions.pop(sid or "", None)  # good for one view only
        self._send(req, 200, _page("Your account · Acme", f"""<header><nav><a href="/account">Account</a>
<a href="/logout">Log out</a></nav></header>
<main><h1>Your account</h1><p class="who">Signed in as {html.escape(email)}</p></main>"""))

    def _logout(self, req: BaseHTTPRequestHandler, sid: str | None) -> None:
        if self.mutant != "logout-broken":
            with self._lock:
                self.sessions.pop(sid or "", None)
        self._redirect(req, "/login")

    # ── helpers ────────────────────────────────────────────────────────────
    @staticmethod
    def _cookie(req: BaseHTTPRequestHandler, name: str) -> str | None:
        for part in (req.headers.get("Cookie") or "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return None

    @staticmethod
    def _send(req: BaseHTTPRequestHandler, status: int, body: str) -> None:
        data = body.encode("utf-8")
        req.send_response(status)
        req.send_header("Content-Type", "text/html; charset=utf-8")
        req.send_header("Content-Length", str(len(data)))
        req.end_headers()
        req.wfile.write(data)

    @staticmethod
    def _redirect(req: BaseHTTPRequestHandler, location: str, *, cookie: str | None = None) -> None:
        req.send_response(303)
        req.send_header("Location", location)
        if cookie:
            req.send_header("Set-Cookie", cookie)
        req.send_header("Content-Length", "0")
        req.end_headers()
