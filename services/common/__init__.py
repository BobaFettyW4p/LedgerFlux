"""
Common utilities and models for LedgerFlux services.

This module provides shared data models, stream management, and utility functions
used across all LedgerFlux services.
"""

# Import commonly used classes and functions for easier access
from .models import (
    Tick, Snapshot, TickFields, TradeData,
    SubscribeRequest, UnsubscribeRequest, PingRequest,
    SnapshotMessage, IncrMessage, RateLimitMessage, PongMessage, ErrorMessage,
    create_tick, create_snapshot
)
from .config import NATSConfig, load_nats_config
from .stream import NATSStreamManager
from .pg_store import PostgresSnapshotStore, SnapshotRecord
from .util import (
    shard_index, stable_hash, shard_product, validate_product_list, format_quantity
)
from .metrics import get_metrics_response, set_build_info

__all__ = [
    # Models
    'Tick', 'Snapshot', 'TickFields', 'TradeData',
    'SubscribeRequest', 'UnsubscribeRequest', 'PingRequest',
    'SnapshotMessage', 'IncrMessage', 'RateLimitMessage', 'PongMessage', 'ErrorMessage',
    'create_tick', 'create_snapshot',
    'load_nats_config',
    # Stream
    'NATSStreamManager', 'NATSConfig',
    # Storage
    'PostgresSnapshotStore', 'SnapshotRecord',
    # Utils
    'shard_index', 'stable_hash', 'shard_product', 'validate_product_list', 'format_quantity',
    # Metrics
    'get_metrics_response', 'set_build_info'
]
