"""
TestSphere-AI — Reusable Test Fixtures

Shared helper functions for creating test data.
These fixtures are used across multiple test modules.
"""

from __future__ import annotations

from agents.llm.client import LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.providers.mock import MockLLMProvider
from agents.planner.planner import LLMTestPlanner
from agents.planner.schemas import (
    ApplicationContext,
    ElementContext,
    PageContext,
)


def create_mock_config() -> LLMConfig:
    """Return a standard mock LLM configuration."""
    return LLMConfig(provider="mock", model="mock-model", max_retries=0)


def create_mock_provider(
    config: LLMConfig | None = None,
    *,
    simulate: str | None = None,
) -> MockLLMProvider:
    """Return a MockLLMProvider instance.

    Parameters
    ----------
    config:
        Optional LLM config. Defaults to ``create_mock_config()``.
    simulate:
        Optional failure simulation mode.
    """
    cfg = config or create_mock_config()
    return MockLLMProvider(cfg, simulate=simulate)


def create_llm_session(
    provider: MockLLMProvider | None = None,
    config: LLMConfig | None = None,
) -> LLMClientSession:
    """Return an LLMClientSession wrapping a mock provider.

    Parameters
    ----------
    provider:
        Optional mock provider. A new one is created if not provided.
    config:
        Optional LLM config.
    """
    cfg = config or create_mock_config()
    prov = provider or create_mock_provider(cfg)
    return LLMClientSession(prov, cfg)


def create_test_planner(
    provider: MockLLMProvider | None = None,
) -> tuple[LLMTestPlanner, MockLLMProvider]:
    """Create an LLMTestPlanner with a fresh mock provider.

    Returns
    -------
    tuple[LLMTestPlanner, MockLLMProvider]
        The planner and its underlying mock provider (for registering
        responses in tests).
    """
    cfg = create_mock_config()
    prov = provider or create_mock_provider(cfg)
    session = LLMClientSession(prov, cfg)
    planner = LLMTestPlanner(session)
    return planner, prov


def create_sample_login_context() -> ApplicationContext:
    """Return a reusable sample ApplicationContext for a login application.

    Application: Demo Login Application
    Pages:
      - /login (Login Page) with email input, password input, login button,
        forgot password link
      - /dashboard (Dashboard) with welcome heading and logout button

    This fixture is used in Test Planner pipeline tests.
    """
    return ApplicationContext(
        app_name="Demo Application",
        app_url="http://localhost:3000",
        description="A demo web application with login and dashboard.",
        pages=[
            PageContext(
                url="/login",
                name="Login",
                title="Login Page",
                description="User authentication page",
                elements=[
                    ElementContext(
                        tag="input",
                        id="email",
                        name="email",
                        type="email",
                        placeholder="Enter email",
                    ),
                    ElementContext(
                        tag="input",
                        id="password",
                        name="password",
                        type="password",
                        placeholder="Enter password",
                    ),
                    ElementContext(
                        tag="button",
                        id="login-button",
                        text="Login",
                    ),
                    ElementContext(
                        tag="a",
                        id="forgot-password",
                        text="Forgot Password?",
                    ),
                ],
            ),
            PageContext(
                url="/dashboard",
                name="Dashboard",
                title="Dashboard",
                description="Main application dashboard",
                elements=[
                    ElementContext(
                        tag="h1",
                        id="welcome-heading",
                        text="Welcome",
                    ),
                    ElementContext(
                        tag="button",
                        id="logout-button",
                        text="Logout",
                    ),
                ],
            ),
        ],
        technology_stack=["React", "Node.js"],
    )


def create_minimal_context() -> ApplicationContext:
    """Return a minimal valid ApplicationContext (no pages/elements)."""
    return ApplicationContext(
        app_name="Minimal App",
        app_url="http://localhost:8080",
    )
