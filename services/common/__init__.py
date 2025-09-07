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
from .stream import NATSStreamManager, NATSConfig
from .util import (
    stable_hash, shard_product, validate_product_list, format_price, format_quantity
)

__all__ = [
    # Models
    'Tick', 'Snapshot', 'TickFields', 'TradeData',
    'SubscribeRequest', 'UnsubscribeRequest', 'PingRequest',
    'SnapshotMessage', 'IncrMessage', 'RateLimitMessage', 'PongMessage', 'ErrorMessage',
    'create_tick', 'create_snapshot',
    # Stream
    'NATSStreamManager', 'NATSConfig',
    # Utils
    'stable_hash', 'shard_product', 'validate_product_list', 'format_price', 'format_quantity'
]
