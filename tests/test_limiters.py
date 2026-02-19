"""
Tests for rate limiter functionality.
"""
import unittest
import time
from unittest.mock import Mock, patch
import redis

import sys
sys.path.insert(0, '../src')

from limiters import RateLimiter, LimiterStrategy


class TestRateLimiter(unittest.TestCase):
    """Test rate limiting algorithms."""
    
    def setUp(self):
        """Set up test Redis client."""
        self.redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
        self.limiter = RateLimiter(self.redis_client)
        
        # Clean up test keys
        for key in self.redis_client.scan_iter("bucket:test_*"):
            self.redis_client.delete(key)
        for key in self.redis_client.scan_iter("window:test_*"):
            self.redis_client.delete(key)
    
    def test_token_bucket_allows_initial_requests(self):
        """Test that token bucket allows requests up to limit."""
        limit = 5
        
        for i in range(limit):
            allowed, metadata = self.limiter.check_limit(
                "test_client_1",
                limit=limit,
                window=60,
                strategy=LimiterStrategy.TOKEN_BUCKET
            )
            self.assertTrue(allowed, f"Request {i+1} should be allowed")
            self.assertEqual(metadata['remaining'], limit - i - 1)
    
    def test_token_bucket_blocks_excess_requests(self):
        """Test that token bucket blocks requests exceeding limit."""
        limit = 3
        
        # Use up all tokens
        for _ in range(limit):
            self.limiter.check_limit("test_client_2", limit, 60, LimiterStrategy.TOKEN_BUCKET)
        
        # Next request should be blocked
        allowed, metadata = self.limiter.check_limit(
            "test_client_2", limit, 60, LimiterStrategy.TOKEN_BUCKET
        )
        self.assertFalse(allowed)
        self.assertEqual(metadata['remaining'], 0)
    
    def test_token_bucket_refills_over_time(self):
        """Test that token bucket refills tokens over time."""
        limit = 10
        window = 10  # 10 second window, so 1 token per second
        
        # Use up all tokens
        for _ in range(limit):
            self.limiter.check_limit("test_client_3", limit, window, LimiterStrategy.TOKEN_BUCKET)
        
        # Should be blocked immediately
        allowed, _ = self.limiter.check_limit("test_client_3", limit, window, LimiterStrategy.TOKEN_BUCKET)
        self.assertFalse(allowed)
        
        # Wait for tokens to refill (2 seconds = 2 tokens)
        time.sleep(2)
        
        # Should allow 2 requests now
        for i in range(2):
            allowed, metadata = self.limiter.check_limit(
                "test_client_3", limit, window, LimiterStrategy.TOKEN_BUCKET
            )
            self.assertTrue(allowed, f"Refilled request {i+1} should be allowed")
    
    def test_sliding_window_allows_initial_requests(self):
        """Test that sliding window allows requests up to limit."""
        limit = 5
        
        for i in range(limit):
            allowed, metadata = self.limiter.check_limit(
                "test_client_4",
                limit=limit,
                window=60,
                strategy=LimiterStrategy.SLIDING_WINDOW
            )
            self.assertTrue(allowed, f"Request {i+1} should be allowed")
            self.assertEqual(metadata['remaining'], limit - i - 1)
    
    def test_sliding_window_blocks_excess_requests(self):
        """Test that sliding window blocks requests exceeding limit."""
        limit = 3
        
        # Use up limit
        for _ in range(limit):
            self.limiter.check_limit("test_client_5", limit, 60, LimiterStrategy.SLIDING_WINDOW)
        
        # Next request should be blocked
        allowed, metadata = self.limiter.check_limit(
            "test_client_5", limit, 60, LimiterStrategy.SLIDING_WINDOW
        )
        self.assertFalse(allowed)
        self.assertEqual(metadata['remaining'], 0)
    
    def test_sliding_window_respects_time_window(self):
        """Test that sliding window properly handles time-based expiry."""
        limit = 3
        window = 2  # 2 second window
        
        # Make 3 requests
        for _ in range(limit):
            self.limiter.check_limit("test_client_6", limit, window, LimiterStrategy.SLIDING_WINDOW)
        
        # Should be blocked
        allowed, _ = self.limiter.check_limit("test_client_6", limit, window, LimiterStrategy.SLIDING_WINDOW)
        self.assertFalse(allowed)
        
        # Wait for window to pass
        time.sleep(window + 0.5)
        
        # Should allow new requests
        allowed, metadata = self.limiter.check_limit(
            "test_client_6", limit, window, LimiterStrategy.SLIDING_WINDOW
        )
        self.assertTrue(allowed)
        self.assertEqual(metadata['remaining'], limit - 1)
    
    def test_different_clients_independent_limits(self):
        """Test that different clients have independent rate limits."""
        limit = 2
        
        # Client 1 uses up limit
        for _ in range(limit):
            self.limiter.check_limit("client_a", limit, 60, LimiterStrategy.SLIDING_WINDOW)
        
        # Client 1 should be blocked
        allowed, _ = self.limiter.check_limit("client_a", limit, 60, LimiterStrategy.SLIDING_WINDOW)
        self.assertFalse(allowed)
        
        # Client 2 should still be allowed
        allowed, metadata = self.limiter.check_limit("client_b", limit, 60, LimiterStrategy.SLIDING_WINDOW)
        self.assertTrue(allowed)
        self.assertEqual(metadata['remaining'], limit - 1)
    
    def test_fallback_mode_on_redis_failure(self):
        """Test that fallback mode handles Redis failures gracefully."""
        # Create limiter with mocked Redis that always fails
        mock_redis = Mock()
        mock_redis.eval.side_effect = redis.RedisError("Connection failed")
        
        limiter_with_fallback = RateLimiter(mock_redis, fallback_mode=True)
        
        # Should fail open (allow request)
        allowed, metadata = limiter_with_fallback.check_limit(
            "test_fallback", 10, 60, LimiterStrategy.SLIDING_WINDOW
        )
        self.assertTrue(allowed)
        self.assertTrue(metadata.get('fallback'))
        self.assertIn('error', metadata)


class TestEndToEnd(unittest.TestCase):
    """End-to-end integration tests."""
    
    def setUp(self):
        """Set up test environment."""
        from app import app
        self.app = app
        self.client = self.app.test_client()
    
    def test_rate_limit_headers_present(self):
        """Test that rate limit headers are included in response."""
        response = self.client.get('/api/data')
        
        self.assertIn('X-RateLimit-Limit', response.headers)
        self.assertIn('X-RateLimit-Remaining', response.headers)
        self.assertIn('X-RateLimit-Reset', response.headers)
        self.assertIn('X-RateLimit-Strategy', response.headers)
    
    def test_rate_limit_enforcement(self):
        """Test that rate limits are actually enforced."""
        # Make requests until we hit the limit
        responses = []
        for _ in range(15):  # More than the 10 request limit
            response = self.client.get('/api/data')
            responses.append(response.status_code)
        
        # Should have some 200s and some 429s
        self.assertIn(200, responses)
        self.assertIn(429, responses)
    
    def test_health_endpoint(self):
        """Test health check endpoint."""
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('status', data)


if __name__ == '__main__':
    unittest.main()
