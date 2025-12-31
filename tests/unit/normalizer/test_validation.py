"""Tests for validation logic in services/normalizer/app.py"""

import pytest
from services.normalizer.app import Normalizer
from services.common.models import Tick, TickFields, TradeData


class TestNormalizerValidation:
    """Test tick validation logic."""

    @pytest.fixture
    def normalizer(self):
        """Create Normalizer instance."""
        config = {
            "shard_id": 0,
            "num_shards": 4,
            "input_stream": "market.ticks",
            "output_stream": "market.ticks",
            "stream_name": "market_ticks",
        }
        return Normalizer(config)

    @pytest.fixture
    def valid_tick(self):
        """Create valid tick."""
        return Tick(
            product="BTC-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(
                last_trade=TradeData(px=50000.0, qty=0.5),
                best_bid=TradeData(px=49995.0, qty=1.2),
                best_ask=TradeData(px=50005.0, qty=0.8),
            ),
        )

    def test_valid_tick(self, normalizer, valid_tick):
        """Should accept valid tick."""
        assert normalizer._validate_tick(valid_tick) is True

    def test_reject_missing_product(self, normalizer):
        """Should reject tick with missing product."""
        tick = Tick(
            product="",  # Empty product
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(last_trade=TradeData(px=50000.0, qty=0.5)),
        )

        assert normalizer._validate_tick(tick) is False

    def test_reject_negative_price(self, normalizer):
        """Should reject tick with negative price."""
        tick = Tick(
            product="BTC-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(last_trade=TradeData(px=-100.0, qty=0.5)),
        )

        assert normalizer._validate_tick(tick) is False

    def test_reject_zero_price(self, normalizer):
        """Should reject tick with zero price."""
        tick = Tick(
            product="BTC-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(last_trade=TradeData(px=0.0, qty=0.5)),
        )

        assert normalizer._validate_tick(tick) is False

    def test_reject_negative_bid_price(self, normalizer):
        """Should reject tick with negative bid price."""
        tick = Tick(
            product="BTC-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(
                last_trade=TradeData(px=50000.0, qty=0.5),
                best_bid=TradeData(px=-100.0, qty=1.2),
            ),
        )

        assert normalizer._validate_tick(tick) is False

    def test_reject_zero_bid_price(self, normalizer):
        """Should reject tick with zero bid price."""
        tick = Tick(
            product="BTC-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(best_bid=TradeData(px=0.0, qty=1.2)),
        )

        assert normalizer._validate_tick(tick) is False

    def test_reject_negative_ask_price(self, normalizer):
        """Should reject tick with negative ask price."""
        tick = Tick(
            product="BTC-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(
                last_trade=TradeData(px=50000.0, qty=0.5),
                best_ask=TradeData(px=-100.0, qty=0.8),
            ),
        )

        assert normalizer._validate_tick(tick) is False

    def test_reject_invalid_spread_bid_equals_ask(self, normalizer):
        """Should reject tick where bid equals ask."""
        tick = Tick(
            product="BTC-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(
                last_trade=TradeData(px=50000.0, qty=0.5),
                best_bid=TradeData(px=50000.0, qty=1.2),
                best_ask=TradeData(px=50000.0, qty=0.8),
            ),
        )

        assert normalizer._validate_tick(tick) is False

    def test_reject_invalid_spread_bid_greater_than_ask(self, normalizer):
        """Should reject tick where bid > ask (crossed spread)."""
        tick = Tick(
            product="BTC-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(
                last_trade=TradeData(px=50000.0, qty=0.5),
                best_bid=TradeData(px=50010.0, qty=1.2),  # Bid higher than ask
                best_ask=TradeData(px=50005.0, qty=0.8),
            ),
        )

        assert normalizer._validate_tick(tick) is False

    def test_accept_valid_spread(self, normalizer):
        """Should accept tick with valid spread (bid < ask)."""
        tick = Tick(
            product="BTC-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(
                last_trade=TradeData(px=50000.0, qty=0.5),
                best_bid=TradeData(px=49995.0, qty=1.2),
                best_ask=TradeData(px=50005.0, qty=0.8),
            ),
        )

        assert normalizer._validate_tick(tick) is True

    def test_sequence_tracking(self, normalizer):
        """Should track last sequence per product."""
        tick1 = Tick(
            product="BTC-USD",
            seq=100,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(last_trade=TradeData(px=50000.0, qty=0.5)),
        )

        tick2 = Tick(
            product="BTC-USD",
            seq=101,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(last_trade=TradeData(px=50001.0, qty=0.5)),
        )

        # First tick
        assert normalizer._validate_tick(tick1) is True
        assert normalizer.last_sequences["BTC-USD"] == 100

        # Second tick with higher sequence
        assert normalizer._validate_tick(tick2) is True
        assert normalizer.last_sequences["BTC-USD"] == 101

    def test_out_of_order_detection(self, normalizer):
        """Should detect out-of-order sequences (but still accept)."""
        # Establish sequence
        tick1 = Tick(
            product="BTC-USD",
            seq=100,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(last_trade=TradeData(px=50000.0, qty=0.5)),
        )
        normalizer._validate_tick(tick1)

        # Send older sequence (should still validate but log warning)
        tick2 = Tick(
            product="BTC-USD",
            seq=50,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(last_trade=TradeData(px=50001.0, qty=0.5)),
        )

        # Should still return True (validation passes, just logs warning)
        assert normalizer._validate_tick(tick2) is True

    def test_accept_tick_with_only_last_trade(self, normalizer):
        """Should accept tick with only last_trade field."""
        tick = Tick(
            product="ETH-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(last_trade=TradeData(px=3000.0, qty=2.5)),
        )

        assert normalizer._validate_tick(tick) is True

    def test_accept_tick_with_only_bid(self, normalizer):
        """Should accept tick with only bid field."""
        tick = Tick(
            product="SOL-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(best_bid=TradeData(px=100.0, qty=50.0)),
        )

        assert normalizer._validate_tick(tick) is True

    def test_accept_tick_with_only_ask(self, normalizer):
        """Should accept tick with only ask field."""
        tick = Tick(
            product="ADA-USD",
            seq=12345,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(best_ask=TradeData(px=1.50, qty=1000.0)),
        )

        assert normalizer._validate_tick(tick) is True

    def test_per_product_sequence_tracking(self, normalizer):
        """Should track sequences independently per product."""
        tick_btc = Tick(
            product="BTC-USD",
            seq=100,
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(last_trade=TradeData(px=50000.0, qty=0.5)),
        )

        tick_eth = Tick(
            product="ETH-USD",
            seq=50,  # Lower sequence than BTC
            ts_event=1609459200000000000,
            ts_ingest=1609459200100000000,
            fields=TickFields(last_trade=TradeData(px=3000.0, qty=1.0)),
        )

        assert normalizer._validate_tick(tick_btc) is True
        assert normalizer._validate_tick(tick_eth) is True

        assert normalizer.last_sequences["BTC-USD"] == 100
        assert normalizer.last_sequences["ETH-USD"] == 50
