import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class NATSConfig:
    urls: str
    stream_name: str
    max_age_seconds: int = 1800
    delete_existing: bool = False


def load_nats_config(stream_name: Optional[str] = None) -> NATSConfig:
    """Load NATS/JetStream configuration.

    Order of precedence:
    - Environment variables
    - services/common/nats.config.json (mounted via ConfigMap in k8s)
    - Sensible defaults
    """

    cfg_path = Path(__file__).with_name("nats.config.json")
    file_cfg: dict = {}
    if cfg_path.exists():
        try:
            with cfg_path.open("r", encoding="utf-8") as f:
                file_cfg = json.load(f)
        except Exception:
            file_cfg = {}

    urls = os.environ.get("NATS_URLS") or file_cfg.get("urls", "nats://nats:4222")

    # Prefer explicit seconds; fall back to minutes from config; then default 30m.
    max_age_seconds_str = os.environ.get("JS_MAX_AGE_SECONDS")
    if max_age_seconds_str is not None:
        max_age_seconds = int(max_age_seconds_str)
    else:
        max_age_seconds = int(
            file_cfg.get("max_age_seconds", file_cfg.get("retention_minutes", 30) * 60)
        )

    delete_existing_env = os.environ.get("JS_DELETE_EXISTING")
    if delete_existing_env is not None:
        delete_existing = delete_existing_env.lower() in ("1", "true", "yes")
    else:
        delete_existing = bool(file_cfg.get("delete_existing", False))

    stream = (
        stream_name
        or os.environ.get("JS_STREAM_NAME")
        or file_cfg.get("stream_name", "market_ticks")
    )

    return NATSConfig(
        urls=urls,
        stream_name=stream,
        max_age_seconds=max_age_seconds,
        delete_existing=delete_existing,
    )
