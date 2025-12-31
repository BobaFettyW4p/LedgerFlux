"""Tests for Coinbase data transformation in services/ingestor/app.py"""
import pytest
from datetime import datetime, timezone
from services.ingestor.app import transform_coinbase_ticker
from services.common.models import Tick


class TestCoinbaseTransform:
    """Test Coinbase ticker message transformation."""

    def test_complete_ticker_transform(self, sample_coinbase_ticker):
        """Should transform complete ticker to Tick."""
        tick = transform_coinbase_ticker(sample_coinbase_ticker)

        assert isinstance(tick, Tick)
        assert tick.product == "BTC-USD"
        assert tick.seq == 12345
        assert tick.fields.last_trade.px == 50000.0
        assert tick.fields.last_trade.qty == 0.5
        assert tick.fields.best_bid.px == 49995.0
        assert tick.fields.best_bid.qty == 1.2
        assert tick.fields.best_ask.px == 50005.0
        assert tick.fields.best_ask.qty == 0.8

    def test_partial_ticker_no_bid_ask(self):
        """Should handle ticker without bid/ask data."""
        partial_ticker = {
            "type": "ticker",
            "sequence": 100,
            "product_id": "ETH-USD",
            "price": "3000.00",
            "last_size": "2.5",
            "time": "2021-01-01T00:00:00.000000Z"
        }

        tick = transform_coinbase_ticker(partial_ticker)

        assert tick.product == "ETH-USD"
        assert tick.seq == 100
        assert tick.fields.last_trade is not None
        assert tick.fields.last_trade.px == 3000.0
        assert tick.fields.last_trade.qty == 2.5
        assert tick.fields.best_bid is None
        assert tick.fields.best_ask is None

    def test_partial_ticker_only_bid(self):
        """Should handle ticker with only bid data."""
        ticker = {
            "type": "ticker",
            "sequence": 200,
            "product_id": "SOL-USD",
            "price": "100.00",
            "last_size": "10.0",
            "best_bid": "99.50",
            "best_bid_size": "50.0",
            "time": "2021-01-01T00:00:00.000000Z"
        }

        tick = transform_coinbase_ticker(ticker)

        assert tick.fields.last_trade is not None
        assert tick.fields.best_bid is not None
        assert tick.fields.best_bid.px == 99.50
        assert tick.fields.best_bid.qty == 50.0
        assert tick.fields.best_ask is None

    def test_partial_ticker_only_ask(self):
        """Should handle ticker with only ask data."""
        ticker = {
            "type": "ticker",
            "sequence": 300,
            "product_id": "ADA-USD",
            "price": "1.50",
            "last_size": "1000.0",
            "best_ask": "1.51",
            "best_ask_size": "2000.0",
            "time": "2021-01-01T00:00:00.000000Z"
        }

        tick = transform_coinbase_ticker(ticker)

        assert tick.fields.last_trade is not None
        assert tick.fields.best_bid is None
        assert tick.fields.best_ask is not None
        assert tick.fields.best_ask.px == 1.51
        assert tick.fields.best_ask.qty == 2000.0

    def test_timestamp_parsing(self):
        """Should correctly parse ISO timestamp."""
        ticker = {
            "type": "ticker",
            "sequence": 1,
            "product_id": "BTC-USD",
            "price": "50000.00",
            "last_size": "0.1",
            "time": "2021-01-01T12:30:45.123456Z"
        }

        tick = transform_coinbase_ticker(ticker)

        # ts_event should be in nanoseconds
        assert tick.ts_event > 0
        # Convert back to verify
        expected_dt = datetime(2021, 1, 1, 12, 30, 45, 123456, tzinfo=timezone.utc)
        expected_ns = int(expected_dt.timestamp() * 1_000_000_000)
        assert tick.ts_event == expected_ns

    def test_ts_ingest_set(self):
        """Should set ts_ingest to current time."""
        ticker = {
            "type": "ticker",
            "sequence": 1,
            "product_id": "BTC-USD",
            "price": "50000.00",
            "last_size": "0.1",
            "time": "2021-01-01T00:00:00.000000Z"
        }

        tick = transform_coinbase_ticker(ticker)

        # ts_ingest should be different from ts_event (current time)
        assert tick.ts_ingest != tick.ts_event
        assert tick.ts_ingest > tick.ts_event

    def test_product_id_preserved(self):
        """Should preserve product_id exactly."""
        ticker = {
            "type": "ticker",
            "sequence": 1,
            "product_id": "ETH-USD",
            "price": "3000.00",
            "last_size": "1.0",
            "time": "2021-01-01T00:00:00.000000Z"
        }

        tick = transform_coinbase_ticker(ticker)
        assert tick.product == "ETH-USD"

    def test_sequence_preserved(self):
        """Should preserve sequence number."""
        ticker = {
            "type": "ticker",
            "sequence": 999999,
            "product_id": "BTC-USD",
            "price": "50000.00",
            "last_size": "0.1",
            "time": "2021-01-01T00:00:00.000000Z"
        }

        tick = transform_coinbase_ticker(ticker)
        assert tick.seq == 999999

    def test_float_conversion(self):
        """Should convert string prices to floats."""
        ticker = {
            "type": "ticker",
            "sequence": 1,
            "product_id": "BTC-USD",
            "price": "50000.123456",
            "last_size": "0.987654",
            "best_bid": "49999.99",
            "best_bid_size": "1.11",
            "best_ask": "50000.01",
            "best_ask_size": "2.22",
            "time": "2021-01-01T00:00:00.000000Z"
        }

        tick = transform_coinbase_ticker(ticker)

        assert isinstance(tick.fields.last_trade.px, float)
        assert isinstance(tick.fields.last_trade.qty, float)
        assert tick.fields.last_trade.px == 50000.123456
        assert tick.fields.last_trade.qty == 0.987654
        assert tick.fields.best_bid.px == 49999.99
        assert tick.fields.best_ask.px == 50000.01

    def test_tick_version_and_type(self):
        """Should set correct version and type."""
        ticker = {
            "type": "ticker",
            "sequence": 1,
            "product_id": "BTC-USD",
            "price": "50000.00",
            "last_size": "0.1",
            "time": "2021-01-01T00:00:00.000000Z"
        }

        tick = transform_coinbase_ticker(ticker)

        assert tick.v == 1
        assert tick.type == "tick"

    def test_empty_fields_when_no_trade_data(self):
        """Should have empty fields when no trade data present."""
        ticker = {
            "type": "ticker",
            "sequence": 1,
            "product_id": "BTC-USD",
            "time": "2021-01-01T00:00:00.000000Z"
        }

        tick = transform_coinbase_ticker(ticker)

        assert tick.fields.last_trade is None
        assert tick.fields.best_bid is None
        assert tick.fields.best_ask is None
