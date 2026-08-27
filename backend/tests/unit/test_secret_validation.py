"""
Unit tests for production secret fail-fast validation (config.py).
"""
import pytest

from config import Settings, _validate_production_secrets


def _make(**overrides) -> Settings:
    """Build a Settings instance bypassing .env file interference."""
    return Settings(
        secret_key=overrides.pop("secret_key", None) or "a" * 32,
        environment=overrides.pop("environment", "production"),
        _env_file=None,  # type: ignore[arg-type]
        **overrides,
    )


class TestProductionSecretValidation:
    def test_production_with_good_secret_passes(self):
        s = _make(secret_key="x" * 64)
        _validate_production_secrets(s)  # must not raise

    def test_production_short_secret_raises(self):
        s = _make(secret_key="tooshort")
        with pytest.raises(RuntimeError, match="shorter than 32"):
            _validate_production_secrets(s)

    def test_production_default_placeholder_raises(self):
        s = _make(secret_key="change-me-in-production-use-32-random-bytes")
        with pytest.raises(RuntimeError, match="placeholder"):
            _validate_production_secrets(s)

    def test_production_env_example_placeholder_raises(self):
        s = _make(secret_key="your-secret-key-here-minimum-32-characters-change-this")
        with pytest.raises(RuntimeError, match="placeholder"):
            _validate_production_secrets(s)

    def test_development_allows_defaults(self):
        s = _make(environment="development", secret_key="change-me-in-production-use-32-random-bytes")
        _validate_production_secrets(s)  # must not raise

    def test_environment_case_insensitive(self):
        s = _make(environment="PRODUCTION", secret_key="short")
        with pytest.raises(RuntimeError):
            _validate_production_secrets(s)
