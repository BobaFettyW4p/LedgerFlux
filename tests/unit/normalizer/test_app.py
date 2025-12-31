"""Unit tests for Normalizer application."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from services.normalizer.app import Normalizer
from services.common.models import Tick, TickFields, TradeData


@pytest.fixture
def normalizer_config():
    """Create a sample normalizer config."""
    return {
        "shard_id": 0,
        "num_shards": 4,
        "input_stream": "market.ticks",
        "output_stream": "market.ticks",
        "stream_name": "market_ticks"
    }


@pytest.fixture
def sample_tick():
    """Create a valid sample tick."""
    return Tick(
        v=1,
        type="tick",
        product="BTC-USD",
        seq=12345,
        ts_event=1609459200000000000,
        ts_ingest=1609459200100000000,
        fields=TickFields(
            last_trade=TradeData(px=50000.0, qty=0.5),
            best_bid=TradeData(px=49995.0, qty=1.2),
            best_ask=TradeData(px=50005.0, qty=0.8)
        )
    )


class TestNormalizerInitialization:
    """Test suite for Normalizer initialization."""

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_init_with_explicit_shard_id(self, mock_broker_class, mock_load_config, normalizer_config):
        """Test initialization with explicit shard ID."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)

        assert normalizer.shard_id == 0
        assert normalizer.num_shards == 4
        assert normalizer.input_stream == "market.ticks"
        assert normalizer.output_stream == "market.ticks"
        assert normalizer.stream_name == "market_ticks"
        assert normalizer.stats['messages_processed'] == 0
        assert normalizer.stats['messages_validated'] == 0
        assert normalizer.stats['messages_rejected'] == 0
        assert normalizer.stats['products_seen'] == set()
        assert normalizer.last_sequences == {}

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_init_with_defaults(self, mock_broker_class, mock_load_config):
        """Test initialization with default values."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer({})

        assert normalizer.shard_id == 0  # Default when no HOSTNAME
        assert normalizer.num_shards == 4
        assert normalizer.input_stream == "market.ticks"
        assert normalizer.output_stream == "market.ticks"

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    @patch.dict('os.environ', {'HOSTNAME': 'normalizer-pod-3'})
    def test_init_auto_shard_from_hostname(self, mock_broker_class, mock_load_config):
        """Test auto shard ID detection from HOSTNAME."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        config = {"shard_id": "auto"}
        normalizer = Normalizer(config)

        assert normalizer.shard_id == 3

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    @patch.dict('os.environ', {'HOSTNAME': 'normalizer-0'})
    def test_init_auto_shard_zero(self, mock_broker_class, mock_load_config):
        """Test auto shard ID detection for shard 0."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        config = {"shard_id": "auto"}
        normalizer = Normalizer(config)

        assert normalizer.shard_id == 0

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    @patch.dict('os.environ', {'HOSTNAME': 'some-pod-without-number'})
    def test_init_auto_shard_no_match(self, mock_broker_class, mock_load_config):
        """Test auto shard ID when hostname has no number."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        config = {"shard_id": "auto"}
        normalizer = Normalizer(config)

        assert normalizer.shard_id == 0  # Falls back to 0

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_init_with_none_shard_id(self, mock_broker_class, mock_load_config):
        """Test initialization with None shard_id triggers auto detection."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        config = {"shard_id": None}

        with patch.dict('os.environ', {'HOSTNAME': 'test-pod-5'}):
            normalizer = Normalizer(config)

        assert normalizer.shard_id == 5


class TestNormalizerValidation:
    """Test suite for tick validation."""

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_valid(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test validation of a valid tick."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)
        assert normalizer._validate_tick(sample_tick) is True
        assert normalizer.last_sequences["BTC-USD"] == 12345

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_missing_product(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test validation fails for missing product."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)
        sample_tick.product = ""
        assert normalizer._validate_tick(sample_tick) is False

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_missing_fields(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test validation fails for missing fields."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)
        sample_tick.fields = None
        assert normalizer._validate_tick(sample_tick) is False

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_invalid_last_trade_price(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test validation fails for invalid last trade price."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)
        sample_tick.fields.last_trade.px = 0.0
        assert normalizer._validate_tick(sample_tick) is False

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_negative_last_trade_price(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test validation fails for negative last trade price."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)
        sample_tick.fields.last_trade.px = -100.0
        assert normalizer._validate_tick(sample_tick) is False

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_invalid_bid_price(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test validation fails for invalid bid price."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)
        sample_tick.fields.best_bid.px = 0.0
        assert normalizer._validate_tick(sample_tick) is False

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_invalid_ask_price(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test validation fails for invalid ask price."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)
        sample_tick.fields.best_ask.px = -50.0
        assert normalizer._validate_tick(sample_tick) is False

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_invalid_spread(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test validation fails when ask <= bid (invalid spread)."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)
        sample_tick.fields.best_bid.px = 50000.0
        sample_tick.fields.best_ask.px = 49995.0  # Ask lower than bid
        assert normalizer._validate_tick(sample_tick) is False

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_equal_bid_ask(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test validation fails when ask == bid."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)
        sample_tick.fields.best_bid.px = 50000.0
        sample_tick.fields.best_ask.px = 50000.0  # Equal
        assert normalizer._validate_tick(sample_tick) is False

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_out_of_order_sequence(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test validation warns about out-of-order sequence but still passes."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)

        # First tick establishes sequence
        sample_tick.seq = 100
        assert normalizer._validate_tick(sample_tick) is True
        assert normalizer.last_sequences["BTC-USD"] == 100

        # Second tick with lower sequence (out of order) - validation still passes but logs warning
        sample_tick.seq = 50
        assert normalizer._validate_tick(sample_tick) is True
        # Sequence gets updated even for out-of-order
        assert normalizer.last_sequences["BTC-USD"] == 50

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_no_bid_ask(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test validation passes when bid/ask are None."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)
        sample_tick.fields.best_bid = None
        sample_tick.fields.best_ask = None
        assert normalizer._validate_tick(sample_tick) is True

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    def test_validate_tick_exception_handling(self, mock_broker_class, mock_load_config, normalizer_config):
        """Test validation handles exceptions gracefully."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        normalizer = Normalizer(normalizer_config)

        # Create a mock tick that will raise an exception
        bad_tick = MagicMock()
        bad_tick.product = MagicMock(side_effect=Exception("Test exception"))

        assert normalizer._validate_tick(bad_tick) is False


class TestNormalizerProcessing:
    """Test suite for tick processing."""

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    async def test_process_tick_valid(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test processing a valid tick."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker.publish_tick = AsyncMock()
        mock_broker_class.return_value = mock_broker

        normalizer = Normalizer(normalizer_config)

        await normalizer._process_tick(sample_tick)

        assert normalizer.stats['messages_processed'] == 1
        assert normalizer.stats['messages_validated'] == 1
        assert normalizer.stats['messages_rejected'] == 0
        assert "BTC-USD" in normalizer.stats['products_seen']
        mock_broker.publish_tick.assert_called_once()

        # Check the shard it was published to
        call_args = mock_broker.publish_tick.call_args
        tick_arg = call_args[0][0]
        shard_arg = call_args[0][1]
        assert tick_arg == sample_tick
        assert isinstance(shard_arg, int)
        assert 0 <= shard_arg < 4

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    async def test_process_tick_invalid(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test processing an invalid tick."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker.publish_tick = AsyncMock()
        mock_broker_class.return_value = mock_broker

        normalizer = Normalizer(normalizer_config)

        # Make tick invalid
        sample_tick.fields.last_trade.px = 0.0

        await normalizer._process_tick(sample_tick)

        assert normalizer.stats['messages_processed'] == 1
        assert normalizer.stats['messages_validated'] == 0
        assert normalizer.stats['messages_rejected'] == 1
        # Should not publish invalid tick
        mock_broker.publish_tick.assert_not_called()

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    async def test_process_tick_publish_error(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test handling publish error."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker.publish_tick = AsyncMock(side_effect=Exception("Publish failed"))
        mock_broker_class.return_value = mock_broker

        normalizer = Normalizer(normalizer_config)

        await normalizer._process_tick(sample_tick)

        assert normalizer.stats['messages_processed'] == 1
        assert normalizer.stats['errors'] == 1

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    async def test_process_tick_stats_printing(self, mock_broker_class, mock_load_config, normalizer_config, sample_tick):
        """Test that stats are printed every 50 messages."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker.publish_tick = AsyncMock()
        mock_broker_class.return_value = mock_broker

        normalizer = Normalizer(normalizer_config)

        # Process 50 ticks
        for i in range(50):
            await normalizer._process_tick(sample_tick)

        assert normalizer.stats['messages_processed'] == 50
        assert normalizer.stats['messages_validated'] == 50


class TestNormalizerLifecycle:
    """Test suite for normalizer lifecycle."""

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    async def test_stop(self, mock_broker_class, mock_load_config, normalizer_config):
        """Test stopping the normalizer."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker_class.return_value = mock_broker

        normalizer = Normalizer(normalizer_config)
        await normalizer.stop()

        mock_broker.disconnect.assert_called_once()

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    async def test_start_connects_broker(self, mock_broker_class, mock_load_config, normalizer_config):
        """Test that start connects to broker."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker_class.return_value = mock_broker

        normalizer = Normalizer(normalizer_config)

        with patch.object(normalizer, '_process_messages', new_callable=AsyncMock):
            await normalizer.start()

        mock_broker.connect.assert_called_once_with(timeout=60.0)

    @patch('services.normalizer.app.load_nats_config')
    @patch('services.normalizer.app.NATSStreamManager')
    async def test_start_connection_failure(self, mock_broker_class, mock_load_config, normalizer_config):
        """Test start when broker connection fails."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker.connect = AsyncMock(side_effect=Exception("Connection failed"))
        mock_broker_class.return_value = mock_broker

        normalizer = Normalizer(normalizer_config)

        with pytest.raises(Exception, match="Connection failed"):
            await normalizer.start()
