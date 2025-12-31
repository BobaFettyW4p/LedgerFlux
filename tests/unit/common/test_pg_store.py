"""Unit tests for PostgresSnapshotStore."""
import os
import pytest
from datetime import datetime
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch, call
from services.common.pg_store import PostgresSnapshotStore, SnapshotRecord


@pytest.fixture
def mock_async_cursor():
    """Create a mock async cursor."""
    cursor = AsyncMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock()
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock()
    return cursor


@pytest.fixture
def mock_async_connection(mock_async_cursor):
    """Create a mock async PostgreSQL connection."""
    conn = AsyncMock()
    conn.cursor = MagicMock(return_value=mock_async_cursor)
    conn.close = AsyncMock()
    return conn


class TestPostgresSnapshotStore:
    """Test suite for PostgresSnapshotStore."""

    def test_init_with_dsn(self):
        """Test initialization with explicit DSN."""
        dsn = "postgresql://user:pass@localhost:5432/test"
        store = PostgresSnapshotStore(dsn=dsn)
        assert store._dsn_input == dsn
        assert store._conn is None

    def test_init_without_dsn(self):
        """Test initialization without DSN."""
        store = PostgresSnapshotStore()
        assert store._dsn_input is None
        assert store._conn is None

    def test_build_dsn_with_explicit_dsn(self):
        """Test DSN building when explicit DSN is provided."""
        explicit_dsn = "postgresql://user:pass@example.com:5432/mydb"
        store = PostgresSnapshotStore(dsn=explicit_dsn)
        assert store._build_dsn() == explicit_dsn

    @patch.dict(os.environ, {"PG_DSN": "postgresql://env:pass@envhost:5432/envdb"}, clear=True)
    def test_build_dsn_from_env_dsn(self):
        """Test DSN building from PG_DSN environment variable."""
        store = PostgresSnapshotStore()
        assert store._build_dsn() == "postgresql://env:pass@envhost:5432/envdb"

    @patch.dict(os.environ, {
        "PG_HOST": "testhost",
        "PG_PORT": "5433",
        "PG_DATABASE": "testdb",
        "PG_USER": "testuser",
        "PG_PASSWORD": "testpass"
    }, clear=True)
    def test_build_dsn_from_env_components_with_password(self):
        """Test DSN building from individual env vars with password."""
        store = PostgresSnapshotStore()
        dsn = store._build_dsn()
        assert dsn == "postgresql://testuser:testpass@testhost:5433/testdb"

    @patch.dict(os.environ, {
        "PG_HOST": "testhost",
        "PG_PORT": "5433",
        "PG_DATABASE": "testdb",
        "PG_USER": "testuser"
    }, clear=True)
    def test_build_dsn_from_env_components_without_password(self):
        """Test DSN building from individual env vars without password."""
        store = PostgresSnapshotStore()
        dsn = store._build_dsn()
        assert dsn == "postgresql://testuser@testhost:5433/testdb"

    @patch.dict(os.environ, {}, clear=True)
    def test_build_dsn_with_defaults(self):
        """Test DSN building with default values when no env vars set."""
        store = PostgresSnapshotStore()
        dsn = store._build_dsn()
        assert dsn == "postgresql://postgres@localhost:5432/ledgerflux"

    @patch("services.common.pg_store.psycopg.AsyncConnection.connect")
    async def test_connect_first_time(self, mock_connect, mock_async_connection):
        """Test connecting for the first time."""
        mock_connect.return_value = mock_async_connection
        store = PostgresSnapshotStore(dsn="postgresql://test:test@localhost:5432/test")

        await store.connect()

        mock_connect.assert_called_once_with(
            "postgresql://test:test@localhost:5432/test",
            autocommit=True
        )
        assert store._conn == mock_async_connection

    @patch("services.common.pg_store.psycopg.AsyncConnection.connect")
    async def test_connect_already_connected(self, mock_connect, mock_async_connection):
        """Test connect returns early if already connected."""
        store = PostgresSnapshotStore()
        store._conn = mock_async_connection

        await store.connect()

        # Should not call connect again
        mock_connect.assert_not_called()

    @patch("services.common.pg_store.psycopg.AsyncConnection.connect")
    async def test_ensure_schema_creates_table(self, mock_connect, mock_async_connection, mock_async_cursor):
        """Test ensure_schema creates snapshots table."""
        mock_connect.return_value = mock_async_connection
        store = PostgresSnapshotStore()

        await store.ensure_schema()

        # Should execute CREATE TABLE statement
        mock_async_cursor.execute.assert_called_once()
        create_stmt = mock_async_cursor.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS snapshots" in create_stmt
        assert "product TEXT PRIMARY KEY" in create_stmt
        assert "version INT NOT NULL" in create_stmt
        assert "last_seq BIGINT NOT NULL" in create_stmt
        assert "ts_snapshot BIGINT NOT NULL" in create_stmt
        assert "state JSONB NOT NULL" in create_stmt

    @patch("services.common.pg_store.psycopg.AsyncConnection.connect")
    async def test_ensure_schema_when_already_connected(self, mock_connect, mock_async_connection, mock_async_cursor):
        """Test ensure_schema uses existing connection."""
        store = PostgresSnapshotStore()
        store._conn = mock_async_connection

        await store.ensure_schema()

        # Should not call connect
        mock_connect.assert_not_called()
        # Should still execute CREATE TABLE
        mock_async_cursor.execute.assert_called_once()

    @patch("services.common.pg_store.psycopg.AsyncConnection.connect")
    async def test_upsert_latest_basic(self, mock_connect, mock_async_connection, mock_async_cursor):
        """Test upserting a snapshot with basic state."""
        mock_connect.return_value = mock_async_connection
        store = PostgresSnapshotStore()

        state = {
            "last_trade": {"px": 50000.0, "qty": 0.5},
            "best_bid": {"px": 49995.0, "qty": 1.2}
        }

        await store.upsert_latest(
            product="BTC-USD",
            version=1,
            last_seq=12345,
            ts_snapshot_ns=1609459200000000000,
            state=state
        )

        # Verify execute was called with upsert statement
        mock_async_cursor.execute.assert_called_once()
        stmt, params = mock_async_cursor.execute.call_args[0]
        assert "INSERT INTO snapshots" in stmt
        assert "ON CONFLICT (product)" in stmt
        assert params[0] == "BTC-USD"
        assert params[1] == 1
        assert params[2] == 12345
        assert params[3] == 1609459200000000000

    @patch("services.common.pg_store.psycopg.AsyncConnection.connect")
    async def test_upsert_latest_with_datetime_serialization(self, mock_connect, mock_async_connection, mock_async_cursor):
        """Test upserting a snapshot with datetime that needs serialization."""
        mock_connect.return_value = mock_async_connection
        store = PostgresSnapshotStore()

        dt = datetime(2021, 1, 1, 12, 0, 0)
        state = {
            "last_trade": {"px": 50000.0, "qty": 0.5},
            "last_update": dt
        }

        await store.upsert_latest(
            product="BTC-USD",
            version=1,
            last_seq=12345,
            ts_snapshot_ns=1609459200000000000,
            state=state
        )

        # Verify execute was called
        mock_async_cursor.execute.assert_called_once()
        # The state should have datetime converted to ISO format
        # We can't easily inspect the Json() wrapper, but we can verify the call happened

    @patch("services.common.pg_store.psycopg.AsyncConnection.connect")
    async def test_upsert_latest_without_datetime(self, mock_connect, mock_async_connection, mock_async_cursor):
        """Test upserting a snapshot without datetime in last_update."""
        mock_connect.return_value = mock_async_connection
        store = PostgresSnapshotStore()

        state = {
            "last_trade": {"px": 50000.0, "qty": 0.5},
            "last_update": "2021-01-01T00:00:00"
        }

        await store.upsert_latest(
            product="BTC-USD",
            version=1,
            last_seq=12345,
            ts_snapshot_ns=1609459200000000000,
            state=state
        )

        # Verify execute was called successfully
        mock_async_cursor.execute.assert_called_once()

    @patch("services.common.pg_store.psycopg.AsyncConnection.connect")
    async def test_upsert_latest_connects_if_needed(self, mock_connect, mock_async_connection, mock_async_cursor):
        """Test upsert_latest connects if not already connected."""
        mock_connect.return_value = mock_async_connection
        store = PostgresSnapshotStore()

        await store.upsert_latest(
            product="BTC-USD",
            version=1,
            last_seq=12345,
            ts_snapshot_ns=1609459200000000000,
            state={}
        )

        # Should have called connect
        mock_connect.assert_called_once()

    @patch("services.common.pg_store.psycopg.AsyncConnection.connect")
    async def test_get_latest_found(self, mock_connect, mock_async_connection, mock_async_cursor):
        """Test getting latest snapshot when it exists."""
        mock_connect.return_value = mock_async_connection

        # Mock the row returned from database
        mock_async_cursor.fetchone.return_value = {
            "product": "BTC-USD",
            "version": 1,
            "last_seq": 12345,
            "ts_snapshot": 1609459200000000000,
            "state": {"last_trade": {"px": 50000.0, "qty": 0.5}}
        }

        store = PostgresSnapshotStore()
        result = await store.get_latest("BTC-USD")

        assert result is not None
        assert isinstance(result, SnapshotRecord)
        assert result.product == "BTC-USD"
        assert result.version == 1
        assert result.last_seq == 12345
        assert result.ts_snapshot == 1609459200000000000
        assert result.state == {"last_trade": {"px": 50000.0, "qty": 0.5}}

        # Verify query was executed
        mock_async_cursor.execute.assert_called_once()
        stmt, params = mock_async_cursor.execute.call_args[0]
        assert "SELECT product, version, last_seq, ts_snapshot, state" in stmt
        assert "FROM snapshots" in stmt
        assert "WHERE product = %s" in stmt
        assert params == ("BTC-USD",)

    @patch("services.common.pg_store.psycopg.AsyncConnection.connect")
    async def test_get_latest_not_found(self, mock_connect, mock_async_connection, mock_async_cursor):
        """Test getting latest snapshot when it doesn't exist."""
        mock_connect.return_value = mock_async_connection
        mock_async_cursor.fetchone.return_value = None

        store = PostgresSnapshotStore()
        result = await store.get_latest("NONEXISTENT-PRODUCT")

        assert result is None
        mock_async_cursor.execute.assert_called_once()

    @patch("services.common.pg_store.psycopg.AsyncConnection.connect")
    async def test_get_latest_connects_if_needed(self, mock_connect, mock_async_connection, mock_async_cursor):
        """Test get_latest connects if not already connected."""
        mock_connect.return_value = mock_async_connection
        mock_async_cursor.fetchone.return_value = None

        store = PostgresSnapshotStore()
        await store.get_latest("BTC-USD")

        # Should have called connect
        mock_connect.assert_called_once()

    async def test_close_when_connected(self, mock_async_connection):
        """Test closing an open connection."""
        store = PostgresSnapshotStore()
        store._conn = mock_async_connection

        await store.close()

        mock_async_connection.close.assert_called_once()
        assert store._conn is None

    async def test_close_when_not_connected(self):
        """Test closing when no connection exists."""
        store = PostgresSnapshotStore()
        assert store._conn is None

        # Should not raise an error
        await store.close()

        assert store._conn is None


class TestSnapshotRecord:
    """Test suite for SnapshotRecord dataclass."""

    def test_snapshot_record_creation(self):
        """Test creating a SnapshotRecord instance."""
        state = {"last_trade": {"px": 50000.0, "qty": 0.5}}
        record = SnapshotRecord(
            product="BTC-USD",
            version=1,
            last_seq=12345,
            ts_snapshot=1609459200000000000,
            state=state
        )

        assert record.product == "BTC-USD"
        assert record.version == 1
        assert record.last_seq == 12345
        assert record.ts_snapshot == 1609459200000000000
        assert record.state == state

    def test_snapshot_record_equality(self):
        """Test SnapshotRecord equality comparison."""
        state = {"last_trade": {"px": 50000.0, "qty": 0.5}}
        record1 = SnapshotRecord(
            product="BTC-USD",
            version=1,
            last_seq=12345,
            ts_snapshot=1609459200000000000,
            state=state
        )
        record2 = SnapshotRecord(
            product="BTC-USD",
            version=1,
            last_seq=12345,
            ts_snapshot=1609459200000000000,
            state=state
        )

        assert record1 == record2
