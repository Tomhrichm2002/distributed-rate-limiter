# Distributed Rate Limiter

API rate limiter built with Python, Redis, and PostgreSQL. Implements multiple rate limiting algorithms (Token Bucket, Sliding Window) with comprehensive analytics, graceful degradation, and a real-time monitoring dashboard.

## Features

- **Multiple Rate Limiting Algorithms**
  - Token Bucket: Allows burst traffic up to capacity
  - Sliding Window: More accurate, prevents boundary issues

- **Production-Ready**
  - Circuit breaker for Redis failures
  - fail open/closed configurable
  - Logging and monitoring
  - Request analytics pipeline

- **Real-Time Dashboard**
  - Live metrics and statistics
  - Top blocked clients identification
  - Per-endpoint performance tracking

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│   Gateway   │────▶│   Backend   │
│             │     │  +Limiter   │     │   Service   │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────▼──────┐
                    │    Redis    │
                    └─────────────┘
                           │
                    ┌──────▼──────┐
                    │  PostgreSQL │
                    └─────────────┘  :)
```

## Quick Start

### Requirements

- Docker and Docker Compose
- Python 3.11+ (for local development)

### Run with Docker!

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f gateway

# Stop services
docker-compose down
```

Services will be available at:
- API Gateway: http://localhost:5000
- Dashboard: http://localhost:8080
- Redis: localhost:6379
- PostgreSQL: localhost:5432

### Test the Rate Limiter

```bash
# Make requests to rate-limited endpoint
for i in {1..15}; do
  curl -w "\nStatus: %{http_code}\n" \
       -H "X-API-Key: test-client" \
       http://localhost:5000/api/data
  echo "---"
done
```

Sanity check:
- First 10 requests: `200 OK`
- Remaining requests: `429 Too Many Requests`

Check rate limit headers:
```bash
curl -I http://localhost:5000/api/data
```

Response headers:
```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 9
X-RateLimit-Reset: 1706828520
X-RateLimit-Strategy: sliding_window
```

## API Endpoints

### Protected Endpoints

#### `GET /api/data`
- Rate Limit: 10 requests/minute (Sliding Window)
- Returns sample data

#### `GET /api/search?q=<query>`
- Rate Limit: 30 requests/minute (Token Bucket)
- Allows burst traffic
- Returns search results

#### `POST /api/upload`
- Rate Limit: 5 requests/5 minutes (Sliding Window)
- Expensive operation with strict limit

### Monitoring Endpoints

#### `GET /health`
- Health check (no rate limit)
- Returns status of Redis and PostgreSQL

#### `GET /metrics`
- Request statistics from last hour
- Total, allowed, blocked counts

## Rate Limiting Strategies

### Token Bucket

**Use Case:** APIs that allow burst traffic

**How it works:**
- Bucket starts with `limit` tokens
- Each request consumes 1 token
- Tokens refill at constant rate: `limit / window` per second
- Allows bursts up to full bucket capacity

**Example:** Search API where occasional bursts are acceptable

```python
@app.route('/api/search')
@rate_limit(limit=30, window=60, strategy=LimiterStrategy.TOKEN_BUCKET)
def search():
    ...
```

### Sliding Window

**Use Case:** Strict rate limiting without boundary issues

**How it works:**
- Tracks individual request timestamps
- Removes requests outside current window
- Counts remaining requests in window
- More accurate than fixed windows

**Example:** Upload API where strict limits are required

```python
@app.route('/api/upload')
@rate_limit(limit=5, window=300, strategy=LimiterStrategy.SLIDING_WINDOW)
def upload():
    ...
```

## Dashboard

Visit http://localhost:8080 to see:

- **Real-time Metrics**
  - Total requests
  - Allowed vs blocked
  - Block rate percentage

- **Endpoint Performance**
  - Per-endpoint statistics
  - Strategy comparison
  - Average limits and remaining tokens

- **Top Blocked Clients**
  - Identify potential abuse
  - Track violation patterns
  - Monitor suspicious activity

## Configuration

### Environment Variables

```bash
# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_DB=ratelimiter
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
```

### Rate Limit Decorator

```python
from limiters import LimiterStrategy

@rate_limit(
    limit=100,           # Max requests
    window=60,           # Time window in seconds
    strategy=LimiterStrategy.SLIDING_WINDOW  # Algorithm
)
def my_endpoint():
    ...
```

### Fallback Behavior

**Fail Open (default):** Allow requests when Redis is down
```python
limiter = RateLimiter(redis_client, fallback_mode=True)
```

**Fail Closed:** Deny requests when Redis is down
```python
limiter = RateLimiter(redis_client, fallback_mode=False)
```

## Technical Deep Dive

### Atomicity and Race Conditions

This implementation uses Redis Lua scripts to ensure atomic operations:

```lua
-- Sliding Window Implementation (simplified)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, now)
    return 1  -- allowed
end
return 0  -- blocked
```

Benefits:
- All operations in one round-trip
- No race conditions between check and increment
- Guaranteed consistency across instances

### Performance Considerations

**Benchmarks** (single Redis instance):
- Token Bucket: ~5,000 req/sec
- Sliding Window: ~4,000 req/sec
- Latency: p50 < 5ms, p99 < 15ms

**Scaling:**
- Horizontal scaling: Add more gateway instances
- Redis: Use Redis Cluster for high throughput
- PostgreSQL: Connection pooling + read replicas

## Testing

### Run Tests

```bash
# Start Redis for tests
docker-compose up -d redis postgres

# Run test suite
cd tests
python test_limiters.py
```

### Load Testing

```bash
# Install Apache Bench
apt-get install apache2-utils  # Ubuntu
brew install httpie  # macOS

# Run load test
ab -n 1000 -c 10 http://localhost:5000/api/data
```

## Project Structure

```
rate-limiter/
├── src/
│   ├── limiters.py        # Core rate limiting algorithms
│   ├── app.py             # Flask API gateway
│   └── dashboard.py       # Analytics dashboard
├── config/
│   └── schema.sql         # PostgreSQL schema
├── tests/
│   └── test_limiters.py   # Test suite
├── docker-compose.yml     # Docker orchestration
├── Dockerfile             # Container definition
├── requirements.txt       # Python dependencies
└── README.md
```

## Common Issues

### Redis Connection Timeout

**Symptom:** `RedisError: Connection timeout`

**Solution:**
```bash
# Check Redis is running
docker-compose ps redis

# Check connectivity
redis-cli -h localhost -p 6379 ping
```

### Rate Limit Not Enforcing

**Possible causes:**
1. Different client identifiers (check `X-API-Key` header)
2. Redis keys expired (check TTL)
3. Fallback mode triggered (check logs)

**Debug:**
```bash
# Check Redis keys
redis-cli KEYS "window:*"
redis-cli KEYS "bucket:*"

# Monitor operations
redis-cli MONITOR
```



## License

MIT

## Author

Built as a demonstration of production-grade system design and distributed rate limiting.
