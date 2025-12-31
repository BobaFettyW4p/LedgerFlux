"""Tests for ClientConnection class in services/gateway/app.py"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from freezegun import freeze_time
from services.gateway.app import ClientConnection, RateLimiter
from services.common.models import RateLimitMessage, ErrorMessage


class TestClientConnection:
    """Test ClientConnection class."""

    @pytest.fixture
    def mock_websocket(self):
        """Create mock WebSocket."""
        ws = AsyncMock()
        ws.send_text = AsyncMock()
        return ws

    @pytest.fixture
    def rate_limiter(self):
        """Create rate limiter."""
        return RateLimiter(max_rate=10, burst=20)

    @pytest.fixture
    def client(self, mock_websocket, rate_limiter):
        """Create ClientConnection instance."""
        return ClientConnection(mock_websocket, rate_limiter)

    def test_client_connection_initialization(self, client, mock_websocket, rate_limiter):
        """Should initialize with correct attributes."""
        assert client.websocket == mock_websocket
        assert client.rate_limiter == rate_limiter
        assert client.subscribed_products == set()
        assert client.last_sequences == {}
        assert isinstance(client.connected_at, datetime)

    @pytest.mark.asyncio
    async def test_send_message_allowed(self, client, mock_websocket):
        """Should send message when rate limit allows."""
        message = {"op": "incr", "data": {"product": "BTC-USD", "price": 50000.0}}

        result = await client.send_message(message)

        assert result is True
        mock_websocket.send_text.assert_called_once()
        sent_data = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_data == message

    @pytest.mark.asyncio
    @freeze_time("2021-01-01 00:00:00")
    async def test_send_message_rate_limited(self, mock_websocket):
        """Should send rate limit message when rate exceeded."""
        with freeze_time("2021-01-01 00:00:00"):
            limiter = RateLimiter(max_rate=10, burst=5)
            client = ClientConnection(mock_websocket, limiter)

            # Consume all tokens
            for _ in range(5):
                client.rate_limiter.is_allowed()

            # Next send should be rate limited
            message = {"op": "incr", "data": {"product": "BTC-USD"}}
            result = await client.send_message(message)

            assert result is False
            mock_websocket.send_text.assert_called_once()

            # Should have sent rate limit message
            sent_data = json.loads(mock_websocket.send_text.call_args[0][0])
            assert sent_data["op"] == "rate_limit"
            assert sent_data["retry_ms"] == 100  # 1000/10

    @pytest.mark.asyncio
    async def test_send_error(self, client, mock_websocket):
        """Should send error message."""
        await client.send_error("INVALID_OP", "Unknown operation")

        mock_websocket.send_text.assert_called_once()
        sent_data = json.loads(mock_websocket.send_text.call_args[0][0])

        assert sent_data["op"] == "error"
        assert sent_data["code"] == "INVALID_OP"
        assert sent_data["msg"] == "Unknown operation"

    def test_subscription_tracking(self, client):
        """Should track subscribed products."""
        assert len(client.subscribed_products) == 0

        # Add subscriptions
        client.subscribed_products.add("BTC-USD")
        client.subscribed_products.add("ETH-USD")

        assert len(client.subscribed_products) == 2
        assert "BTC-USD" in client.subscribed_products
        assert "ETH-USD" in client.subscribed_products

        # Remove subscription
        client.subscribed_products.remove("BTC-USD")

        assert len(client.subscribed_products) == 1
        assert "BTC-USD" not in client.subscribed_products
        assert "ETH-USD" in client.subscribed_products

    def test_sequence_tracking(self, client):
        """Should track last sequences per product."""
        assert len(client.last_sequences) == 0

        # Track sequences
        client.last_sequences["BTC-USD"] = 12345
        client.last_sequences["ETH-USD"] = 67890

        assert client.last_sequences["BTC-USD"] == 12345
        assert client.last_sequences["ETH-USD"] == 67890

        # Update sequence
        client.last_sequences["BTC-USD"] = 12346

        assert client.last_sequences["BTC-USD"] == 12346

    @pytest.mark.asyncio
    @freeze_time("2021-01-01 00:00:00")
    async def test_send_multiple_messages_with_rate_limit(self, mock_websocket):
        """Should handle multiple messages with rate limiting."""
        with freeze_time("2021-01-01 00:00:00") as frozen_time:
            limiter = RateLimiter(max_rate=10, burst=3)
            client = ClientConnection(mock_websocket, limiter)

            # Send 3 messages (should all succeed - using burst)
            for i in range(3):
                result = await client.send_message({"msg": i})
                assert result is True

            # 4th message should be rate limited
            result = await client.send_message({"msg": 4})
            assert result is False

            # Advance time to refill tokens
            frozen_time.move_to("2021-01-01 00:00:01")

            # Should be able to send again
            result = await client.send_message({"msg": 5})
            assert result is True

    @pytest.mark.asyncio
    async def test_connected_at_timestamp(self):
        """Should record connection timestamp."""
        with freeze_time("2021-01-01 12:30:45"):
            ws = AsyncMock()
            limiter = RateLimiter(max_rate=10, burst=20)
            client = ClientConnection(ws, limiter)

            assert client.connected_at == datetime(2021, 1, 1, 12, 30, 45)
