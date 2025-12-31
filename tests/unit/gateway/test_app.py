"""Unit tests for Gateway application."""
import json
import time
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from services.gateway.app import RateLimiter, ClientConnection, Gateway
from services.common.models import (
    Tick, Snapshot, TickFields, TradeData
)


@pytest.fixture
def sample_tick():
    """Create a sample tick."""
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


@pytest.fixture
def sample_snapshot():
    """Create a sample snapshot."""
    return Snapshot(
        v=1,
        type="snapshot",
        product="BTC-USD",
        seq=12345,
        ts_snapshot=1609459200000000000,
        state={
            "last_trade": {"px": 50000.0, "qty": 0.5},
            "best_bid": {"px": 49995.0, "qty": 1.2}
        }
    )


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    return ws


@pytest.fixture
def gateway_config():
    """Create a sample gateway config."""
    return {
        "input_stream": "market.ticks",
        "stream_name": "market_ticks",
        "num_shards": 4,
        "port": 8000,
        "max_msgs_per_sec": 100,
        "burst": 200
    }


class TestRateLimiter:
    """Test suite for RateLimiter."""

    def test_init(self):
        """Test RateLimiter initialization."""
        limiter = RateLimiter(max_rate=10, burst=20)
        assert limiter.max_rate == 10
        assert limiter.burst == 20
        assert limiter.tokens == 20
        assert limiter.last_update > 0

    def test_is_allowed_initial_burst(self):
        """Test that initial burst allows messages."""
        limiter = RateLimiter(max_rate=10, burst=5)

        # Should allow burst number of messages
        for _ in range(5):
            assert limiter.is_allowed() is True

        # Should deny next message
        assert limiter.is_allowed() is False

    def test_is_allowed_token_replenishment(self):
        """Test token replenishment over time."""
        limiter = RateLimiter(max_rate=10, burst=1)

        # Use up the initial token
        assert limiter.is_allowed() is True
        assert limiter.is_allowed() is False

        # Wait for token replenishment (0.1 seconds for 1 token at 10/sec)
        time.sleep(0.15)

        # Should allow one more message
        assert limiter.is_allowed() is True

    def test_is_allowed_max_tokens_capped_at_burst(self):
        """Test that tokens don't accumulate beyond burst."""
        limiter = RateLimiter(max_rate=100, burst=5)

        # Wait long enough to accumulate many tokens
        time.sleep(1.0)

        # Should only allow burst number of messages
        for _ in range(5):
            assert limiter.is_allowed() is True
        assert limiter.is_allowed() is False

    def test_is_allowed_with_epsilon_tolerance(self):
        """Test floating point epsilon tolerance."""
        limiter = RateLimiter(max_rate=10, burst=10)
        limiter.tokens = 0.996  # Just below 1.0 but within epsilon

        # Should allow due to epsilon tolerance
        assert limiter.is_allowed() is True

    def test_get_retry_delay(self):
        """Test retry delay calculation."""
        limiter = RateLimiter(max_rate=10, burst=20)
        assert limiter.get_retry_delay() == 100  # 1000ms / 10 = 100ms

        limiter = RateLimiter(max_rate=50, burst=100)
        assert limiter.get_retry_delay() == 20  # 1000ms / 50 = 20ms


class TestClientConnection:
    """Test suite for ClientConnection."""

    def test_init(self, mock_websocket):
        """Test ClientConnection initialization."""
        rate_limiter = RateLimiter(max_rate=10, burst=20)
        client = ClientConnection(mock_websocket, rate_limiter)

        assert client.websocket == mock_websocket
        assert client.rate_limiter == rate_limiter
        assert client.subscribed_products == set()
        assert client.last_sequences == {}
        assert isinstance(client.connected_at, datetime)

    async def test_send_message_success(self, mock_websocket):
        """Test sending a message successfully."""
        rate_limiter = RateLimiter(max_rate=100, burst=200)
        client = ClientConnection(mock_websocket, rate_limiter)

        message = {"type": "test", "data": "hello"}
        result = await client.send_message(message)

        assert result is True
        mock_websocket.send_text.assert_called_once_with(json.dumps(message))

    async def test_send_message_rate_limited(self, mock_websocket):
        """Test sending message when rate limited."""
        rate_limiter = RateLimiter(max_rate=10, burst=0)  # No tokens
        client = ClientConnection(mock_websocket, rate_limiter)

        message = {"type": "test", "data": "hello"}
        result = await client.send_message(message)

        assert result is False
        # Should have sent rate limit message
        assert mock_websocket.send_text.call_count == 1
        sent_msg = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_msg["op"] == "rate_limit"
        assert "retry_ms" in sent_msg

    async def test_send_error(self, mock_websocket):
        """Test sending an error message."""
        rate_limiter = RateLimiter(max_rate=10, burst=20)
        client = ClientConnection(mock_websocket, rate_limiter)

        await client.send_error("TEST_ERROR", "This is a test error")

        mock_websocket.send_text.assert_called_once()
        sent_msg = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_msg["op"] == "error"
        assert sent_msg["code"] == "TEST_ERROR"
        assert sent_msg["msg"] == "This is a test error"


class TestGateway:
    """Test suite for Gateway."""

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    def test_init(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config):
        """Test Gateway initialization."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)

        assert gateway.config == gateway_config
        assert gateway.input_stream == "market.ticks"
        assert gateway.stream_name == "market_ticks"
        assert gateway.num_shards == 4
        assert gateway.port == 8000
        assert gateway.max_msgs_per_sec == 100
        assert gateway.burst == 200
        assert gateway.app is not None
        assert gateway.clients == {}
        assert gateway.stats['clients_connected'] == 0
        assert gateway.stats['messages_sent'] == 0

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    def test_init_with_defaults(self, mock_store_class, mock_broker_class, mock_load_config):
        """Test Gateway initialization with default config values."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway({})

        assert gateway.input_stream == "market.ticks"
        assert gateway.stream_name == "market_ticks"
        assert gateway.num_shards == 4
        assert gateway.port == 8000
        assert gateway.max_msgs_per_sec == 100
        assert gateway.burst == 200

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_start_success(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config):
        """Test successful gateway start."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker_class.return_value = mock_broker

        mock_store = AsyncMock()
        mock_store_class.return_value = mock_store

        gateway = Gateway(gateway_config)

        with patch.object(gateway, '_start_message_processing', new_callable=AsyncMock) as mock_start_processing:
            await gateway.start()

        mock_broker.connect.assert_called_once_with(timeout=60.0)
        mock_store.connect.assert_called_once()
        mock_store.ensure_schema.assert_called_once()
        mock_start_processing.assert_called_once()

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_start_postgres_failure(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config):
        """Test gateway start when Postgres connection fails."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker_class.return_value = mock_broker

        mock_store = AsyncMock()
        mock_store.connect.side_effect = Exception("Connection failed")
        mock_store_class.return_value = mock_store

        gateway = Gateway(gateway_config)

        with patch.object(gateway, '_start_message_processing', new_callable=AsyncMock):
            # Should not raise, just print warning
            await gateway.start()

        mock_broker.connect.assert_called_once()

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_stop(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config):
        """Test gateway stop."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker_class.return_value = mock_broker

        mock_store = AsyncMock()
        mock_store_class.return_value = mock_store

        gateway = Gateway(gateway_config)
        await gateway.stop()

        mock_broker.disconnect.assert_called_once()
        mock_store.close.assert_called_once()

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_handle_client_message_subscribe(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, mock_websocket):
        """Test handling subscribe message."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)
        rate_limiter = RateLimiter(100, 200)
        client = ClientConnection(mock_websocket, rate_limiter)

        with patch.object(gateway, '_handle_subscribe', new_callable=AsyncMock) as mock_sub:
            message = '{"op": "subscribe", "products": ["BTC-USD"]}'
            await gateway._handle_client_message(client, message)

            mock_sub.assert_called_once()

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_handle_client_message_unsubscribe(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, mock_websocket):
        """Test handling unsubscribe message."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)
        rate_limiter = RateLimiter(100, 200)
        client = ClientConnection(mock_websocket, rate_limiter)

        with patch.object(gateway, '_handle_unsubscribe', new_callable=AsyncMock) as mock_unsub:
            message = '{"op": "unsubscribe", "products": ["BTC-USD"]}'
            await gateway._handle_client_message(client, message)

            mock_unsub.assert_called_once()

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_handle_client_message_ping(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, mock_websocket):
        """Test handling ping message."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)
        rate_limiter = RateLimiter(100, 200)
        client = ClientConnection(mock_websocket, rate_limiter)

        with patch.object(gateway, '_handle_ping', new_callable=AsyncMock) as mock_ping:
            message = '{"op": "ping", "t": 1234567890}'
            await gateway._handle_client_message(client, message)

            mock_ping.assert_called_once()

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_handle_client_message_invalid_json(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, mock_websocket):
        """Test handling invalid JSON."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)
        rate_limiter = RateLimiter(100, 200)
        client = ClientConnection(mock_websocket, rate_limiter)

        message = 'invalid json{'
        await gateway._handle_client_message(client, message)

        # Should send error
        mock_websocket.send_text.assert_called_once()
        sent_msg = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_msg["code"] == "INVALID_JSON"

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_handle_client_message_unknown_operation(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, mock_websocket):
        """Test handling unknown operation."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)
        rate_limiter = RateLimiter(100, 200)
        client = ClientConnection(mock_websocket, rate_limiter)

        message = '{"op": "unknown"}'
        await gateway._handle_client_message(client, message)

        # Should send error
        mock_websocket.send_text.assert_called_once()
        sent_msg = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_msg["code"] == "INVALID_OPERATION"

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_handle_subscribe_without_snapshot(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, mock_websocket):
        """Test subscribe without requesting snapshot."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)
        rate_limiter = RateLimiter(100, 200)
        client = ClientConnection(mock_websocket, rate_limiter)

        message = {
            "op": "subscribe",
            "products": ["BTC-USD", "ETH-USD"],
            "want_snapshot": False
        }

        await gateway._handle_subscribe(client, message)

        assert "BTC-USD" in client.subscribed_products
        assert "ETH-USD" in client.subscribed_products
        # Should not send any snapshots
        mock_websocket.send_text.assert_not_called()

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_handle_subscribe_with_snapshot_from_store(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, mock_websocket, sample_snapshot):
        """Test subscribe with snapshot from store."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_store = AsyncMock()
        mock_store.get_latest.return_value = {
            'product': 'BTC-USD',
            'last_seq': 12345,
            'ts_snapshot': 1609459200000000000,
            'state': {'last_trade': {'px': 50000.0, 'qty': 0.5}}
        }
        mock_store_class.return_value = mock_store

        gateway = Gateway(gateway_config)
        rate_limiter = RateLimiter(100, 200)
        client = ClientConnection(mock_websocket, rate_limiter)

        message = {
            "op": "subscribe",
            "products": ["BTC-USD"],
            "want_snapshot": True
        }

        await gateway._handle_subscribe(client, message)

        assert "BTC-USD" in client.subscribed_products
        mock_store.get_latest.assert_called_once_with("BTC-USD")
        mock_websocket.send_text.assert_called_once()

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_handle_subscribe_with_fallback_snapshot(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, mock_websocket):
        """Test subscribe with fallback snapshot when store returns None."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_store = AsyncMock()
        mock_store.get_latest.return_value = None
        mock_store_class.return_value = mock_store

        gateway = Gateway(gateway_config)
        rate_limiter = RateLimiter(100, 200)
        client = ClientConnection(mock_websocket, rate_limiter)

        message = {
            "op": "subscribe",
            "products": ["BTC-USD"],
            "want_snapshot": True
        }

        await gateway._handle_subscribe(client, message)

        assert "BTC-USD" in client.subscribed_products
        # Should send fallback snapshot
        mock_websocket.send_text.assert_called_once()
        sent_msg = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_msg["op"] == "snapshot"

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_handle_unsubscribe(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, mock_websocket):
        """Test unsubscribe."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)
        rate_limiter = RateLimiter(100, 200)
        client = ClientConnection(mock_websocket, rate_limiter)
        client.subscribed_products = {"BTC-USD", "ETH-USD", "SOL-USD"}

        message = {
            "op": "unsubscribe",
            "products": ["BTC-USD", "ETH-USD"]
        }

        await gateway._handle_unsubscribe(client, message)

        assert "BTC-USD" not in client.subscribed_products
        assert "ETH-USD" not in client.subscribed_products
        assert "SOL-USD" in client.subscribed_products

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_handle_ping(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, mock_websocket):
        """Test ping/pong."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)
        rate_limiter = RateLimiter(100, 200)
        client = ClientConnection(mock_websocket, rate_limiter)

        message = {
            "op": "ping",
            "t": 1234567890
        }

        await gateway._handle_ping(client, message)

        mock_websocket.send_text.assert_called_once()
        sent_msg = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_msg["op"] == "pong"
        assert sent_msg["t"] == 1234567890

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_broadcast_tick(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, sample_tick):
        """Test broadcasting tick to subscribed clients."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)

        # Create mock clients
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws3 = AsyncMock()

        client1 = ClientConnection(ws1, RateLimiter(100, 200))
        client1.subscribed_products = {"BTC-USD"}

        client2 = ClientConnection(ws2, RateLimiter(100, 200))
        client2.subscribed_products = {"ETH-USD"}  # Not subscribed to BTC-USD

        client3 = ClientConnection(ws3, RateLimiter(100, 200))
        client3.subscribed_products = {"BTC-USD", "ETH-USD"}

        gateway.clients = {ws1: client1, ws2: client2, ws3: client3}

        await gateway._broadcast_tick(sample_tick)

        # Client1 and Client3 should receive the message
        assert ws1.send_text.call_count == 1
        assert ws2.send_text.call_count == 0  # Not subscribed
        assert ws3.send_text.call_count == 1

        assert gateway.stats['messages_sent'] == 2

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_broadcast_tick_no_clients(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, sample_tick):
        """Test broadcasting tick with no connected clients."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)
        gateway.clients = {}

        # Should not raise any errors
        await gateway._broadcast_tick(sample_tick)

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_broadcast_tick_rate_limited(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config, sample_tick):
        """Test broadcasting tick when client is rate limited."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)

        ws = AsyncMock()
        client = ClientConnection(ws, RateLimiter(100, 0))  # No tokens
        client.subscribed_products = {"BTC-USD"}

        gateway.clients = {ws: client}

        await gateway._broadcast_tick(sample_tick)

        # Should send rate limit message
        assert ws.send_text.call_count == 1
        assert gateway.stats['rate_limits'] == 1
        assert gateway.stats['messages_sent'] == 0

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    async def test_start_message_processing(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config):
        """Test starting message processing for all shards."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker_class.return_value = mock_broker

        gateway = Gateway(gateway_config)

        with patch.dict('os.environ', {'HOSTNAME': 'test-host'}):
            await gateway._start_message_processing()

        # Should subscribe to all shards
        assert mock_broker.subscribe_to_shard.call_count == 4

        # Verify consumer names
        calls = mock_broker.subscribe_to_shard.call_args_list
        for i, call in enumerate(calls):
            assert call[0][0] == i  # shard_id
            assert call[1]['consumer_name'] == f"gateway-test-host-{i}"


class TestGatewayHTTPEndpoints:
    """Test HTTP endpoints of Gateway."""

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    def test_root_endpoint(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config):
        """Test root endpoint."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)
        client = TestClient(gateway.app)

        response = client.get("/")
        assert response.status_code == 200
        assert "Market Data Gateway" in response.text
        assert "ws://localhost:8000/ws" in response.text

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    def test_health_endpoint(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config):
        """Test health endpoint."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        gateway = Gateway(gateway_config)
        client = TestClient(gateway.app)

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "clients" in data

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    def test_ready_endpoint_connected(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config):
        """Test ready endpoint when broker is connected."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = MagicMock()
        mock_broker.nats_connection = MagicMock()  # Simulates connected
        mock_broker_class.return_value = mock_broker

        gateway = Gateway(gateway_config)
        client = TestClient(gateway.app)

        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["broker"] == "connected"

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    def test_ready_endpoint_not_connected(self, mock_store_class, mock_broker_class, mock_load_config, gateway_config):
        """Test ready endpoint when broker is not connected."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = MagicMock()
        mock_broker.nats_connection = None  # Not connected
        mock_broker_class.return_value = mock_broker

        gateway = Gateway(gateway_config)
        client = TestClient(gateway.app)

        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["broker"] == "disconnected"

    @patch('services.gateway.app.load_nats_config')
    @patch('services.gateway.app.NATSStreamManager')
    @patch('services.gateway.app.PostgresSnapshotStore')
    @patch('services.gateway.app.get_metrics_response')
    def test_metrics_endpoint(self, mock_get_metrics, mock_store_class, mock_broker_class, mock_load_config, gateway_config):
        """Test metrics endpoint."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_get_metrics.return_value = ("# Metrics data", "text/plain")

        gateway = Gateway(gateway_config)
        client = TestClient(gateway.app)

        response = client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert "Metrics data" in response.text
