from datetime import datetime
from typing import Dict, Optional, Any
from pydantic import BaseModel, Field, AliasChoices

"""canonical classes for all services, derived from pydantic.BaseModel"""


class TradeData(BaseModel):
    px: float = Field(description="Price")
    qty: float = Field(description="Quantity")


class TickFields(BaseModel):
    last_trade: Optional[TradeData] = Field(None, description="Last trade data")
    best_bid: Optional[TradeData] = Field(None, description="Best bid data")
    best_ask: Optional[TradeData] = Field(None, description="Best ask data")


class Tick(BaseModel):
    v: int = Field(1, description="Version")
    type: str = Field("tick", description="Message type")
    product: str = Field(description="Product symbol (e.g., BTC-USD)")
    seq: int = Field(description="Sequence number")
    ts_event: int = Field(description="Event timestamp (nanoseconds)")
    ts_ingest: int = Field(description="Ingest timestamp (nanoseconds)")
    fields: TickFields = Field(description="Market data fields")


class Snapshot(BaseModel):
    v: int = Field(1, description="Version")
    type: str = Field("snapshot", description="Message type")
    product: str = Field(description="Product symbol (e.g., BTC-USD)")
    seq: int = Field(description="Sequence number")
    ts_snapshot: int = Field(description="Snapshot timestamp (nanoseconds)")
    state: Dict[str, Any] = Field(description="Market state data")


class SubscribeRequest(BaseModel):
    # Accept both 'op' and 'operation' on input; serialize as 'op'
    operation: str = Field(
        "subscribe",
        description="Operation type",
        validation_alias=AliasChoices("operation", "op"),
        serialization_alias="op",
    )
    products: list[str] = Field(description="List of products to subscribe to")
    from_seq: Optional[Dict[str, int]] = Field(
        None, description="Starting sequence per product"
    )
    want_snapshot: bool = Field(True, description="Whether to send initial snapshot")


class UnsubscribeRequest(BaseModel):
    operation: str = Field(
        "unsubscribe",
        description="Operation type",
        validation_alias=AliasChoices("operation", "op"),
        serialization_alias="op",
    )
    products: list[str] = Field(description="List of products to unsubscribe from")


class PingRequest(BaseModel):
    operation: str = Field(
        "ping",
        description="Operation type",
        validation_alias=AliasChoices("operation", "op"),
        serialization_alias="op",
    )
    timestamp: int = Field(
        description="Timestamp",
        validation_alias=AliasChoices("timestamp", "t"),
        serialization_alias="t",
    )


class SnapshotMessage(BaseModel):
    operation: str = Field(
        "snapshot",
        description="Operation type",
        validation_alias=AliasChoices("operation", "op"),
        serialization_alias="op",
    )
    data: Snapshot = Field(description="Snapshot data")


class IncrMessage(BaseModel):
    operation: str = Field(
        "incr",
        description="Operation type",
        validation_alias=AliasChoices("operation", "op"),
        serialization_alias="op",
    )
    data: Tick = Field(description="Tick data")


class RateLimitMessage(BaseModel):
    operation: str = Field(
        "rate_limit",
        description="Operation type",
        validation_alias=AliasChoices("operation", "op"),
        serialization_alias="op",
    )
    retry_ms: int = Field(description="Retry delay in milliseconds")


class PongMessage(BaseModel):
    operation: str = Field(
        "pong",
        description="Operation type",
        validation_alias=AliasChoices("operation", "op"),
        serialization_alias="op",
    )
    timestamp: int = Field(
        description="Timestamp from ping",
        validation_alias=AliasChoices("timestamp", "t"),
        serialization_alias="t",
    )


class ErrorMessage(BaseModel):
    operation: str = Field(
        "error",
        description="Operation type",
        validation_alias=AliasChoices("operation", "op"),
        serialization_alias="op",
    )
    code: str = Field(description="Error code")
    msg: str = Field(description="Error message")


"""helper functions for creating ticks and snapshots"""


def create_tick(product: str, seq: int, ts_event: int, fields: TickFields) -> Tick:
    ts_ingest = int(datetime.now().timestamp() * 1_000_000_000)
    return Tick(
        product=product, seq=seq, ts_event=ts_event, ts_ingest=ts_ingest, fields=fields
    )


def create_snapshot(
    product: str, seq: int, ts_snapshot: int, state: Dict[str, Any]
) -> Snapshot:
    return Snapshot(product=product, seq=seq, ts_snapshot=ts_snapshot, state=state)
