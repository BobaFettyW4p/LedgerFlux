from datetime import datetime
from typing import Dict, Optional, Any
from pydantic import BaseModel, Field, AliasChoices, ConfigDict

"""canonical classes for all services, derived from pydantic.BaseModel"""


class TradeData(BaseModel):
    px: float = Field(description="Price")
    qty: float = Field(description="Quantity")


class TickFields(BaseModel):
    last_trade: Optional[TradeData] = Field(default=None, description="Last trade data")
    best_bid: Optional[TradeData] = Field(default=None, description="Best bid data")
    best_ask: Optional[TradeData] = Field(default=None, description="Best ask data")


class Tick(BaseModel):
    v: int = Field(default=1, description="Version")
    type: str = Field(default="tick", description="Message type")
    product: str = Field(description="Product symbol (e.g., BTC-USD)")
    seq: int = Field(description="Sequence number")
    ts_event: int = Field(description="Event timestamp (nanoseconds)")
    ts_ingest: int = Field(description="Ingest timestamp (nanoseconds)")
    fields: TickFields = Field(description="Market data fields")


class Snapshot(BaseModel):
    v: int = Field(default=1, description="Version")
    type: str = Field(default="snapshot", description="Message type")
    product: str = Field(description="Product symbol (e.g., BTC-USD)")
    seq: int = Field(description="Sequence number")
    ts_snapshot: int = Field(description="Snapshot timestamp (nanoseconds)")
    state: Dict[str, Any] = Field(description="Market state data")


class SubscribeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    op: str = Field(
        default="subscribe",
        description="Operation type",
        validation_alias=AliasChoices("op", "operation"),
    )
    products: list[str] = Field(description="List of products to subscribe to")
    from_seq: Optional[Dict[str, int]] = Field(
        default=None, description="Starting sequence per product"
    )
    want_snapshot: bool = Field(
        default=True, description="Whether to send initial snapshot"
    )


class UnsubscribeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    op: str = Field(
        default="unsubscribe",
        description="Operation type",
        validation_alias=AliasChoices("op", "operation"),
    )
    products: list[str] = Field(description="List of products to unsubscribe from")


class PingRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    op: str = Field(
        default="ping",
        description="Operation type",
        validation_alias=AliasChoices("op", "operation"),
    )
    t: int = Field(
        description="Timestamp (seconds since epoch)",
        validation_alias=AliasChoices("t", "timestamp"),
    )


class SnapshotMessage(BaseModel):
    op: str = Field(
        default="snapshot",
        description="Operation type",
        validation_alias=AliasChoices("op", "operation"),
    )
    data: Snapshot = Field(description="Snapshot data")


class IncrMessage(BaseModel):
    op: str = Field(
        default="incr",
        description="Operation type",
        validation_alias=AliasChoices("op", "operation"),
    )
    data: Tick = Field(description="Tick data")


class RateLimitMessage(BaseModel):
    op: str = Field(
        default="rate_limit",
        description="Operation type",
        validation_alias=AliasChoices("op", "operation"),
    )
    retry_ms: int = Field(description="Retry delay in milliseconds")


class PongMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    op: str = Field(
        default="pong",
        description="Operation type",
        validation_alias=AliasChoices("op", "operation"),
    )
    t: int = Field(
        description="Timestamp from ping",
        validation_alias=AliasChoices("t", "timestamp"),
    )


class ErrorMessage(BaseModel):
    op: str = Field(
        default="error",
        description="Operation type",
        validation_alias=AliasChoices("op", "operation"),
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
