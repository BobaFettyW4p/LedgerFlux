"""Unit tests for Snapshotter application."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from services.snapshotter.app import Snapshotter
from services.common.models import Tick, TickFields, TradeData


@pytest.fixture
def snapshotter_config():
    """Create a sample snapshotter config."""
    return {
        "shard_id": 0,
        "num_shards": 4,
        "snapshot_period_ms": 60000,
        "input_stream": "market.ticks",
        "stream_name": "market_ticks",
        "pg_dsn": "postgresql://test:test@localhost/test",
        "health_port": 8082,
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
            best_ask=TradeData(px=50005.0, qty=0.8),
        ),
    )


class TestSnapshotterInitialization:
    """Test suite for Snapshotter initialization."""

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    def test_init_with_explicit_shard_id(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test initialization with explicit shard ID."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)

        assert snapshotter.shard_id == 0
        assert snapshotter.num_shards == 4
        assert snapshotter.snapshot_period_ms == 60000
        assert snapshotter.input_stream == "market.ticks"
        assert snapshotter.stream_name == "market_ticks"
        assert snapshotter.pg_dsn == "postgresql://test:test@localhost/test"
        assert snapshotter.health_port == 8082
        assert snapshotter.product_states == {}
        assert snapshotter.last_snapshots == {}
        assert snapshotter.stats["messages_processed"] == 0
        assert snapshotter.stats["snapshots_created"] == 0
        assert snapshotter._store_ready is False
        assert snapshotter._broker_ready is False
        assert snapshotter._ready is False

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    def test_init_with_defaults(
        self, mock_store_class, mock_broker_class, mock_load_config
    ):
        """Test initialization with default values."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter({})

        assert snapshotter.shard_id == 0
        assert snapshotter.num_shards == 4
        assert snapshotter.snapshot_period_ms == 60000
        assert snapshotter.input_stream == "market.ticks"
        assert snapshotter.pg_dsn is None

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    @patch.dict("os.environ", {"HOSTNAME": "snapshotter-pod-2"})
    def test_init_auto_shard_from_hostname(
        self, mock_store_class, mock_broker_class, mock_load_config
    ):
        """Test auto shard ID detection from HOSTNAME."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        config = {"shard_id": "auto"}
        snapshotter = Snapshotter(config)

        assert snapshotter.shard_id == 2

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    @patch.dict("os.environ", {"HOSTNAME": "no-number-here"})
    def test_init_auto_shard_no_match(
        self, mock_store_class, mock_broker_class, mock_load_config
    ):
        """Test auto shard ID when hostname has no number."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        config = {"shard_id": "auto"}
        snapshotter = Snapshotter(config)

        assert snapshotter.shard_id == 0  # Falls back to 0


class TestSnapshotterProductState:
    """Test suite for product state management."""

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_update_product_state_new_product(
        self,
        mock_store_class,
        mock_broker_class,
        mock_load_config,
        snapshotter_config,
        sample_tick,
    ):
        """Test updating state for a new product."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)
        snapshotter._store_ready = True

        with patch.object(snapshotter, "_write_to_pg", new_callable=AsyncMock):
            await snapshotter._update_product_state(sample_tick)

        assert "BTC-USD" in snapshotter.product_states
        state = snapshotter.product_states["BTC-USD"]
        assert state["last_trade"]["px"] == 50000.0
        assert state["last_trade"]["qty"] == 0.5
        assert state["best_bid"]["px"] == 49995.0
        assert state["best_bid"]["qty"] == 1.2
        assert state["best_ask"]["px"] == 50005.0
        assert state["best_ask"]["qty"] == 0.8
        assert state["last_seq"] == 12345
        assert snapshotter.stats["states_updated"] == 1

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_update_product_state_existing_product(
        self,
        mock_store_class,
        mock_broker_class,
        mock_load_config,
        snapshotter_config,
        sample_tick,
    ):
        """Test updating state for an existing product."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)
        snapshotter._store_ready = True

        with patch.object(snapshotter, "_write_to_pg", new_callable=AsyncMock):
            # First update
            await snapshotter._update_product_state(sample_tick)

            # Second update with different values
            sample_tick.seq = 12346
            sample_tick.fields.last_trade.px = 50100.0
            await snapshotter._update_product_state(sample_tick)

        state = snapshotter.product_states["BTC-USD"]
        assert state["last_trade"]["px"] == 50100.0
        assert state["last_seq"] == 12346
        assert snapshotter.stats["states_updated"] == 2

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_update_product_state_partial_fields(
        self,
        mock_store_class,
        mock_broker_class,
        mock_load_config,
        snapshotter_config,
        sample_tick,
    ):
        """Test updating state with partial field data."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)
        snapshotter._store_ready = True

        # First update with all fields
        with patch.object(snapshotter, "_write_to_pg", new_callable=AsyncMock):
            await snapshotter._update_product_state(sample_tick)

        # Second update with only last_trade
        sample_tick.fields.best_bid = None
        sample_tick.fields.best_ask = None
        sample_tick.seq = 12346

        with patch.object(snapshotter, "_write_to_pg", new_callable=AsyncMock):
            await snapshotter._update_product_state(sample_tick)

        state = snapshotter.product_states["BTC-USD"]
        # Last trade should be updated
        assert state["last_seq"] == 12346
        # Bid/ask should remain from first update (not cleared)
        assert state["best_bid"]["px"] == 49995.0
        assert state["best_ask"]["px"] == 50005.0


class TestSnapshotterSnapshotLogic:
    """Test suite for snapshot creation logic."""

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    def test_should_create_snapshot_first_time(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test snapshot should be created for first time."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)

        assert snapshotter._should_create_snapshot("BTC-USD") is True

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    def test_should_create_snapshot_period_elapsed(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test snapshot should be created after period elapsed."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)
        # Set last snapshot to 70 seconds ago (period is 60 seconds)
        snapshotter.last_snapshots["BTC-USD"] = datetime.now() - timedelta(seconds=70)

        assert snapshotter._should_create_snapshot("BTC-USD") is True

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    def test_should_create_snapshot_period_not_elapsed(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test snapshot should not be created before period elapsed."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)
        # Set last snapshot to 30 seconds ago (period is 60 seconds)
        snapshotter.last_snapshots["BTC-USD"] = datetime.now() - timedelta(seconds=30)

        assert snapshotter._should_create_snapshot("BTC-USD") is False

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_create_snapshot(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test creating a snapshot."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker.publish_snapshot = AsyncMock()
        mock_broker_class.return_value = mock_broker

        snapshotter = Snapshotter(snapshotter_config)

        # Set up product state
        snapshotter.product_states["BTC-USD"] = {
            "last_trade": {"px": 50000.0, "qty": 0.5},
            "best_bid": {"px": 49995.0, "qty": 1.2},
            "best_ask": {"px": 50005.0, "qty": 0.8},
            "last_seq": 12345,
            "last_update": datetime.now(),
        }

        await snapshotter._create_snapshot("BTC-USD")

        assert snapshotter.stats["snapshots_created"] == 1
        assert "BTC-USD" in snapshotter.last_snapshots
        mock_broker.publish_snapshot.assert_called_once()

        # Check the snapshot that was published
        call_args = mock_broker.publish_snapshot.call_args
        snapshot = call_args[0][0]
        assert snapshot.product == "BTC-USD"
        assert snapshot.seq == 12345

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_create_snapshot_no_state(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test creating snapshot when no state exists."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker.publish_snapshot = AsyncMock()
        mock_broker_class.return_value = mock_broker

        snapshotter = Snapshotter(snapshotter_config)

        # Try to create snapshot without state
        await snapshotter._create_snapshot("BTC-USD")

        # Should not publish or create snapshot
        assert snapshotter.stats["snapshots_created"] == 0
        mock_broker.publish_snapshot.assert_not_called()


class TestSnapshotterPersistence:
    """Test suite for Postgres persistence."""

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_write_to_pg_success(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test successful write to Postgres."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_store = AsyncMock()
        mock_store.upsert_latest = AsyncMock()
        mock_store_class.return_value = mock_store

        snapshotter = Snapshotter(snapshotter_config)
        snapshotter._store_ready = True

        state = {
            "last_seq": 12345,
            "last_update": datetime.now(),
            "last_trade": {"px": 50000.0, "qty": 0.5},
        }

        await snapshotter._write_to_pg("BTC-USD", state)

        assert snapshotter.stats["pg_writes"] == 1
        mock_store.upsert_latest.assert_called_once()

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_write_to_pg_store_not_ready(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test write when store is not ready."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_store = AsyncMock()
        mock_store.upsert_latest = AsyncMock()
        mock_store_class.return_value = mock_store

        snapshotter = Snapshotter(snapshotter_config)
        snapshotter._store_ready = False

        state = {"last_seq": 12345, "last_update": datetime.now()}

        await snapshotter._write_to_pg("BTC-USD", state)

        # Should not write
        assert snapshotter.stats["pg_writes"] == 0
        mock_store.upsert_latest.assert_not_called()

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_write_to_pg_error_handling(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test error handling during Postgres write."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_store = AsyncMock()
        mock_store.upsert_latest = AsyncMock(side_effect=Exception("Write failed"))
        mock_store_class.return_value = mock_store

        snapshotter = Snapshotter(snapshotter_config)
        snapshotter._store_ready = True

        state = {"last_seq": 12345, "last_update": datetime.now()}

        await snapshotter._write_to_pg("BTC-USD", state)

        # Should handle error gracefully
        assert snapshotter.stats["errors"] == 1

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_init_store_success(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test successful store initialization."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_store = AsyncMock()
        mock_store.ensure_schema = AsyncMock()
        mock_store_class.return_value = mock_store

        snapshotter = Snapshotter(snapshotter_config)

        await snapshotter._init_store()

        assert snapshotter._store_ready is True
        mock_store.ensure_schema.assert_called_once()

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_init_store_failure(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test store initialization failure."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_store = AsyncMock()
        mock_store.ensure_schema = AsyncMock(side_effect=Exception("Connection failed"))
        mock_store_class.return_value = mock_store

        snapshotter = Snapshotter(snapshotter_config)

        await snapshotter._init_store()

        assert snapshotter._store_ready is False


class TestSnapshotterProcessing:
    """Test suite for tick processing."""

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_process_tick_success(
        self,
        mock_store_class,
        mock_broker_class,
        mock_load_config,
        snapshotter_config,
        sample_tick,
    ):
        """Test successful tick processing."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)
        snapshotter._store_ready = True

        with patch.object(
            snapshotter, "_update_product_state", new_callable=AsyncMock
        ) as mock_update:
            with patch.object(
                snapshotter, "_write_tick_history", new_callable=AsyncMock
            ):
                with patch.object(
                    snapshotter, "_should_create_snapshot", return_value=False
                ):
                    await snapshotter._process_tick(sample_tick)

        assert snapshotter.stats["messages_processed"] == 1
        mock_update.assert_called_once_with(sample_tick)

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_process_tick_creates_snapshot(
        self,
        mock_store_class,
        mock_broker_class,
        mock_load_config,
        snapshotter_config,
        sample_tick,
    ):
        """Test tick processing triggers snapshot creation."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)
        snapshotter._store_ready = True

        with patch.object(snapshotter, "_update_product_state", new_callable=AsyncMock):
            with patch.object(
                snapshotter, "_write_tick_history", new_callable=AsyncMock
            ):
                with patch.object(
                    snapshotter, "_should_create_snapshot", return_value=True
                ):
                    with patch.object(
                        snapshotter, "_create_snapshot", new_callable=AsyncMock
                    ) as mock_create:
                        await snapshotter._process_tick(sample_tick)

        mock_create.assert_called_once_with("BTC-USD")

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_process_tick_error_handling(
        self,
        mock_store_class,
        mock_broker_class,
        mock_load_config,
        snapshotter_config,
        sample_tick,
    ):
        """Test error handling during tick processing."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)

        with patch.object(
            snapshotter,
            "_update_product_state",
            new_callable=AsyncMock,
            side_effect=Exception("Update failed"),
        ):
            await snapshotter._process_tick(sample_tick)

        assert snapshotter.stats["errors"] == 1

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_process_tick_stats_printing(
        self,
        mock_store_class,
        mock_broker_class,
        mock_load_config,
        snapshotter_config,
        sample_tick,
    ):
        """Test that stats are printed every 100 messages."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)
        snapshotter._store_ready = True

        with patch.object(snapshotter, "_update_product_state", new_callable=AsyncMock):
            with patch.object(
                snapshotter, "_write_tick_history", new_callable=AsyncMock
            ):
                with patch.object(
                    snapshotter, "_should_create_snapshot", return_value=False
                ):
                    # Process 100 ticks
                    for i in range(100):
                        await snapshotter._process_tick(sample_tick)

        assert snapshotter.stats["messages_processed"] == 100


class TestSnapshotterHealthEndpoints:
    """Test health endpoints."""

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    def test_health_endpoint(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test health endpoint."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)
        snapshotter.stats["messages_processed"] = 100
        snapshotter.stats["snapshots_created"] = 10
        snapshotter.stats["errors"] = 2

        client = TestClient(snapshotter.health_app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["messages_processed"] == 100
        assert data["snapshots_created"] == 10
        assert data["errors"] == 2

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    def test_ready_endpoint_not_ready(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test ready endpoint when not ready."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)

        client = TestClient(snapshotter.health_app)
        response = client.get("/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["broker"] == "disconnected"
        assert data["store"] == "not_ready"

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    def test_ready_endpoint_ready(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test ready endpoint when ready."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        snapshotter = Snapshotter(snapshotter_config)
        snapshotter._ready = True
        snapshotter._store_ready = True
        snapshotter._broker_ready = True

        client = TestClient(snapshotter.health_app)
        response = client.get("/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["broker"] == "connected"
        assert data["store"] == "ready"


class TestSnapshotterLifecycle:
    """Test snapshotter lifecycle."""

    @patch("services.snapshotter.app.load_nats_config")
    @patch("services.snapshotter.app.NATSStreamManager")
    @patch("services.snapshotter.app.PostgresSnapshotStore")
    async def test_stop(
        self, mock_store_class, mock_broker_class, mock_load_config, snapshotter_config
    ):
        """Test stopping the snapshotter."""
        mock_nats_config = MagicMock()
        mock_load_config.return_value = mock_nats_config

        mock_broker = AsyncMock()
        mock_broker_class.return_value = mock_broker

        mock_store = AsyncMock()
        mock_store_class.return_value = mock_store

        snapshotter = Snapshotter(snapshotter_config)

        with patch.object(
            snapshotter, "_stop_health_server", new_callable=AsyncMock
        ) as mock_stop_health:
            await snapshotter.stop()

        mock_broker.disconnect.assert_called_once()
        mock_store.close.assert_called_once()
        mock_stop_health.assert_called_once()
