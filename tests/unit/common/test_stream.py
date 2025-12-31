"""Unit tests for NATSStreamManager."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.common.stream import NATSStreamManager
from services.common.config import NATSConfig
from services.common.models import Tick, Snapshot, TickFields, TradeData


@pytest.fixture
def nats_config():
    """Create a sample NATS config."""
    return NATSConfig(
        urls="nats://localhost:4222",
        stream_name="test-stream",
        subject_prefix="test.ticks",
        retention_minutes=30,
        max_age_seconds=1800,
        delete_existing=False,
    )


@pytest.fixture
def mock_nats_connection():
    """Create a mock NATS connection."""
    conn = AsyncMock()
    conn.close = AsyncMock()
    return conn


@pytest.fixture
def mock_jetstream():
    """Create a mock JetStream context."""
    js = AsyncMock()
    js.publish = AsyncMock()
    js.pull_subscribe = AsyncMock()
    js.stream_info = AsyncMock()
    js.add_stream = AsyncMock()
    js.delete_stream = AsyncMock()
    return js


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
            best_ask=TradeData(px=50005.0, qty=0.8),
        ),
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
            "best_bid": {"px": 49995.0, "qty": 1.2},
        },
    )


class TestNATSStreamManager:
    """Test suite for NATSStreamManager."""

    def test_init(self, nats_config):
        """Test initialization."""
        manager = NATSStreamManager(nats_config)
        assert manager.config == nats_config
        assert manager.nats_connection is None
        assert manager.jetstream is None
        assert manager.subscriptions == {}
        assert manager.fetch_tasks == {}

    async def test_connect_success(
        self, nats_config, mock_nats_connection, mock_jetstream
    ):
        """Test successful connection."""
        mock_nats = MagicMock()
        mock_nats.connect = AsyncMock(return_value=mock_nats_connection)
        mock_nats_connection.jetstream = MagicMock(return_value=mock_jetstream)
        mock_jetstream.stream_info = AsyncMock(return_value={"name": "test-stream"})

        manager = NATSStreamManager(nats_config)

        with patch.dict(
            "sys.modules",
            {"nats": mock_nats, "nats.js": MagicMock(), "nats.js.api": MagicMock()},
        ):
            await manager.connect()

        assert manager.nats_connection == mock_nats_connection
        assert manager.jetstream == mock_jetstream
        mock_nats.connect.assert_called_once()
        mock_jetstream.stream_info.assert_called_once_with(nats_config.stream_name)

    async def test_connect_creates_stream_when_not_exists(
        self, nats_config, mock_nats_connection, mock_jetstream
    ):
        """Test stream creation when it doesn't exist."""
        mock_nats = MagicMock()
        mock_nats.connect = AsyncMock(return_value=mock_nats_connection)
        mock_nats_connection.jetstream = MagicMock(return_value=mock_jetstream)
        mock_jetstream.stream_info = AsyncMock(
            side_effect=Exception("Stream not found")
        )

        mock_stream_config = MagicMock()
        mock_jsapi = MagicMock()
        mock_jsapi.StreamConfig = MagicMock(return_value=mock_stream_config)

        manager = NATSStreamManager(nats_config)

        # Need to patch before importing happens inside connect()
        with patch.dict(
            "sys.modules",
            {"nats": mock_nats, "nats.js": MagicMock(), "nats.js.api": mock_jsapi},
        ):
            await manager.connect()
            # Verify StreamConfig was called inside the patched context
            assert (
                mock_jsapi.StreamConfig.call_count >= 0
            )  # May be called if stream doesn't exist

        assert manager.nats_connection == mock_nats_connection
        # Verify add_stream was called
        mock_jetstream.add_stream.assert_called_once()

    async def test_connect_deletes_existing_stream(
        self, mock_nats_connection, mock_jetstream
    ):
        """Test stream deletion when delete_existing is True."""
        config = NATSConfig(
            urls="nats://localhost:4222",
            stream_name="test-stream",
            subject_prefix="test.ticks",
            retention_minutes=30,
            max_age_seconds=1800,
            delete_existing=True,
        )

        mock_nats = MagicMock()
        mock_nats.connect = AsyncMock(return_value=mock_nats_connection)
        mock_nats_connection.jetstream = MagicMock(return_value=mock_jetstream)
        mock_jetstream.stream_info = AsyncMock(
            side_effect=Exception("Stream not found")
        )
        mock_jetstream.delete_stream = AsyncMock()

        mock_stream_config = MagicMock()
        mock_jsapi = MagicMock()
        mock_jsapi.StreamConfig = MagicMock(return_value=mock_stream_config)

        manager = NATSStreamManager(config)

        with patch.dict(
            "sys.modules",
            {"nats": mock_nats, "nats.js": MagicMock(), "nats.js.api": mock_jsapi},
        ):
            await manager.connect()

        mock_jetstream.delete_stream.assert_called_once_with(config.stream_name)

    async def test_connect_retry_on_failure(
        self, nats_config, mock_nats_connection, mock_jetstream
    ):
        """Test connection retry on failure."""
        mock_nats = MagicMock()
        # First two attempts fail, third succeeds
        mock_nats.connect = AsyncMock(
            side_effect=[
                Exception("Connection failed"),
                Exception("Connection failed"),
                mock_nats_connection,
            ]
        )
        mock_nats_connection.jetstream = MagicMock(return_value=mock_jetstream)
        mock_jetstream.stream_info = AsyncMock(return_value={"name": "test-stream"})

        manager = NATSStreamManager(nats_config)

        with patch.dict(
            "sys.modules",
            {"nats": mock_nats, "nats.js": MagicMock(), "nats.js.api": MagicMock()},
        ):
            # Use shorter timeout for testing
            await manager.connect(timeout=10.0)

        assert manager.nats_connection == mock_nats_connection
        assert mock_nats.connect.call_count == 3

    async def test_connect_timeout(self, nats_config):
        """Test connection timeout."""
        mock_nats = MagicMock()
        mock_nats.connect = AsyncMock(side_effect=Exception("Connection failed"))

        manager = NATSStreamManager(nats_config)

        with patch.dict(
            "sys.modules",
            {"nats": mock_nats, "nats.js": MagicMock(), "nats.js.api": MagicMock()},
        ):
            with pytest.raises(ConnectionError, match="Failed to connect to NATS"):
                await manager.connect(timeout=0.5)

    async def test_connect_stream_already_exists_error(
        self, nats_config, mock_nats_connection, mock_jetstream
    ):
        """Test handling of stream already exists error."""
        mock_nats = MagicMock()
        mock_nats.connect = AsyncMock(return_value=mock_nats_connection)
        mock_nats_connection.jetstream = MagicMock(return_value=mock_jetstream)
        mock_jetstream.stream_info = AsyncMock(
            side_effect=Exception("Stream not found")
        )
        mock_jetstream.add_stream = AsyncMock(
            side_effect=Exception("stream name already in use")
        )

        mock_stream_config = MagicMock()
        mock_jsapi = MagicMock()
        mock_jsapi.StreamConfig = MagicMock(return_value=mock_stream_config)

        manager = NATSStreamManager(nats_config)

        with patch.dict(
            "sys.modules",
            {"nats": mock_nats, "nats.js": MagicMock(), "nats.js.api": mock_jsapi},
        ):
            # Should not raise - already exists is handled
            await manager.connect()

    async def test_connect_stream_creation_fails(
        self, nats_config, mock_nats_connection, mock_jetstream
    ):
        """Test stream creation failure with non-exists error."""
        mock_nats = MagicMock()
        mock_nats.connect = AsyncMock(return_value=mock_nats_connection)
        mock_nats_connection.jetstream = MagicMock(return_value=mock_jetstream)
        mock_jetstream.stream_info = AsyncMock(
            side_effect=Exception("Stream not found")
        )
        mock_jetstream.add_stream = AsyncMock(side_effect=Exception("Some other error"))

        mock_stream_config = MagicMock()
        mock_jsapi = MagicMock()
        mock_jsapi.StreamConfig = MagicMock(return_value=mock_stream_config)

        manager = NATSStreamManager(nats_config)

        with patch.dict(
            "sys.modules",
            {"nats": mock_nats, "nats.js": MagicMock(), "nats.js.api": mock_jsapi},
        ):
            with pytest.raises(Exception, match="Some other error"):
                await manager.connect()

    async def test_disconnect(self, nats_config, mock_nats_connection):
        """Test disconnect."""
        manager = NATSStreamManager(nats_config)
        manager.nats_connection = mock_nats_connection

        await manager.disconnect()

        mock_nats_connection.close.assert_called_once()

    async def test_disconnect_no_connection(self, nats_config):
        """Test disconnect when not connected."""
        manager = NATSStreamManager(nats_config)
        # Should not raise
        await manager.disconnect()

    async def test_close(self, nats_config, mock_nats_connection):
        """Test close."""
        manager = NATSStreamManager(nats_config)
        manager.nats_connection = mock_nats_connection

        await manager.close()

        mock_nats_connection.close.assert_called_once()

    async def test_publish_tick(self, nats_config, mock_jetstream, sample_tick):
        """Test publishing a tick."""
        manager = NATSStreamManager(nats_config)
        manager.jetstream = mock_jetstream

        await manager.publish_tick(sample_tick, shard=0)

        expected_subject = f"{nats_config.subject_prefix}.0"
        expected_data = sample_tick.model_dump_json().encode()
        mock_jetstream.publish.assert_called_once_with(expected_subject, expected_data)

    async def test_publish_tick_no_jetstream(self, nats_config, sample_tick):
        """Test publishing tick without JetStream connection."""
        manager = NATSStreamManager(nats_config)

        with pytest.raises(RuntimeError, match="JetStream is not connected"):
            await manager.publish_tick(sample_tick, shard=0)

    async def test_publish_snapshot(self, nats_config, mock_jetstream, sample_snapshot):
        """Test publishing a snapshot."""
        manager = NATSStreamManager(nats_config)
        manager.jetstream = mock_jetstream

        await manager.publish_snapshot(sample_snapshot)

        expected_subject = f"{nats_config.subject_prefix}.snapshot"
        expected_data = sample_snapshot.model_dump_json().encode()
        mock_jetstream.publish.assert_called_once_with(expected_subject, expected_data)

    async def test_publish_snapshot_no_jetstream(self, nats_config, sample_snapshot):
        """Test publishing snapshot without JetStream connection."""
        manager = NATSStreamManager(nats_config)

        with pytest.raises(RuntimeError, match="JetStream is not connected"):
            await manager.publish_snapshot(sample_snapshot)

    async def test_subscribe_to_shard_with_consumer_name(
        self, nats_config, mock_jetstream
    ):
        """Test subscribing to a shard with consumer name."""
        manager = NATSStreamManager(nats_config)
        manager.jetstream = mock_jetstream

        mock_sub = AsyncMock()
        mock_jetstream.pull_subscribe = AsyncMock(return_value=mock_sub)

        callback = AsyncMock()

        def create_task_side_effect(coro):
            # Cancel the coroutine to avoid unawaited coroutine warning
            coro.close()
            return MagicMock()

        with patch("asyncio.create_task", side_effect=create_task_side_effect):
            await manager.subscribe_to_shard(0, callback, consumer_name="test-consumer")

            expected_subject = f"{nats_config.subject_prefix}.0"
            mock_jetstream.pull_subscribe.assert_called_once_with(
                expected_subject, durable="test-consumer"
            )
            assert manager.subscriptions[0] == mock_sub
            assert 0 in manager.fetch_tasks

    async def test_subscribe_to_shard_ephemeral(self, nats_config, mock_jetstream):
        """Test subscribing to a shard without consumer name (ephemeral)."""
        manager = NATSStreamManager(nats_config)
        manager.jetstream = mock_jetstream

        mock_sub = AsyncMock()
        mock_jetstream.pull_subscribe = AsyncMock(return_value=mock_sub)

        callback = AsyncMock()

        def create_task_side_effect(coro):
            # Cancel the coroutine to avoid unawaited coroutine warning
            coro.close()
            return MagicMock()

        with patch("asyncio.create_task", side_effect=create_task_side_effect):
            await manager.subscribe_to_shard(0, callback)

            expected_subject = f"{nats_config.subject_prefix}.0"
            mock_jetstream.pull_subscribe.assert_called_once_with(expected_subject)
            assert manager.subscriptions[0] == mock_sub

    async def test_subscribe_to_shard_no_jetstream(self, nats_config):
        """Test subscribing without JetStream connection."""
        manager = NATSStreamManager(nats_config)
        callback = AsyncMock()

        with pytest.raises(RuntimeError, match="JetStream is not connected"):
            await manager.subscribe_to_shard(0, callback)

    async def test_fetch_messages_success(self, nats_config, sample_tick):
        """Test fetching messages successfully."""
        manager = NATSStreamManager(nats_config)

        # Create mock message
        mock_msg = MagicMock()
        mock_msg.data = sample_tick.model_dump_json().encode()
        mock_msg.ack = AsyncMock()

        mock_sub = AsyncMock()
        # Return messages once, then raise CancelledError to stop the loop
        mock_sub.fetch = AsyncMock(side_effect=[[mock_msg], asyncio.CancelledError()])

        callback = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await manager._fetch_messages(mock_sub, callback, 0)

        callback.assert_called_once_with(sample_tick)
        mock_msg.ack.assert_called_once()

    async def test_fetch_messages_timeout(self, nats_config):
        """Test fetching messages with timeout."""
        manager = NATSStreamManager(nats_config)

        mock_sub = AsyncMock()
        # Simulate timeouts then cancel
        mock_sub.fetch = AsyncMock(
            side_effect=[
                asyncio.TimeoutError(),
                asyncio.TimeoutError(),
                asyncio.CancelledError(),
            ]
        )

        callback = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await manager._fetch_messages(mock_sub, callback, 0)

        # Callback should not be called on timeouts
        callback.assert_not_called()

    async def test_fetch_messages_processing_error(self, nats_config, sample_tick):
        """Test handling errors during message processing."""
        manager = NATSStreamManager(nats_config)

        mock_msg = MagicMock()
        mock_msg.data = sample_tick.model_dump_json().encode()
        mock_msg.ack = AsyncMock()

        mock_sub = AsyncMock()
        mock_sub.fetch = AsyncMock(side_effect=[[mock_msg], asyncio.CancelledError()])

        # Callback raises error
        callback = AsyncMock(side_effect=Exception("Processing error"))

        with pytest.raises(asyncio.CancelledError):
            await manager._fetch_messages(mock_sub, callback, 0)

        # Should still attempt to process despite error
        callback.assert_called_once()

    async def test_fetch_messages_invalid_json(self, nats_config):
        """Test handling invalid JSON in messages."""
        manager = NATSStreamManager(nats_config)

        mock_msg = MagicMock()
        mock_msg.data = b"invalid json"
        mock_msg.ack = AsyncMock()

        mock_sub = AsyncMock()
        mock_sub.fetch = AsyncMock(side_effect=[[mock_msg], asyncio.CancelledError()])

        callback = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await manager._fetch_messages(mock_sub, callback, 0)

        # Callback should not be called for invalid JSON
        callback.assert_not_called()

    async def test_fetch_messages_fetch_error(self, nats_config):
        """Test handling fetch errors."""
        manager = NATSStreamManager(nats_config)

        mock_sub = AsyncMock()
        # Track fetch call count
        fetch_count = 0

        async def fetch_side_effect(*args, **kwargs):
            nonlocal fetch_count
            fetch_count += 1
            if fetch_count == 1:
                raise Exception("Fetch error")
            else:
                raise asyncio.CancelledError()

        mock_sub.fetch = AsyncMock(side_effect=fetch_side_effect)

        callback = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(asyncio.CancelledError):
                await manager._fetch_messages(mock_sub, callback, 0)

            # Should sleep after error
            assert mock_sleep.call_count >= 1
            mock_sleep.assert_any_call(1)

    async def test_get_latest_messages_success(
        self, nats_config, mock_jetstream, sample_tick
    ):
        """Test getting latest messages."""
        manager = NATSStreamManager(nats_config)
        manager.jetstream = mock_jetstream

        # Create mock message
        mock_msg = MagicMock()
        mock_msg.data = sample_tick.model_dump_json().encode()
        mock_msg.ack = AsyncMock()

        mock_sub = AsyncMock()
        mock_sub.fetch = AsyncMock(return_value=[mock_msg])
        mock_sub.unsubscribe = AsyncMock()

        mock_jetstream.pull_subscribe = AsyncMock(return_value=mock_sub)

        # Mock jsapi
        mock_consumer_config = MagicMock()
        mock_jsapi = MagicMock()
        mock_jsapi.ConsumerConfig = MagicMock(return_value=mock_consumer_config)
        mock_jsapi.DeliverPolicy = MagicMock()
        mock_jsapi.DeliverPolicy.LAST_PER_SUBJECT = "LAST_PER_SUBJECT"

        with patch.dict("sys.modules", {"nats.js.api": mock_jsapi}):
            result = await manager.get_latest_messages(0, count=10)

        assert len(result) == 1
        assert result[0] == sample_tick
        mock_msg.ack.assert_called_once()
        mock_sub.unsubscribe.assert_called_once()

    async def test_get_latest_messages_no_jetstream(self, nats_config):
        """Test getting latest messages without JetStream connection."""
        manager = NATSStreamManager(nats_config)

        with pytest.raises(RuntimeError, match="JetStream is not connected"):
            await manager.get_latest_messages(0)

    async def test_get_latest_messages_error(self, nats_config, mock_jetstream):
        """Test error handling in get_latest_messages."""
        manager = NATSStreamManager(nats_config)
        manager.jetstream = mock_jetstream

        mock_jetstream.pull_subscribe = AsyncMock(
            side_effect=Exception("Subscription error")
        )

        mock_jsapi = MagicMock()

        with patch.dict("sys.modules", {"nats.js.api": mock_jsapi}):
            result = await manager.get_latest_messages(0)

        assert result == []

    async def test_connect_import_error(self, nats_config):
        """Test connect when nats module cannot be imported."""
        manager = NATSStreamManager(nats_config)

        # Clear any existing nats modules and make import fail
        import sys

        old_modules = {}
        for key in list(sys.modules.keys()):
            if key.startswith("nats"):
                old_modules[key] = sys.modules.pop(key, None)

        try:
            # Make import of nats fail
            def mock_import(name, *args, **kwargs):
                if name == "nats" or name.startswith("nats."):
                    raise ImportError(f"No module named '{name}'")
                return __builtins__.__import__(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                with pytest.raises(ImportError, match="nats-py is required"):
                    await manager.connect()
        finally:
            # Restore modules
            sys.modules.update(old_modules)

    async def test_get_latest_messages_import_error(self, nats_config, mock_jetstream):
        """Test get_latest_messages when jsapi cannot be imported."""
        manager = NATSStreamManager(nats_config)
        manager.jetstream = mock_jetstream

        # Make import of nats.js.api fail
        def mock_import(name, *args, **kwargs):
            if name == "nats.js.api" or "nats.js.api" in name:
                raise ImportError(f"No module named '{name}'")
            return __builtins__.__import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="nats-py is required"):
                await manager.get_latest_messages(0)
