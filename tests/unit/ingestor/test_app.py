"""Unit tests for Ingestor application."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from services.ingestor.app import transform_coinbase_ticker, CoinbaseIngester
from services.common.models import Tick


@pytest.fixture
def sample_coinbase_ticker():
    """Create a sample Coinbase ticker message."""
    return {
        "type": "ticker",
        "sequence": 12345,
        "product_id": "BTC-USD",
        "price": "50000.00",
        "last_size": "0.5",
        "best_bid": "49995.00",
        "best_bid_size": "1.2",
        "best_ask": "50005.00",
        "best_ask_size": "0.8",
        "time": "2021-01-01T00:00:00.000000Z",
    }


@pytest.fixture
def ingestor_config():
    """Create a sample ingestor config."""
    return {
        "products": ["BTC-USD", "ETH-USD"],
        "channels": ["ticker", "heartbeat"],
        "num_shards": 4,
        "stream_name": "market_ticks",
        "subject_prefix": "market.ticks",
        "ws_uri": "wss://ws-feed.exchange.coinbase.com",
        "health_port": 8080,
    }


class TestTransformCoinbaseTicker:
    """Test suite for transform_coinbase_ticker function."""

    def test_transform_complete_ticker(self, sample_coinbase_ticker):
        """Test transforming a complete ticker message."""
        tick = transform_coinbase_ticker(sample_coinbase_ticker)

        assert isinstance(tick, Tick)
        assert tick.product == "BTC-USD"
        assert tick.seq == 12345
        assert tick.type == "tick"
        assert tick.v == 1

        # Check fields
        assert tick.fields.last_trade is not None
        assert tick.fields.last_trade.px == 50000.0
        assert tick.fields.last_trade.qty == 0.5

        assert tick.fields.best_bid is not None
        assert tick.fields.best_bid.px == 49995.0
        assert tick.fields.best_bid.qty == 1.2

        assert tick.fields.best_ask is not None
        assert tick.fields.best_ask.px == 50005.0
        assert tick.fields.best_ask.qty == 0.8

    def test_transform_ticker_without_trade(self, sample_coinbase_ticker):
        """Test transforming ticker without trade data."""
        del sample_coinbase_ticker["price"]
        del sample_coinbase_ticker["last_size"]

        tick = transform_coinbase_ticker(sample_coinbase_ticker)

        assert tick.product == "BTC-USD"
        assert tick.fields.last_trade is None
        assert tick.fields.best_bid is not None
        assert tick.fields.best_ask is not None

    def test_transform_ticker_without_bid(self, sample_coinbase_ticker):
        """Test transforming ticker without bid data."""
        del sample_coinbase_ticker["best_bid"]
        del sample_coinbase_ticker["best_bid_size"]

        tick = transform_coinbase_ticker(sample_coinbase_ticker)

        assert tick.product == "BTC-USD"
        assert tick.fields.last_trade is not None
        assert tick.fields.best_bid is None
        assert tick.fields.best_ask is not None

    def test_transform_ticker_without_ask(self, sample_coinbase_ticker):
        """Test transforming ticker without ask data."""
        del sample_coinbase_ticker["best_ask"]
        del sample_coinbase_ticker["best_ask_size"]

        tick = transform_coinbase_ticker(sample_coinbase_ticker)

        assert tick.product == "BTC-USD"
        assert tick.fields.last_trade is not None
        assert tick.fields.best_bid is not None
        assert tick.fields.best_ask is None

    def test_transform_ticker_timestamp_parsing(self, sample_coinbase_ticker):
        """Test timestamp parsing from ISO format."""
        tick = transform_coinbase_ticker(sample_coinbase_ticker)

        # Should be 2021-01-01 00:00:00 UTC in nanoseconds
        # The timestamp string is "2021-01-01T00:00:00.000000Z"
        # which should parse to 1609459200 seconds since epoch (UTC)
        expected_ts = 1609459200000000000  # 2021-01-01 00:00:00 UTC in nanoseconds
        assert tick.ts_event == expected_ts


class TestCoinbaseIngester:
    """Test suite for CoinbaseIngester."""

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    def test_init(self, mock_broker_class, mock_load_config, ingestor_config):
        """Test CoinbaseIngester initialization."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        ingester = CoinbaseIngester(ingestor_config)

        assert ingester.products == ["BTC-USD", "ETH-USD"]
        assert ingester.channels == ["ticker", "heartbeat"]
        assert ingester.num_shards == 4
        assert ingester.stream_name == "market_ticks"
        assert ingester.subject_prefix == "market.ticks"
        assert ingester.ws_uri == "wss://ws-feed.exchange.coinbase.com"
        assert ingester.health_port == 8080
        assert ingester._ready is False
        assert ingester._broker_ready is False
        assert ingester._ws_connected is False
        assert ingester.stats["messages_received"] == 0
        assert ingester.stats["messages_published"] == 0
        assert "BTC-USD" in ingester.stats["products"]
        assert "ETH-USD" in ingester.stats["products"]

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    def test_init_with_defaults(self, mock_broker_class, mock_load_config):
        """Test initialization with default values."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        ingester = CoinbaseIngester({})

        assert ingester.products == []
        assert ingester.channels == ["ticker", "heartbeat"]
        assert ingester.num_shards == 4
        assert ingester.stream_name == "market_ticks"
        assert ingester.subject_prefix == "market.ticks"
        assert ingester.health_port == 8080

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    def test_init_normalizes_product_names(self, mock_broker_class, mock_load_config):
        """Test that product names are normalized to uppercase."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        config = {"products": ["btc-usd", " eth-USD ", "SOL-usd"]}
        ingester = CoinbaseIngester(config)

        assert ingester.products == ["BTC-USD", "ETH-USD", "SOL-USD"]

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    async def test_process_message_subscriptions(
        self, mock_broker_class, mock_load_config, ingestor_config
    ):
        """Test processing subscription confirmation message."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        ingester = CoinbaseIngester(ingestor_config)

        message = json.dumps(
            {
                "type": "subscriptions",
                "channels": [{"name": "ticker", "product_ids": ["BTC-USD"]}],
            }
        )

        await ingester._process_message(message)

        assert ingester.stats["messages_received"] == 1
        # Should not process as ticker
        assert ingester.stats["messages_published"] == 0

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    async def test_process_message_ticker(
        self,
        mock_broker_class,
        mock_load_config,
        ingestor_config,
        sample_coinbase_ticker,
    ):
        """Test processing ticker message."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker_class.return_value = mock_broker

        ingester = CoinbaseIngester(ingestor_config)

        message = json.dumps(sample_coinbase_ticker)

        with patch.object(
            ingester, "_process_ticker", new_callable=AsyncMock
        ) as mock_process:
            await ingester._process_message(message)

        assert ingester.stats["messages_received"] == 1
        mock_process.assert_called_once()

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    async def test_process_message_heartbeat(
        self, mock_broker_class, mock_load_config, ingestor_config
    ):
        """Test processing heartbeat message."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        ingester = CoinbaseIngester(ingestor_config)

        message = json.dumps(
            {
                "type": "heartbeat",
                "sequence": 12345,
                "last_trade_id": 54321,
                "product_id": "BTC-USD",
                "time": "2021-01-01T00:00:00.000000Z",
            }
        )

        await ingester._process_message(message)

        assert ingester.stats["messages_received"] == 1
        # Heartbeat doesn't publish anything
        assert ingester.stats["messages_published"] == 0

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    async def test_process_message_unknown_type(
        self, mock_broker_class, mock_load_config, ingestor_config
    ):
        """Test processing unknown message type."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        ingester = CoinbaseIngester(ingestor_config)

        message = json.dumps({"type": "unknown", "data": "test"})

        await ingester._process_message(message)

        assert ingester.stats["messages_received"] == 1
        assert ingester.stats["messages_published"] == 0

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    async def test_process_message_invalid_json(
        self, mock_broker_class, mock_load_config, ingestor_config
    ):
        """Test processing invalid JSON."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        ingester = CoinbaseIngester(ingestor_config)

        message = "invalid json{"

        await ingester._process_message(message)

        assert ingester.stats["errors"] == 1

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    async def test_process_ticker_success(
        self,
        mock_broker_class,
        mock_load_config,
        ingestor_config,
        sample_coinbase_ticker,
    ):
        """Test successfully processing and publishing a ticker."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker.publish_tick = AsyncMock()
        mock_broker_class.return_value = mock_broker

        ingester = CoinbaseIngester(ingestor_config)

        await ingester._process_ticker(sample_coinbase_ticker)

        assert ingester.stats["messages_published"] == 1
        assert ingester.stats["products"]["BTC-USD"] == 1
        mock_broker.publish_tick.assert_called_once()

        # Check the tick was created correctly
        call_args = mock_broker.publish_tick.call_args
        tick = call_args[0][0]
        shard = call_args[0][1]

        assert tick.product == "BTC-USD"
        assert isinstance(shard, int)
        assert 0 <= shard < 4

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    async def test_process_ticker_publish_error(
        self,
        mock_broker_class,
        mock_load_config,
        ingestor_config,
        sample_coinbase_ticker,
    ):
        """Test handling publish error."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker.publish_tick = AsyncMock(side_effect=Exception("Publish failed"))
        mock_broker_class.return_value = mock_broker

        ingester = CoinbaseIngester(ingestor_config)

        await ingester._process_ticker(sample_coinbase_ticker)

        assert ingester.stats["messages_published"] == 0
        assert ingester.stats["errors"] == 1

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    async def test_process_ticker_transform_error(
        self, mock_broker_class, mock_load_config, ingestor_config
    ):
        """Test handling transform error."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        ingester = CoinbaseIngester(ingestor_config)

        # Invalid ticker data (missing required fields)
        invalid_ticker = {"type": "ticker"}

        await ingester._process_ticker(invalid_ticker)

        assert ingester.stats["errors"] == 1
        assert ingester.stats["messages_published"] == 0

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    async def test_process_ticker_stats_printing(
        self,
        mock_broker_class,
        mock_load_config,
        ingestor_config,
        sample_coinbase_ticker,
    ):
        """Test that stats are printed every 100 messages."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker.publish_tick = AsyncMock()
        mock_broker_class.return_value = mock_broker

        ingester = CoinbaseIngester(ingestor_config)

        # Publish 99 messages - should not print stats
        for _ in range(99):
            await ingester._process_ticker(sample_coinbase_ticker)

        assert ingester.stats["messages_published"] == 99

        # 100th message should trigger stats printing
        await ingester._process_ticker(sample_coinbase_ticker)

        assert ingester.stats["messages_published"] == 100

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    async def test_stop(self, mock_broker_class, mock_load_config, ingestor_config):
        """Test stopping the ingester."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker_class.return_value = mock_broker

        ingester = CoinbaseIngester(ingestor_config)
        ingester._ready = True

        with patch.object(
            ingester, "_stop_health_server", new_callable=AsyncMock
        ) as mock_stop:
            await ingester.stop()

        assert ingester._ready is False
        mock_broker.disconnect.assert_called_once()
        mock_stop.assert_called_once()


class TestCoinbaseIngesterHealthEndpoints:
    """Test health endpoints of CoinbaseIngester."""

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    def test_health_endpoint(
        self, mock_broker_class, mock_load_config, ingestor_config
    ):
        """Test health endpoint."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        ingester = CoinbaseIngester(ingestor_config)
        ingester.stats["messages_received"] = 100
        ingester.stats["messages_published"] = 95
        ingester.stats["errors"] = 5

        client = TestClient(ingester.health_app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["messages_received"] == 100
        assert data["messages_published"] == 95
        assert data["errors"] == 5

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    def test_ready_endpoint_not_ready(
        self, mock_broker_class, mock_load_config, ingestor_config
    ):
        """Test ready endpoint when not ready."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        ingester = CoinbaseIngester(ingestor_config)

        client = TestClient(ingester.health_app)
        response = client.get("/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["broker"] == "disconnected"
        assert data["websocket"] == "disconnected"

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    def test_ready_endpoint_ready(
        self, mock_broker_class, mock_load_config, ingestor_config
    ):
        """Test ready endpoint when ready."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        ingester = CoinbaseIngester(ingestor_config)
        ingester._ready = True
        ingester._broker_ready = True
        ingester._ws_connected = True

        client = TestClient(ingester.health_app)
        response = client.get("/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["broker"] == "connected"
        assert data["websocket"] == "connected"

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    @patch("services.ingestor.app.get_metrics_response")
    def test_metrics_endpoint(
        self, mock_get_metrics, mock_broker_class, mock_load_config, ingestor_config
    ):
        """Test metrics endpoint."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_get_metrics.return_value = ("# Metrics data", "text/plain")

        ingester = CoinbaseIngester(ingestor_config)

        client = TestClient(ingester.health_app)
        response = client.get("/metrics")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert "Metrics data" in response.text


class TestCoinbaseIngesterStartStop:
    """Test start/stop lifecycle."""

    @patch("services.ingestor.app.load_nats_config")
    @patch("services.ingestor.app.NATSStreamManager")
    async def test_start_connects_broker(
        self, mock_broker_class, mock_load_config, ingestor_config
    ):
        """Test that start connects to broker."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker_class.return_value = mock_broker

        ingester = CoinbaseIngester(ingestor_config)

        with patch.object(ingester, "_start_health_server", new_callable=AsyncMock):
            with patch.object(ingester, "_websocket_loop", new_callable=AsyncMock):
                await ingester.start()

        mock_broker.connect.assert_called_once_with(timeout=60.0)
        assert ingester._broker_ready is True
        assert ingester._ready is True
