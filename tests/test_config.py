"""
TestSphere-AI — Configuration Tests

Validates that LLMConfig loads correctly from environment
variables and handles missing/default values properly.
"""

import os

from agents.llm.config import LLMConfig


class TestLLMConfig:
    """Validate LLM configuration loading."""

    def test_default_values(self):
        """Config with no env vars should have safe defaults."""
        # Clear any existing env vars
        env_backup = {}
        for key in (
            "LLM_API_KEY", "LLM_MODEL", "LLM_TEMPERATURE",
            "LLM_MAX_TOKENS", "LLM_PROVIDER",
        ):
            env_backup[key] = os.environ.pop(key, None)

        try:
            config = LLMConfig.from_env()
            assert config.provider == "mock"
            assert config.api_key == ""
            assert config.model == "mock-model"
            assert config.temperature == 0.2
            assert config.max_tokens == 4096
            # Mock provider is considered configured without API key
            assert config.is_configured is True
        finally:
            # Restore env vars
            for key, val in env_backup.items():
                if val is not None:
                    os.environ[key] = val

    def test_custom_values_from_env(self):
        """Config should read from environment variables."""
        os.environ["LLM_API_KEY"] = "test-key-12345"
        os.environ["LLM_MODEL"] = "gpt-3.5-turbo"
        os.environ["LLM_TEMPERATURE"] = "0.7"
        os.environ["LLM_MAX_TOKENS"] = "2048"
        os.environ["LLM_PROVIDER"] = "api"

        try:
            config = LLMConfig.from_env()
            assert config.provider == "api"
            assert config.api_key == "test-key-12345"
            assert config.model == "gpt-3.5-turbo"
            assert config.temperature == 0.7
            assert config.max_tokens == 2048
            assert config.is_configured is True
        finally:
            del os.environ["LLM_API_KEY"]
            del os.environ["LLM_MODEL"]
            del os.environ["LLM_TEMPERATURE"]
            del os.environ["LLM_MAX_TOKENS"]
            del os.environ["LLM_PROVIDER"]

    def test_is_configured_property(self):
        """is_configured depends on provider type."""
        # Mock provider is always configured
        config_mock = LLMConfig(provider="mock", api_key="")
        assert config_mock.is_configured is True

        # API provider needs a key
        config_no_key = LLMConfig(provider="api", api_key="")
        assert config_no_key.is_configured is False

        config_with_key = LLMConfig(provider="api", api_key="sk-some-key")
        assert config_with_key.is_configured is True

    def test_config_is_frozen(self):
        """Config should be immutable after creation."""
        config = LLMConfig(api_key="test")
        try:
            config.api_key = "changed"  # type: ignore
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass  # Expected: frozen dataclass
