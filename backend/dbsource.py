"""
TestSphere-AI — The app's database as an input (read-only).

A project can link the database behind its app (PostgreSQL, or SQLite on a
development server).  TestSphere then

* reads its **schema**: tables, columns, keys, foreign keys and row counts;
* takes a **row-count snapshot** before and after a pipeline's tests, so the
  run shows what the tests changed (``todos +1``);
* **looks for the goal's data** after the tests ("Buy milk" in
  ``todos.title``), proof the app stored what the test entered.

Every session is read-only (``default_transaction_read_only``, SQLite
``mode=ro``) with a statement timeout; nothing is ever written.  The URL is
stored encrypted (``backend/secretbox.py``), never returned, and its host goes
through the SSRF guard: private addresses only where ALLOW_PRIVATE_TARGETS is
on (local development).
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import sqlite3
from contextlib import closing
from typing import Any
from urllib.parse import unquote, urlsplit

from backend.config import settings

MAX_TABLES = 200
MAX_SEARCH_TABLES = 60
STATEMENT_TIMEOUT_MS = 5000
_IDENT = re.compile(r"^[A-Za-z_][\w$]*$")


class DatabaseError(Exception):
    """A database that cannot be used (bad URL, refused host, connection or query failure)."""


def describe_url(url: str) -> str:
    """The URL without credentials, safe to show: ``postgresql://db.example:5432/shop``."""
    p = urlsplit(url)
    if p.scheme == "sqlite":
        return f"sqlite:///{sqlite_path(url)}"
    return f"{p.scheme}://{p.hostname or ''}{f':{p.port}' if p.port else ''}{p.path}"


def sqlite_path(url: str) -> str:
    """The file of a SQLite URL, as SQLAlchemy reads them: ``sqlite:///shop.db`` (relative),
    ``sqlite:////srv/shop.db`` (absolute), ``sqlite:///C:/shop.db`` (Windows)."""
    path = unquote(urlsplit(url).path)
    return path[1:] if path.startswith("/") else path


def check_url(url: str) -> str:
    """Validate a database URL for this server; returns the kind ('postgresql' or 'sqlite')."""
    p = urlsplit(url.strip())
    if p.scheme in ("postgresql", "postgres"):
        if not p.hostname or not p.path.strip("/"):
            raise DatabaseError("Use postgresql://user:password@host:5432/database.")
        _check_host(p.hostname, p.port or 5432)
        return "postgresql"
    if p.scheme == "sqlite":
        if not settings.INGEST_ALLOW_LOCAL_PATHS:
            raise DatabaseError("SQLite files can only be used on a development server; link a PostgreSQL database.")
        return "sqlite"
    raise DatabaseError("Only PostgreSQL (postgresql://…) and, in development, SQLite (sqlite:///path) are supported.")


def _check_host(host: str, port: int) -> None:
    if settings.ALLOW_PRIVATE_TARGETS:
        return
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise DatabaseError(f"{host} does not resolve: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise DatabaseError(f"{host} resolves to {ip}, a private or internal address. "
                                "This server only connects to public database hosts.")


class Database:
    """A read-only session; use as a context manager."""

    def __init__(self, url: str) -> None:
        self.url = url.strip()
        self.kind = check_url(self.url)
        self._conn: Any = None

    def __enter__(self) -> Database:
        try:
            if self.kind == "sqlite":
                path = sqlite_path(self.url)
                self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=STATEMENT_TIMEOUT_MS / 1000)
            else:
                import psycopg

                self._conn = psycopg.connect(
                    self.url.replace("postgres://", "postgresql://", 1), connect_timeout=8, autocommit=True,
                    options=f"-c default_transaction_read_only=on -c statement_timeout={STATEMENT_TIMEOUT_MS}")
        except Exception as exc:  # noqa: BLE001 - any driver error is a readable "cannot connect"
            raise DatabaseError(f"Could not connect to {describe_url(self.url)}: {_short(exc)}") from exc
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._conn is not None:
            self._conn.close()

    def _rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(f"Query failed on {describe_url(self.url)}: {_short(exc)}") from exc

    # ── Schema ──────────────────────────────────────────────────────────
    def tables(self) -> list[str]:
        if self.kind == "sqlite":
            rows = self._rows("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        else:
            rows = self._rows("SELECT table_schema || '.' || table_name FROM information_schema.tables "
                              "WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema') "
                              "ORDER BY 1")
        return [r[0] for r in rows][:MAX_TABLES]

    def columns(self, table: str) -> list[dict[str, Any]]:
        if self.kind == "sqlite":
            return [{"name": r[1], "type": r[2] or "", "nullable": not r[3], "primary_key": bool(r[5])}
                    for r in self._rows(f"PRAGMA table_info({_quote(table)})")]
        schema, name = table.split(".", 1)
        pk = {r[0] for r in self._rows(
            "SELECT kcu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu "
            "ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
            "WHERE tc.constraint_type='PRIMARY KEY' AND tc.table_schema=%s AND tc.table_name=%s", (schema, name))}
        return [{"name": r[0], "type": r[1], "nullable": r[2] == "YES", "primary_key": r[0] in pk}
                for r in self._rows("SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                                    "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", (schema, name))]

    def foreign_keys(self, table: str) -> list[dict[str, str]]:
        if self.kind == "sqlite":
            return [{"column": r[3], "references": f"{r[2]}.{r[4]}"} for r in self._rows(f"PRAGMA foreign_key_list({_quote(table)})")]
        schema, name = table.split(".", 1)
        return [{"column": r[0], "references": f"{r[1]}.{r[2]}"} for r in self._rows(
            "SELECT kcu.column_name, ccu.table_schema || '.' || ccu.table_name, ccu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name "
            "JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name "
            "WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema=%s AND tc.table_name=%s", (schema, name))]

    def count(self, table: str) -> int | None:
        try:
            return int(self._rows(f"SELECT COUNT(*) FROM {_quote(table)}")[0][0])
        except DatabaseError:
            return None  # e.g. a table this user may not read: shown as unknown

    def schema(self) -> dict[str, Any]:
        tables = []
        for t in self.tables():
            tables.append({"name": t, "columns": self.columns(t), "foreign_keys": self.foreign_keys(t), "rows": self.count(t)})
        return {"kind": self.kind, "database": describe_url(self.url), "tables": tables}

    # ── Run checks ──────────────────────────────────────────────────────
    def snapshot(self, tables: list[str] | None = None) -> dict[str, int | None]:
        return {t: self.count(t) for t in (tables or self.tables())}

    def find_value(self, value: str, schema: dict[str, Any]) -> list[str]:
        """``table.column`` where *value* is stored (text columns, exact match)."""
        hits = []
        for t in schema["tables"][:MAX_SEARCH_TABLES]:
            for col in t["columns"]:
                if not re.search(r"char|text|clob|string", col["type"], re.IGNORECASE) or not _IDENT.match(col["name"]):
                    continue
                mark = "?" if self.kind == "sqlite" else "%s"
                try:
                    found = self._rows(f"SELECT 1 FROM {_quote(t['name'])} WHERE {_quote(col['name'])} = {mark} LIMIT 1", (value,))
                except DatabaseError:
                    continue
                if found:
                    hits.append(f"{t['name']}.{col['name']}")
        return hits


def _quote(name: str) -> str:
    """A quoted identifier (``schema.table`` keeps its dot); names come from the catalog, never from users."""
    return ".".join('"' + part.replace('"', '""') + '"' for part in name.split(".", 1))


def _short(exc: BaseException) -> str:
    return re.sub(r"password=\S+", "password=…", str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__)[:200]


def changes(before: dict[str, int | None], after: dict[str, int | None]) -> dict[str, int]:
    """Row-count differences per table (only tables that changed)."""
    return {t: after[t] - before[t] for t in after
            if before.get(t) is not None and after.get(t) is not None and after[t] != before[t]}


# ── Pipeline: before and after the tests ───────────────────────────────────

def start_check(project: dict[str, Any]) -> dict[str, Any] | None:
    """Row counts before the tests run (None when the project has no database)."""
    if not project.get("db_url"):
        return None
    from backend.secretbox import SecretBoxError, decrypt

    try:
        url = decrypt(project["db_url"])
        schema = json.loads(project.get("db_schema") or '{"tables": []}')
        with Database(url) as conn:
            return {"url": url, "schema": schema, "before": conn.snapshot([t["name"] for t in schema["tables"]] or None)}
    except (DatabaseError, SecretBoxError) as exc:
        return {"error": str(exc), "database": project.get("database")}


def finish_check(check: dict[str, Any] | None, values: list[str]) -> dict[str, Any] | None:
    """What the tests changed, and where the goal's values were stored."""
    if check is None:
        return None
    label = describe_url(check["url"]) if "url" in check else check.get("database")
    if check.get("error"):
        return {"database": label, "error": check["error"]}
    try:
        with Database(check["url"]) as conn:
            after = conn.snapshot(list(check["before"]))
            found = {v: conn.find_value(v, check["schema"]) for v in values if v}
    except DatabaseError as exc:
        return {"database": label, "error": str(exc)}
    return {"database": label, "changes": changes(check["before"], after), "found": found, "error": None}


def summary_line(result: dict[str, Any] | None) -> str | None:
    """One line for the report stage."""
    if not result:
        return None
    if result.get("error"):
        return f"database not checked: {result['error']}"
    parts = [f"{t} {n:+d}" for t, n in result["changes"].items()] or ["no rows changed"]
    for value, where in result["found"].items():
        parts.append(f"“{value[:40]}” stored in {', '.join(where)}" if where else f"“{value[:40]}” not found in the database")
    return "database: " + ", ".join(parts)
