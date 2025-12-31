"""Tests for utility functions in services/common/util.py"""

import pytest
from services.common.util import (
    shard_index,
    shard_product,
    stable_hash,
    get_shard_subject,
    validate_product_list,
    format_quantity,
)


class TestSharding:
    """Test sharding logic for consistency and correctness."""

    def test_shard_index_consistency(self):
        """Same product should always map to same shard."""
        product = "BTC-USD"
        num_shards = 4

        shard1 = shard_index(product, num_shards)
        shard2 = shard_index(product, num_shards)
        shard3 = shard_index(product, num_shards)

        assert shard1 == shard2 == shard3

    def test_shard_index_distribution(self):
        """Products should distribute across all shards."""
        products = [f"PROD-{i}" for i in range(100)]
        num_shards = 4

        shard_counts = {i: 0 for i in range(num_shards)}

        for product in products:
            shard = shard_index(product, num_shards)
            shard_counts[shard] += 1

        # Each shard should have at least some products
        for count in shard_counts.values():
            assert count > 0

        # Should be roughly balanced (within 2x of average)
        avg = 100 / num_shards
        for count in shard_counts.values():
            assert count > avg / 2
            assert count < avg * 2

    def test_shard_index_bounds(self):
        """Shard index should always be within bounds."""
        products = ["BTC-USD", "ETH-USD", "SOL-USD"]

        for num_shards in [2, 4, 8, 16]:
            for product in products:
                shard = shard_index(product, num_shards)
                assert 0 <= shard < num_shards

    def test_shard_product_alias(self):
        """shard_product should behave identically to shard_index."""
        product = "BTC-USD"
        num_shards = 4

        assert shard_product(product, num_shards) == shard_index(product, num_shards)


class TestStableHash:
    """Test stable hashing function."""

    def test_stable_hash_deterministic(self):
        """Hash should be deterministic."""
        value = "test-value"

        hash1 = stable_hash(value)
        hash2 = stable_hash(value)

        assert hash1 == hash2
        assert len(hash1) == 16

    def test_stable_hash_different_values(self):
        """Different values should produce different hashes."""
        hash1 = stable_hash("value1")
        hash2 = stable_hash("value2")

        assert hash1 != hash2

    def test_stable_hash_empty_string(self):
        """Should handle empty string."""
        hash_result = stable_hash("")
        assert len(hash_result) == 16


class TestGetShardSubject:
    """Test NATS subject generation with sharding."""

    def test_get_shard_subject_default(self):
        """Should generate subject with default base."""
        product = "BTC-USD"
        num_shards = 4

        subject = get_shard_subject(product, num_shards)

        # Should start with default base
        assert subject.startswith("market.ticks.")

        # Should end with shard number
        shard = shard_index(product, num_shards)
        assert subject == f"market.ticks.{shard}"

    def test_get_shard_subject_custom_base(self):
        """Should generate subject with custom base."""
        product = "ETH-USD"
        num_shards = 4
        base = "custom.subject"

        subject = get_shard_subject(product, num_shards, base)

        # Should start with custom base
        assert subject.startswith(base + ".")

        # Should end with shard number
        shard = shard_index(product, num_shards)
        assert subject == f"{base}.{shard}"


class TestValidateProductList:
    """Test product list validation and normalization."""

    def test_validate_product_list_valid(self):
        """Should normalize valid product list."""
        products = ["btc-usd", "ETH-USD", "  ada-usd  "]

        result = validate_product_list(products)

        assert result == ["BTC-USD", "ETH-USD", "ADA-USD"]

    def test_validate_product_list_empty(self):
        """Should raise error on empty list."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_product_list([])

    def test_validate_product_list_invalid_product(self):
        """Should raise error on invalid product."""
        with pytest.raises(ValueError, match="Invalid product"):
            validate_product_list(["BTC-USD", None, "ETH-USD"])

    def test_validate_product_list_empty_string(self):
        """Should raise error on empty string product."""
        with pytest.raises(ValueError, match="Invalid product"):
            validate_product_list(["BTC-USD", "", "ETH-USD"])

    def test_validate_product_list_whitespace_only(self):
        """Should raise error on whitespace-only product."""
        with pytest.raises(ValueError, match="Empty product after normalization"):
            validate_product_list(["BTC-USD", "   ", "ETH-USD"])

    def test_validate_product_list_non_string(self):
        """Should raise error on non-string product."""
        with pytest.raises(ValueError, match="Invalid product"):
            validate_product_list(["BTC-USD", 123, "ETH-USD"])


class TestFormatQuantity:
    """Test quantity formatting."""

    def test_format_quantity_default_precision(self):
        """Should format with default 8 decimal places."""
        result = format_quantity(1.23456789123)
        # Should round to 8 decimals
        assert result == "1.23456789"

    def test_format_quantity_custom_precision(self):
        """Should format with custom precision."""
        result = format_quantity(1.23456789, precision=4)
        assert result == "1.2346"

    def test_format_quantity_normalize(self):
        """Should normalize trailing zeros."""
        result = format_quantity(1.50000000, precision=8)
        # normalize() should remove trailing zeros
        assert result == "1.5"

    def test_format_quantity_zero(self):
        """Should handle zero correctly."""
        result = format_quantity(0.0)
        assert result == "0"

    def test_format_quantity_large_number(self):
        """Should handle large numbers."""
        result = format_quantity(123456.789, precision=2)
        assert result == "123456.79"

    def test_format_quantity_rounding(self):
        """Should round half up."""
        # Test ROUND_HALF_UP behavior
        result1 = format_quantity(1.2345, precision=3)
        assert result1 == "1.235"  # 0.0005 rounds up

        result2 = format_quantity(1.2344, precision=3)
        assert result2 == "1.234"  # 0.0004 rounds down
