"""The app's database as an input: read-only schema, run changes, the goal's data, never a private host when hosted."""

import json
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend import dbsource
from backend.config import settings
from backend.main import app
from backend.models import PROJECTS
from backend.services.project_service import ProjectService


@pytest.fixture
def app_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", True)
    path = tmp_path / "shop.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL);
        CREATE TABLE todos (id INTEGER PRIMARY KEY, title VARCHAR(200), done INTEGER, user_id INTEGER REFERENCES users(id));
        INSERT INTO users (email) VALUES ('ann@shop.test');
        INSERT INTO todos (title, done, user_id) VALUES ('Old task', 0, 1);
    """)
    con.commit()
    con.close()
    return path, f"sqlite:///{path.as_posix()}"


def test_schema_is_read_and_the_session_cannot_write(app_db):
    path, url = app_db
    with dbsource.Database(url) as conn:
        schema = conn.schema()
        with pytest.raises(dbsource.DatabaseError, match="readonly|read-only"):
            conn._rows("INSERT INTO users (email) VALUES ('x')")
    todos = next(t for t in schema["tables"] if t["name"] == "todos")
    assert todos["rows"] == 1
    assert [c["name"] for c in todos["columns"]] == ["id", "title", "done", "user_id"]
    assert todos["columns"][0]["primary_key"] is True
    assert todos["foreign_keys"] == [{"column": "user_id", "references": "users.id"}]
    assert "password" not in dbsource.describe_url("postgresql://u:secret@db.example:5432/shop")


def test_a_run_reports_changed_tables_and_where_the_goals_data_landed(app_db):
    path, url = app_db
    with dbsource.Database(url) as conn:
        schema = conn.schema()
    check = dbsource.start_check({"db_url": _seal(url), "db_schema": json.dumps(schema)})
    con = sqlite3.connect(path)  # what the app does while the tests run
    con.execute("INSERT INTO todos (title, done, user_id) VALUES ('Buy milk', 1, 1)")
    con.commit()
    con.close()
    result = dbsource.finish_check(check, ["Buy milk", "Never stored"])
    assert result["changes"] == {"todos": 1} and result["error"] is None
    assert result["found"] == {"Buy milk": ["todos.title"], "Never stored": []}
    line = dbsource.summary_line(result)
    assert "todos +1" in line and "“Buy milk” stored in todos.title" in line and "“Never stored” not found" in line


def _seal(url):
    from backend.secretbox import encrypt

    return encrypt(url)


@pytest.mark.parametrize(("url", "message"), [
    ("mysql://u:p@db.example/x", "Only PostgreSQL"),
    ("postgresql://u:p@127.0.0.1:5432/shop", "private or internal"),
    ("postgresql://u:p@10.0.0.5/shop", "private or internal"),
    ("postgresql://db.example", "Use postgresql://"),
])
def test_urls_are_checked_before_connecting(url, message, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_TARGETS", False)
    with pytest.raises(dbsource.DatabaseError, match=message):
        dbsource.check_url(url)


def test_sqlite_is_for_development_only(monkeypatch):
    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", False)
    with pytest.raises(dbsource.DatabaseError, match="development server"):
        dbsource.check_url("sqlite:///x.db")


def test_linking_through_the_api_keeps_the_url_secret(app_db, fresh_store):
    _, url = app_db
    project = ProjectService.create_project(fresh_store, name="Shop", owner_uid="local-dev", app_url="http://shop.test/")
    client = TestClient(app)
    view = client.put(f"/api/projects/{project['id']}/database", json={"url": url}).json()
    assert view["connected"] is True and {t["name"] for t in view["tables"]} == {"users", "todos"}
    stored = fresh_store.get(PROJECTS, project["id"])
    assert stored["db_url"] and url not in stored["db_url"]  # encrypted at rest
    listed = client.get(f"/api/projects/{project['id']}").json()
    assert "db_url" not in listed and listed["database"].startswith("sqlite:///")
    bad = client.put(f"/api/projects/{project['id']}/database", json={"url": "sqlite:///does/not/exist.db"})
    assert bad.status_code == 422 and "Could not connect" in bad.json()["detail"]
    assert client.delete(f"/api/projects/{project['id']}/database").status_code == 204
    assert client.get(f"/api/projects/{project['id']}/database").json()["connected"] is False


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="needs TEST_POSTGRES_URL (set in CI)")
def test_postgresql_read_only_schema_and_changes(monkeypatch):
    import psycopg

    monkeypatch.setattr(settings, "ALLOW_PRIVATE_TARGETS", True)  # the CI database is on localhost
    url = os.environ["TEST_POSTGRES_URL"]
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute("DROP TABLE IF EXISTS todos; DROP TABLE IF EXISTS users;"
                      "CREATE TABLE users (id serial PRIMARY KEY, email text);"
                      "CREATE TABLE todos (id serial PRIMARY KEY, title varchar(200), user_id int REFERENCES users(id));"
                      "INSERT INTO users (email) VALUES ('ann@x'); INSERT INTO todos (title, user_id) VALUES ('Old', 1);")
        with dbsource.Database(url) as conn:
            schema = conn.schema()
            with pytest.raises(dbsource.DatabaseError, match="read-only"):
                conn._rows("INSERT INTO users (email) VALUES ('x')")
        todos = next(t for t in schema["tables"] if t["name"] == "public.todos")
        assert todos["rows"] == 1 and todos["foreign_keys"] == [{"column": "user_id", "references": "public.users.id"}]
        assert [c["primary_key"] for c in todos["columns"]] == [True, False, False]
        check = dbsource.start_check({"db_url": _seal(url), "db_schema": json.dumps(schema)})
        admin.execute("INSERT INTO todos (title, user_id) VALUES ('Buy milk', 1)")
    result = dbsource.finish_check(check, ["Buy milk"])
    assert result["changes"] == {"public.todos": 1} and result["found"] == {"Buy milk": ["public.todos.title"]}
