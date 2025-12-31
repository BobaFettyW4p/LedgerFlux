"""Tests for Pydantic models in services/common/models.py"""
import pytest
from pydantic import ValidationError
from datetime import datetime
from services.common.models import (
    TradeData,
    TickFields,
    Tick,
    Snapshot,
    SubscribeRequest,
    UnsubscribeRequest,
    PingRequest,
    SnapshotMessage,
    IncrMessage,
    RateLimitMessage,
    PongMessage,
    ErrorMessage,
    create_tick,
    create_snapshot
)


class TestTradeData:
    """Test TradeData model."""

    def test_trade_data_valid(self):
        """Should create valid TradeData."""
        trade = TradeData(px=50000.0, qty=1.5)
        assert trade.px == 50000.0
        assert trade.qty == 1.5

    def test_trade_data_zero_price(self):
        """Should allow zero price (validation happens elsewhere)."""
        trade = TradeData(px=0.0, qty=1.0)
        assert trade.px == 0.0

    def test_trade_data_missing_fields(self):
        """Should require px and qty fields."""
        with pytest.raises(ValidationError):
            TradeData(px=50000.0)  # Missing qty

        with pytest.raises(ValidationError):
            TradeData(qty=1.0)  # Missing px


class TestTickFields:
    """Test TickFields model."""

    def test_tick_fields_all_present(self):
        """Should accept all fields."""
        fields = TickFields(
            last_trade=TradeData(px=50000.0, qty=0.5),
            best_bid=TradeData(px=49995.0, qty=1.2),
            best_ask=TradeData(px=50005.0, qty=0.8)
        )
        assert fields.last_trade.px == 50000.0
        assert fields.best_bid.px == 49995.0
        assert fields.best_ask.px == 50005.0

    def test_tick_fields_partial(self):
        """Should allow partial fields (all optional)."""
        fields = TickFields(last_trade=TradeData(px=50000.0, qty=0.5))
        assert fields.last_trade is not None
        assert fields.best_bid is None
        assert fields.best_ask is None

    def test_tick_fields_empty(self):
        """Should allow empty fields."""
        fields = TickFields()
        assert fields.last_trade is None
        assert fields.best_bid is None
        assert fields.best_ask is None


class TestTick:
    """Test Tick model."""

    def test_tick_valid(self, sample_tick_data):
        """Should create valid Tick."""
        tick = Tick.model_validate(sample_tick_data)
        assert tick.v == 1
        assert tick.type == "tick"
        assert tick.product == "BTC-USD"
        assert tick.seq == 12345
        assert tick.ts_event == 1609459200000000000
        assert tick.ts_ingest == 1609459200100000000
        assert tick.fields.last_trade.px == 50000.0

    def test_tick_defaults(self):
        """Should use default values for v and type."""
        tick = Tick(
            product="ETH-USD",
            seq=100,
            ts_event=1000000000,
            ts_ingest=1000000001,
            fields=TickFields()
        )
        assert tick.v == 1
        assert tick.type == "tick"

    def test_tick_missing_required_fields(self):
        """Should require product, seq, ts_event, ts_ingest, fields."""
        with pytest.raises(ValidationError):
            Tick(product="BTC-USD", seq=100)  # Missing timestamps and fields


class TestSnapshot:
    """Test Snapshot model."""

    def test_snapshot_valid(self):
        """Should create valid Snapshot."""
        snapshot = Snapshot(
            product="BTC-USD",
            seq=12345,
            ts_snapshot=1609459200000000000,
            state={"price": 50000.0}
        )
        assert snapshot.v == 1
        assert snapshot.type == "snapshot"
        assert snapshot.product == "BTC-USD"
        assert snapshot.seq == 12345
        assert snapshot.state["price"] == 50000.0

    def test_snapshot_empty_state(self):
        """Should allow empty state dict."""
        snapshot = Snapshot(
            product="ETH-USD",
            seq=100,
            ts_snapshot=1000000000,
            state={}
        )
        assert snapshot.state == {}


class TestSubscribeRequest:
    """Test SubscribeRequest model."""

    def test_subscribe_request_valid(self):
        """Should create valid SubscribeRequest."""
        req = SubscribeRequest(
            products=["BTC-USD", "ETH-USD"],
            want_snapshot=True
        )
        assert req.op == "subscribe"
        assert req.products == ["BTC-USD", "ETH-USD"]
        assert req.want_snapshot is True

    def test_subscribe_request_with_from_seq(self):
        """Should accept from_seq parameter."""
        req = SubscribeRequest(
            products=["BTC-USD"],
            from_seq={"BTC-USD": 12345},
            want_snapshot=False
        )
        assert req.from_seq == {"BTC-USD": 12345}
        assert req.want_snapshot is False

    def test_subscribe_request_alias_operation(self):
        """Should accept 'operation' alias for 'op'."""
        req = SubscribeRequest.model_validate({
            "operation": "subscribe",
            "products": ["BTC-USD"]
        })
        assert req.op == "subscribe"

    def test_subscribe_request_defaults(self):
        """Should use default values."""
        req = SubscribeRequest(products=["BTC-USD"])
        assert req.op == "subscribe"
        assert req.want_snapshot is True
        assert req.from_seq is None


class TestUnsubscribeRequest:
    """Test UnsubscribeRequest model."""

    def test_unsubscribe_request_valid(self):
        """Should create valid UnsubscribeRequest."""
        req = UnsubscribeRequest(products=["BTC-USD", "ETH-USD"])
        assert req.op == "unsubscribe"
        assert req.products == ["BTC-USD", "ETH-USD"]

    def test_unsubscribe_request_alias(self):
        """Should accept 'operation' alias for 'op'."""
        req = UnsubscribeRequest.model_validate({
            "operation": "unsubscribe",
            "products": ["ETH-USD"]
        })
        assert req.op == "unsubscribe"


class TestPingRequest:
    """Test PingRequest model."""

    def test_ping_request_valid(self):
        """Should create valid PingRequest."""
        req = PingRequest(t=1609459200)
        assert req.op == "ping"
        assert req.t == 1609459200

    def test_ping_request_alias_operation(self):
        """Should accept 'operation' alias for 'op'."""
        req = PingRequest.model_validate({
            "operation": "ping",
            "t": 1234567890
        })
        assert req.op == "ping"

    def test_ping_request_alias_timestamp(self):
        """Should accept 'timestamp' alias for 't'."""
        req = PingRequest.model_validate({
            "op": "ping",
            "timestamp": 1234567890
        })
        assert req.t == 1234567890


class TestMessageModels:
    """Test message wrapper models."""

    def test_snapshot_message(self, sample_tick_data):
        """Should create valid SnapshotMessage."""
        snapshot = Snapshot(
            product="BTC-USD",
            seq=12345,
            ts_snapshot=1609459200000000000,
            state={"price": 50000.0}
        )
        msg = SnapshotMessage(data=snapshot)
        assert msg.op == "snapshot"
        assert msg.data.product == "BTC-USD"

    def test_incr_message(self, sample_tick):
        """Should create valid IncrMessage."""
        msg = IncrMessage(data=sample_tick)
        assert msg.op == "incr"
        assert msg.data.product == "BTC-USD"

    def test_rate_limit_message(self):
        """Should create valid RateLimitMessage."""
        msg = RateLimitMessage(retry_ms=100)
        assert msg.op == "rate_limit"
        assert msg.retry_ms == 100

    def test_pong_message(self):
        """Should create valid PongMessage."""
        msg = PongMessage(t=1609459200)
        assert msg.op == "pong"
        assert msg.t == 1609459200

    def test_pong_message_alias(self):
        """Should accept 'timestamp' alias for 't'."""
        msg = PongMessage.model_validate({
            "op": "pong",
            "timestamp": 1234567890
        })
        assert msg.t == 1234567890

    def test_error_message(self):
        """Should create valid ErrorMessage."""
        msg = ErrorMessage(code="INVALID_OP", msg="Unknown operation")
        assert msg.op == "error"
        assert msg.code == "INVALID_OP"
        assert msg.msg == "Unknown operation"


class TestHelperFunctions:
    """Test helper functions for creating ticks and snapshots."""

    def test_create_tick(self):
        """Should create Tick with auto-generated ts_ingest."""
        fields = TickFields(last_trade=TradeData(px=50000.0, qty=1.0))
        tick = create_tick(
            product="BTC-USD",
            seq=12345,
            ts_event=1609459200000000000,
            fields=fields
        )

        assert tick.product == "BTC-USD"
        assert tick.seq == 12345
        assert tick.ts_event == 1609459200000000000
        assert tick.ts_ingest > tick.ts_event  # Should be current time
        assert tick.fields.last_trade.px == 50000.0

    def test_create_snapshot(self):
        """Should create Snapshot."""
        state = {"price": 50000.0, "volume": 100.0}
        snapshot = create_snapshot(
            product="ETH-USD",
            seq=100,
            ts_snapshot=1609459200000000000,
            state=state
        )

        assert snapshot.product == "ETH-USD"
        assert snapshot.seq == 100
        assert snapshot.ts_snapshot == 1609459200000000000
        assert snapshot.state == state
        assert snapshot.v == 1
        assert snapshot.type == "snapshot"
