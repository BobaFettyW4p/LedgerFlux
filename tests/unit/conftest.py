"""Unit test specific fixtures."""
import pytest
from datetime import datetime
from services.common.models import Tick


@pytest.fixture
def sample_tick_data():
    """Sample tick data for testing."""
    return {
        "v": 1,
        "type": "tick",
        "product": "BTC-USD",
        "seq": 12345,
        "ts_event": 1609459200000000000,
        "ts_ingest": 1609459200100000000,
        "fields": {
            "last_trade": {"px": 50000.0, "qty": 0.5},
            "best_bid": {"px": 49995.0, "qty": 1.2},
            "best_ask": {"px": 50005.0, "qty": 0.8}
        }
    }


@pytest.fixture
def sample_tick(sample_tick_data):
    """Sample Tick model instance."""
    return Tick.model_validate(sample_tick_data)


@pytest.fixture
def sample_coinbase_ticker():
    """Sample Coinbase ticker message."""
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
        "time": "2021-01-01T00:00:00.000000Z"
    }


@pytest.fixture
def sample_snapshot_state():
    """Sample snapshot state."""
    return {
        "last_trade": {"px": 50000.0, "qty": 0.5, "ts": 1609459200000000000},
        "best_bid": {"px": 49995.0, "qty": 1.2, "ts": 1609459200000000000},
        "best_ask": {"px": 50005.0, "qty": 0.8, "ts": 1609459200000000000},
        "last_seq": 12345,
        "last_update": datetime(2021, 1, 1)
    }
