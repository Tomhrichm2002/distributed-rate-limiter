"""
Rate limiting algorithms implementation.
Supports Token Bucket and Sliding Window strategies.
"""
import time
import redis
import logging
from typing import Tuple, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class LimiterStrategy(Enum):
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"


class RateLimiter:
    """Base rate limiter with Redis backend for distributed state."""
    
    def __init__(self, redis_client: redis.Redis, fallback_mode: bool = True):
        self.redis = redis_client
        self.fallback_mode = fallback_mode
    
    def check_limit(self, key: str, limit: int, window: int, strategy: LimiterStrategy) -> Tuple[bool, dict]:
        """
        Check if request should be allowed.
        
        Args:
            key: Unique identifier (e.g., user_id, ip_address)
            limit: Maximum requests allowed
            window: Time window in seconds
            strategy: Rate limiting algorithm to use
            
        Returns:
            Tuple of (allowed: bool, metadata: dict)
        """
        try:
            if strategy == LimiterStrategy.TOKEN_BUCKET:
                return self._token_bucket(key, limit, window)
            elif strategy == LimiterStrategy.SLIDING_WINDOW:
                return self._sliding_window(key, limit, window)
            else:
                raise ValueError(f"Unknown strategy: {strategy}")
        except redis.RedisError as e:
            logger.error(f"Redis error in rate limiter: {e}")
            if self.fallback_mode:
                # Fail open - allow request but log the failure
                logger.warning(f"Rate limiter failed open for key: {key}")
                return True, {"fallback": True, "error": str(e)}
            else:
                # Fail closed - deny request on Redis failure
                return False, {"fallback": True, "error": str(e)}
    
    def _token_bucket(self, key: str, limit: int, window: int) -> Tuple[bool, dict]:
        """
        Token bucket algorithm - allows burst traffic up to capacity.
        Tokens refill at a constant rate.
        """
        lua_script = """
        local key = KEYS[1]
        local limit = tonumber(ARGV[1])
        local window = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])
        
        local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
        local tokens = tonumber(bucket[1])
        local last_refill = tonumber(bucket[2])
        
        -- Initialize if doesn't exist
        if not tokens then
            tokens = limit
            last_refill = now
        end
        
        -- Calculate refill
        local elapsed = now - last_refill
        local refill_rate = limit / window
        local tokens_to_add = math.floor(elapsed * refill_rate)
        
        tokens = math.min(limit, tokens + tokens_to_add)
        last_refill = now
        
        local allowed = 0
        if tokens >= 1 then
            tokens = tokens - 1
            allowed = 1
        end
        
        -- Update state
        redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
        redis.call('EXPIRE', key, window * 2)
        
        return {allowed, tokens, limit}
        """
        
        now = time.time()
        result = self.redis.eval(lua_script, 1, f"bucket:{key}", limit, window, now)
        
        allowed = bool(result[0])
        remaining = int(result[1])
        
        metadata = {
            "strategy": "token_bucket",
            "limit": limit,
            "remaining": remaining,
            "window": window,
            "reset_at": int(now + window)
        }
        
        return allowed, metadata
    
    def _sliding_window(self, key: str, limit: int, window: int) -> Tuple[bool, dict]:
        """
        Sliding window algorithm - more accurate than fixed window,
        prevents boundary issues.
        """
        lua_script = """
        local key = KEYS[1]
        local limit = tonumber(ARGV[1])
        local window = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])
        
        -- Remove old entries outside the window
        redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
        
        -- Count requests in current window
        local count = redis.call('ZCARD', key)
        
        local allowed = 0
        if count < limit then
            -- Add current request
            redis.call('ZADD', key, now, now)
            redis.call('EXPIRE', key, window)
            allowed = 1
            count = count + 1
        end
        
        return {allowed, limit - count, limit}
        """
        
        now = time.time()
        result = self.redis.eval(lua_script, 1, f"window:{key}", limit, window, now)
        
        allowed = bool(result[0])
        remaining = int(result[1])
        
        metadata = {
            "strategy": "sliding_window",
            "limit": limit,
            "remaining": remaining,
            "window": window,
            "reset_at": int(now + window)
        }
        
        return allowed, metadata


class CircuitBreaker:
    """
    Circuit breaker for Redis failures.
    Prevents cascading failures when Redis is down.
    """
    
    def __init__(self, redis_client: redis.Redis, 
                 failure_threshold: int = 5,
                 timeout: int = 60):
        self.redis = redis_client
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half_open
    
    def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == "open":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "half_open"
                logger.info("Circuit breaker entering half-open state")
            else:
                raise Exception("Circuit breaker is open")
        
        try:
            result = func(*args, **kwargs)
            if self.state == "half_open":
                self.state = "closed"
                self.failures = 0
                logger.info("Circuit breaker closed")
            return result
        except Exception as e:
            self.failures += 1
            self.last_failure_time = time.time()
            
            if self.failures >= self.failure_threshold:
                self.state = "open"
                logger.error(f"Circuit breaker opened after {self.failures} failures")
            
            raise e
