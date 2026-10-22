"""Hosted-server safety defaults: CORS origins and refusing to run open by accident."""

import importlib

import pytest
from fastapi.testclient import TestClient

import backend.config as config

HOSTING = ("RENDER", "DYNO", "RAILWAY_ENVIRONMENT", "FLY_APP_NAME", "K_SERVICE", "VERCEL")


@pytest.fixture
def env(monkeypatch):
    for name in (*HOSTING, "APP_ENV", "AUTH_REQUIRED", "CORS_ORIGINS",
                 "FIREBASE_CREDENTIALS", "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def fresh_settings(monkeypatch):
    settings = config.Settings()
    monkeypatch.setattr(config, "settings", settings)
    return settings


def test_hosted_server_without_credentials_refuses_to_start(env):
    env.setenv("RENDER", "true")
    fresh_settings(env)
    assert "Sign-in is off on a public server" in config.startup_safety_problem()


def test_production_app_env_counts_as_hosted(env):
    env.setenv("APP_ENV", "production")
    fresh_settings(env)
    assert config.startup_safety_problem()


def test_explicit_opt_out_or_credentials_are_allowed(env):
    env.setenv("RENDER", "true")
    env.setenv("AUTH_REQUIRED", "false")
    fresh_settings(env)
    assert config.startup_safety_problem() is None

    env.delenv("AUTH_REQUIRED")
    env.setenv("FIREBASE_CREDENTIALS", "{}")
    fresh_settings(env)
    assert config.startup_safety_problem() is None


def test_local_development_runs_without_sign_in(env):
    fresh_settings(env)
    assert config.startup_safety_problem() is None


def test_the_app_does_not_start_when_unsafe(monkeypatch):
    import backend.main as main

    monkeypatch.setattr(main, "startup_safety_problem", lambda: "unsafe")
    with pytest.raises(RuntimeError, match="unsafe"):
        with TestClient(main.app):
            pass


def test_cors_defaults(env):
    assert fresh_settings(env).CORS_ORIGINS == [
        "http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"]
    env.setenv("RENDER", "true")
    assert fresh_settings(env).CORS_ORIGINS == []
    env.setenv("CORS_ORIGINS", "https://testsphere.vercel.app/, https://admin.example.org")
    assert fresh_settings(env).CORS_ORIGINS == ["https://testsphere.vercel.app", "https://admin.example.org"]


def test_cors_does_not_echo_unknown_origins():
    from backend.main import app

    resp = TestClient(app).get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers
    assert "access-control-allow-credentials" not in resp.headers
