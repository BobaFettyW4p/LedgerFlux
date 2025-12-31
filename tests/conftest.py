"""Root test configuration with shared fixtures."""
import asyncio
import pytest
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_nats_connection():
    """Mock NATS connection."""
    mock_conn = AsyncMock()
    mock_conn.is_closed = False
    mock_conn.jetstream = MagicMock(return_value=AsyncMock())
    return mock_conn


@pytest.fixture
def mock_jetstream():
    """Mock JetStream context."""
    mock_js = AsyncMock()
    mock_js.publish = AsyncMock()
    mock_js.pull_subscribe = AsyncMock()
    mock_js.stream_info = AsyncMock()
    mock_js.add_stream = AsyncMock()
    mock_js.delete_stream = AsyncMock()
    return mock_js


@pytest.fixture
def mock_postgres_connection():
    """Mock PostgreSQL async connection."""
    mock_conn = AsyncMock()
    mock_conn.cursor = AsyncMock()
    return mock_conn


@pytest.fixture
def mock_websocket():
    """Mock WebSocket for client connections."""
    mock_ws = AsyncMock()
    mock_ws.accept = AsyncMock()
    mock_ws.send_text = AsyncMock()
    mock_ws.receive_text = AsyncMock()
    return mock_ws
