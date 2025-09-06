"""
Common data models for the market data fan-out system.

These models define the canonical data formats used throughout the system.
"""

from datetime import datetime
from typing import Dict, Optional, Any
from pydantic import BaseModel, Field


class TradeData(BaseModel):
    """Trade price and quantity data"""
    px: float = Field(description="Price")
    qty: float = Field(description="Quantity")


class TickFields(BaseModel):
    """Market data fields for a tick"""
    last_trade: Optional[TradeData] = Field(None, description="Last trade data")
    best_bid: Optional[TradeData] = Field(None, description="Best bid data")
    best_ask: Optional[TradeData] = Field(None, description="Best ask data")


class Tick(BaseModel):
    """Canonical tick data format"""
    v: int = Field(1, description="Version")
    type: str = Field("tick", description="Message type")
    product: str = Field(description="Product symbol (e.g., BTC-USD)")
    seq: int = Field(description="Sequence number")
    ts_event: int = Field(description="Event timestamp (nanoseconds)")
    ts_ingest: int = Field(description="Ingest timestamp (nanoseconds)")
    fields: TickFields = Field(description="Market data fields")


class Snapshot(BaseModel):
    """Canonical snapshot data format"""
    v: int = Field(1, description="Version")
    type: str = Field("snapshot", description="Message type")
    product: str = Field(description="Product symbol (e.g., BTC-USD)")
    seq: int = Field(description="Sequence number")
    ts_snapshot: int = Field(description="Snapshot timestamp (nanoseconds)")
    state: Dict[str, Any] = Field(description="Market state data")


# WebSocket Protocol Models
class SubscribeRequest(BaseModel):
    """Client subscription request"""
    op: str = Field("subscribe", description="Operation type")
    products: list[str] = Field(description="List of products to subscribe to")
    from_seq: Optional[Dict[str, int]] = Field(None, description="Starting sequence per product")
    want_snapshot: bool = Field(True, description="Whether to send initial snapshot")


class UnsubscribeRequest(BaseModel):
    """Client unsubscription request"""
    op: str = Field("unsubscribe", description="Operation type")
    products: list[str] = Field(description="List of products to unsubscribe from")


class PingRequest(BaseModel):
    """Client ping request"""
    op: str = Field("ping", description="Operation type")
    t: int = Field(description="Timestamp")


class SnapshotMessage(BaseModel):
    """Server snapshot message"""
    op: str = Field("snapshot", description="Operation type")
    data: Snapshot = Field(description="Snapshot data")


class IncrMessage(BaseModel):
    """Server incremental update message"""
    op: str = Field("incr", description="Operation type")
    data: Tick = Field(description="Tick data")


class RateLimitMessage(BaseModel):
    """Server rate limit message"""
    op: str = Field("rate_limit", description="Operation type")
    retry_ms: int = Field(description="Retry delay in milliseconds")


class PongMessage(BaseModel):
    """Server pong response"""
    op: str = Field("pong", description="Operation type")
    t: int = Field(description="Timestamp from ping")


class ErrorMessage(BaseModel):
    """Server error message"""
    op: str = Field("error", description="Operation type")
    code: str = Field(description="Error code")
    msg: str = Field(description="Error message")


def create_tick(product: str, seq: int, ts_event: int, fields: TickFields) -> Tick:
    """Create a Tick with current ingest timestamp"""
    ts_ingest = int(datetime.now().timestamp() * 1_000_000_000)
    return Tick(
        product=product,
        seq=seq,
        ts_event=ts_event,
        ts_ingest=ts_ingest,
        fields=fields
    )


def create_snapshot(product: str, seq: int, ts_snapshot: int, state: Dict[str, Any]) -> Snapshot:
    """Create a Snapshot"""
    return Snapshot(
        product=product,
        seq=seq,
        ts_snapshot=ts_snapshot,
        state=state
    )
