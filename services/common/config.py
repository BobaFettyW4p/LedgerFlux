"""
Configuration helpers for shared infrastructure clients.

Provides a small `NATSConfig` dataclass plus loader that reads defaults from
`nats.config.json` and allows environment variable overrides. This keeps the
services aligned on how they talk to JetStream without duplicating parsing
logic across ingestor/normalizer/gateway.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_CONFIG_PATH = Path(__file__).with_name("nats.config.json")


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if not isinstance(value, str):
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class NATSConfig:
    urls: str
    stream_name: str
    subject_prefix: str
    retention_minutes: int
    max_age_seconds: int
    delete_existing: bool = False

    @property
    def max_age_timedelta(self) -> Optional[timedelta]:
        if self.max_age_seconds <= 0:
            return None
        return timedelta(seconds=self.max_age_seconds)


def load_nats_config(
    stream_name: Optional[str] = None,
    subject_prefix: Optional[str] = None,
    config_path: Optional[Path] = None,
) -> NATSConfig:
    """
    Load NATS/JetStream configuration shared across services.

    Precedence:
    1. Explicit `stream_name` argument.
    2. Environment variables: NATS_URLS, JS_STREAM_NAME, JS_RETENTION_MINUTES, JS_MAX_AGE_SECONDS, NATS_DELETE_EXISTING.
    3. JSON config file (default: services/common/nats.config.json).
    4. Hardcoded defaults.
    """

    path = config_path or DEFAULT_CONFIG_PATH
    file_config: Dict[str, Any] = {}
    if path.exists():
        try:
            file_config = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    urls = os.getenv("NATS_URLS", file_config.get("urls", "nats://localhost:4222"))

    retention_minutes = int(
        os.getenv(
            "JS_RETENTION_MINUTES",
            file_config.get("retention_minutes", 30),
        )
    )
    if retention_minutes <= 0:
        raise ValueError("JS_RETENTION_MINUTES must be positive")

    max_age_seconds = int(
        os.getenv(
            "JS_MAX_AGE_SECONDS",
            file_config.get("max_age_seconds", retention_minutes * 60),
        )
    )
    if max_age_seconds <= 0:
        raise ValueError("JS_MAX_AGE_SECONDS must be positive")

    resolved_stream_name = (
        stream_name
        or os.getenv("JS_STREAM_NAME")
        or file_config.get("stream_name")
        or "market_ticks"
    )
    if "." in resolved_stream_name:
        raise ValueError(
            f"Invalid JetStream name '{resolved_stream_name}'. "
            "Stream names cannot contain '.'. Consider using JS_SUBJECT_PREFIX for subjects."
        )

    resolved_subject_prefix = (
        subject_prefix
        or os.getenv("JS_SUBJECT_PREFIX")
        or file_config.get("subject_prefix")
        or "market.ticks"
    )

    delete_existing = _parse_bool(
        os.getenv("NATS_DELETE_EXISTING", file_config.get("delete_existing", False))
    )

    return NATSConfig(
        urls=str(urls),
        stream_name=str(resolved_stream_name),
        subject_prefix=str(resolved_subject_prefix),
        retention_minutes=int(retention_minutes),
        max_age_seconds=int(max_age_seconds),
        delete_existing=delete_existing,
    )
