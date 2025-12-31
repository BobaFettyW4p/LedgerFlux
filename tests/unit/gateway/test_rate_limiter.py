"""Tests for RateLimiter class in services/gateway/app.py"""
import pytest
import time
from freezegun import freeze_time
from services.gateway.app import RateLimiter


class TestRateLimiter:
    """Test token bucket rate limiting algorithm."""

    @freeze_time("2021-01-01 00:00:00")
    def test_initial_burst_tokens(self):
        """Should start with burst tokens available."""
        limiter = RateLimiter(max_rate=10, burst=20)

        # Should allow burst number of requests immediately
        for _ in range(20):
            assert limiter.is_allowed() is True

        # 21st request should be denied
        assert limiter.is_allowed() is False

    @freeze_time("2021-01-01 00:00:00")
    def test_token_refill_rate(self):
        """Tokens should refill at max_rate per second."""
        with freeze_time("2021-01-01 00:00:00") as frozen_time:
            limiter = RateLimiter(max_rate=10, burst=10)

            # Consume all tokens
            for _ in range(10):
                limiter.is_allowed()

            # Should be denied
            assert limiter.is_allowed() is False

            # Advance 1 second - should refill 10 tokens
            frozen_time.move_to("2021-01-01 00:00:01")
            for _ in range(10):
                assert limiter.is_allowed() is True
            assert limiter.is_allowed() is False

    @freeze_time("2021-01-01 00:00:00")
    def test_partial_token_refill(self):
        """Partial time should refill partial tokens."""
        with freeze_time("2021-01-01 00:00:00") as frozen_time:
            limiter = RateLimiter(max_rate=10, burst=10)

            # Consume all tokens
            for _ in range(10):
                limiter.is_allowed()

            # Advance 0.5 seconds - should refill 5 tokens
            frozen_time.move_to("2021-01-01 00:00:00.500")
            for _ in range(5):
                assert limiter.is_allowed() is True
            assert limiter.is_allowed() is False

    @freeze_time("2021-01-01 00:00:00")
    def test_tokens_capped_at_burst(self):
        """Tokens should not exceed burst limit."""
        with freeze_time("2021-01-01 00:00:00") as frozen_time:
            limiter = RateLimiter(max_rate=10, burst=20)

            # Consume some tokens
            for _ in range(5):
                limiter.is_allowed()

            # Wait a long time (would refill way more than burst)
            frozen_time.move_to("2021-01-01 00:01:00")  # 60 seconds = 600 tokens theoretically

            # Should still only have burst tokens available
            for _ in range(20):
                assert limiter.is_allowed() is True
            assert limiter.is_allowed() is False

    def test_get_retry_delay(self):
        """Retry delay should be inverse of rate."""
        limiter = RateLimiter(max_rate=10, burst=20)
        assert limiter.get_retry_delay() == 100  # 1000ms / 10

        limiter2 = RateLimiter(max_rate=50, burst=100)
        assert limiter2.get_retry_delay() == 20  # 1000ms / 50

        limiter3 = RateLimiter(max_rate=100, burst=200)
        assert limiter3.get_retry_delay() == 10  # 1000ms / 100

    @freeze_time("2021-01-01 00:00:00")
    def test_continuous_rate_limiting(self):
        """Should maintain steady rate over time."""
        with freeze_time("2021-01-01 00:00:00") as frozen_time:
            limiter = RateLimiter(max_rate=10, burst=10)

            # Consume initial burst
            for _ in range(10):
                limiter.is_allowed()

            # Simulate requests over 5 seconds at exactly the rate limit
            for second in range(1, 6):
                frozen_time.move_to(f"2021-01-01 00:00:0{second}")

                # Should allow exactly max_rate requests per second
                for _ in range(10):
                    assert limiter.is_allowed() is True

                # Next request should be denied
                assert limiter.is_allowed() is False

    @freeze_time("2021-01-01 00:00:00")
    def test_fractional_tokens(self):
        """Should handle fractional token accumulation correctly."""
        with freeze_time("2021-01-01 00:00:00") as frozen_time:
            limiter = RateLimiter(max_rate=3, burst=5)

            # Consume all tokens
            for _ in range(5):
                limiter.is_allowed()

            # Advance by 0.333 seconds (should add ~1 token)
            frozen_time.move_to("2021-01-01 00:00:00.333")
            assert limiter.is_allowed() is True
            assert limiter.is_allowed() is False

            # Advance by another 0.667 seconds (total 1 second, should add ~2 more tokens)
            frozen_time.move_to("2021-01-01 00:00:01.000")
            assert limiter.is_allowed() is True
            assert limiter.is_allowed() is True
            assert limiter.is_allowed() is False

    @freeze_time("2021-01-01 00:00:00")
    def test_zero_rate(self):
        """Should handle edge case of rate=1 (very slow)."""
        with freeze_time("2021-01-01 00:00:00") as frozen_time:
            limiter = RateLimiter(max_rate=1, burst=2)

            # Consume burst
            assert limiter.is_allowed() is True
            assert limiter.is_allowed() is True
            assert limiter.is_allowed() is False

            # Need to wait 1 full second for 1 token
            frozen_time.move_to("2021-01-01 00:00:01")
            assert limiter.is_allowed() is True
            assert limiter.is_allowed() is False

    @freeze_time("2021-01-01 00:00:00")
    def test_high_rate(self):
        """Should handle high rate limits."""
        with freeze_time("2021-01-01 00:00:00") as frozen_time:
            limiter = RateLimiter(max_rate=1000, burst=2000)

            # Consume burst
            for _ in range(2000):
                assert limiter.is_allowed() is True
            assert limiter.is_allowed() is False

            # Advance 1 second
            frozen_time.move_to("2021-01-01 00:00:01")

            # Should refill 1000 tokens
            for _ in range(1000):
                assert limiter.is_allowed() is True
            assert limiter.is_allowed() is False

    def test_rate_limiter_attributes(self):
        """Should store configuration attributes."""
        limiter = RateLimiter(max_rate=50, burst=100)

        assert limiter.max_rate == 50
        assert limiter.burst == 100
        assert limiter.tokens == 100  # Initial tokens equal burst
        assert isinstance(limiter.last_update, float)
