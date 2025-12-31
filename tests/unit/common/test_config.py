"""Tests for configuration loading in services/common/config.py"""
import pytest
import json
import os
import tempfile
from pathlib import Path
from datetime import timedelta
from services.common.config import (
    NATSConfig,
    load_nats_config,
    _parse_bool
)


class TestParseBool:
    """Test _parse_bool helper function."""

    def test_parse_bool_true_strings(self):
        """Should parse various true string values."""
        assert _parse_bool("true") is True
        assert _parse_bool("True") is True
        assert _parse_bool("TRUE") is True
        assert _parse_bool("1") is True
        assert _parse_bool("yes") is True
        assert _parse_bool("YES") is True
        assert _parse_bool("y") is True
        assert _parse_bool("Y") is True
        assert _parse_bool("on") is True
        assert _parse_bool("ON") is True

    def test_parse_bool_false_strings(self):
        """Should parse various false string values."""
        assert _parse_bool("false") is False
        assert _parse_bool("False") is False
        assert _parse_bool("0") is False
        assert _parse_bool("no") is False
        assert _parse_bool("off") is False
        assert _parse_bool("") is False
        assert _parse_bool("random") is False

    def test_parse_bool_native_bool(self):
        """Should pass through native boolean values."""
        assert _parse_bool(True) is True
        assert _parse_bool(False) is False

    def test_parse_bool_numeric(self):
        """Should convert numeric values."""
        assert _parse_bool(1) is True
        assert _parse_bool(1.5) is True
        assert _parse_bool(0) is False
        assert _parse_bool(0.0) is False

    def test_parse_bool_none(self):
        """Should use default for None."""
        assert _parse_bool(None) is False
        assert _parse_bool(None, default=True) is True

    def test_parse_bool_invalid_type(self):
        """Should use default for invalid types."""
        assert _parse_bool([]) is False
        assert _parse_bool({}) is False
        assert _parse_bool([], default=True) is True


class TestNATSConfig:
    """Test NATSConfig dataclass."""

    def test_nats_config_creation(self):
        """Should create NATSConfig with all fields."""
        config = NATSConfig(
            urls="nats://localhost:4222",
            stream_name="test_stream",
            subject_prefix="test.subject",
            retention_minutes=30,
            max_age_seconds=1800,
            delete_existing=True
        )

        assert config.urls == "nats://localhost:4222"
        assert config.stream_name == "test_stream"
        assert config.subject_prefix == "test.subject"
        assert config.retention_minutes == 30
        assert config.max_age_seconds == 1800
        assert config.delete_existing is True

    def test_nats_config_defaults(self):
        """Should use default for delete_existing."""
        config = NATSConfig(
            urls="nats://localhost:4222",
            stream_name="test_stream",
            subject_prefix="test.subject",
            retention_minutes=30,
            max_age_seconds=1800
        )

        assert config.delete_existing is False

    def test_max_age_timedelta_positive(self):
        """Should convert positive max_age_seconds to timedelta."""
        config = NATSConfig(
            urls="nats://localhost:4222",
            stream_name="test_stream",
            subject_prefix="test.subject",
            retention_minutes=30,
            max_age_seconds=1800
        )

        assert config.max_age_timedelta == timedelta(seconds=1800)

    def test_max_age_timedelta_zero(self):
        """Should return None for zero max_age_seconds."""
        config = NATSConfig(
            urls="nats://localhost:4222",
            stream_name="test_stream",
            subject_prefix="test.subject",
            retention_minutes=30,
            max_age_seconds=0
        )

        assert config.max_age_timedelta is None

    def test_max_age_timedelta_negative(self):
        """Should return None for negative max_age_seconds."""
        config = NATSConfig(
            urls="nats://localhost:4222",
            stream_name="test_stream",
            subject_prefix="test.subject",
            retention_minutes=30,
            max_age_seconds=-100
        )

        assert config.max_age_timedelta is None


class TestLoadNATSConfig:
    """Test load_nats_config function."""

    def test_load_config_defaults(self, monkeypatch):
        """Should use defaults when no config file or env vars."""
        # Clear environment variables
        monkeypatch.delenv("NATS_URLS", raising=False)
        monkeypatch.delenv("JS_STREAM_NAME", raising=False)
        monkeypatch.delenv("JS_SUBJECT_PREFIX", raising=False)
        monkeypatch.delenv("JS_RETENTION_MINUTES", raising=False)
        monkeypatch.delenv("JS_MAX_AGE_SECONDS", raising=False)
        monkeypatch.delenv("NATS_DELETE_EXISTING", raising=False)

        # Use non-existent config path
        config = load_nats_config(config_path=Path("/tmp/nonexistent.json"))

        assert config.urls == "nats://localhost:4222"
        assert config.stream_name == "market_ticks"
        assert config.subject_prefix == "market.ticks"
        assert config.retention_minutes == 30
        assert config.max_age_seconds == 1800  # 30 * 60
        assert config.delete_existing is False

    def test_load_config_from_file(self, monkeypatch):
        """Should load config from JSON file."""
        # Clear environment variables
        monkeypatch.delenv("NATS_URLS", raising=False)
        monkeypatch.delenv("JS_STREAM_NAME", raising=False)

        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_data = {
                "urls": "nats://custom:4222",
                "stream_name": "custom_stream",
                "subject_prefix": "custom.subject",
                "retention_minutes": 60,
                "max_age_seconds": 3600,
                "delete_existing": True
            }
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            config = load_nats_config(config_path=config_path)

            assert config.urls == "nats://custom:4222"
            assert config.stream_name == "custom_stream"
            assert config.subject_prefix == "custom.subject"
            assert config.retention_minutes == 60
            assert config.max_age_seconds == 3600
            assert config.delete_existing is True
        finally:
            config_path.unlink()

    def test_load_config_env_override(self, monkeypatch):
        """Should prioritize environment variables over config file."""
        # Set environment variables
        monkeypatch.setenv("NATS_URLS", "nats://env:4222")
        monkeypatch.setenv("JS_STREAM_NAME", "env_stream")
        monkeypatch.setenv("JS_RETENTION_MINUTES", "120")
        monkeypatch.setenv("NATS_DELETE_EXISTING", "true")

        # Create config file with different values
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_data = {
                "urls": "nats://file:4222",
                "stream_name": "file_stream",
                "retention_minutes": 30
            }
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            config = load_nats_config(config_path=config_path)

            # Environment variables should win
            assert config.urls == "nats://env:4222"
            assert config.stream_name == "env_stream"
            assert config.retention_minutes == 120
            assert config.delete_existing is True
        finally:
            config_path.unlink()

    def test_load_config_argument_override(self, monkeypatch):
        """Should prioritize function arguments over everything."""
        monkeypatch.setenv("JS_STREAM_NAME", "env_stream")
        monkeypatch.setenv("JS_SUBJECT_PREFIX", "env.subject")

        config = load_nats_config(
            stream_name="arg_stream",
            subject_prefix="arg.subject",
            config_path=Path("/tmp/nonexistent.json")
        )

        # Arguments should win
        assert config.stream_name == "arg_stream"
        assert config.subject_prefix == "arg.subject"

    def test_load_config_invalid_json(self):
        """Should raise ValueError on invalid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json }")
            config_path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Invalid JSON"):
                load_nats_config(config_path=config_path)
        finally:
            config_path.unlink()

    def test_load_config_negative_retention(self, monkeypatch):
        """Should raise ValueError on negative retention_minutes."""
        monkeypatch.setenv("JS_RETENTION_MINUTES", "-10")

        with pytest.raises(ValueError, match="must be positive"):
            load_nats_config(config_path=Path("/tmp/nonexistent.json"))

    def test_load_config_zero_retention(self, monkeypatch):
        """Should raise ValueError on zero retention_minutes."""
        monkeypatch.setenv("JS_RETENTION_MINUTES", "0")

        with pytest.raises(ValueError, match="must be positive"):
            load_nats_config(config_path=Path("/tmp/nonexistent.json"))

    def test_load_config_negative_max_age(self, monkeypatch):
        """Should raise ValueError on negative max_age_seconds."""
        monkeypatch.setenv("JS_MAX_AGE_SECONDS", "-100")

        with pytest.raises(ValueError, match="must be positive"):
            load_nats_config(config_path=Path("/tmp/nonexistent.json"))

    def test_load_config_stream_name_with_dot(self, monkeypatch):
        """Should raise ValueError if stream_name contains a dot."""
        monkeypatch.setenv("JS_STREAM_NAME", "invalid.stream")

        with pytest.raises(ValueError, match="cannot contain '.'"):
            load_nats_config(config_path=Path("/tmp/nonexistent.json"))
