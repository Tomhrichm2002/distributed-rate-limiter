"""
API Gateway with rate limiting middleware.
"""
from flask import Flask, request, jsonify, g
from functools import wraps
import redis
import psycopg2
from psycopg2.extras import execute_values
import logging
import time
import os
from datetime import datetime

from limiters import RateLimiter, LimiterStrategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_DB = os.getenv('POSTGRES_DB', 'ratelimiter')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'postgres')

# Initialize Redis
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2
)

# Initialize rate limiter
limiter = RateLimiter(redis_client, fallback_mode=True)


def get_db():
    """Get PostgreSQL connection from g or create new one."""
    if 'db' not in g:
        g.db = psycopg2.connect(
            host=POSTGRES_HOST,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD
        )
    return g.db


@app.teardown_appcontext
def close_db(error):
    """Close database connection at end of request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def log_request(client_id: str, endpoint: str, allowed: bool, metadata: dict):
    """Log request to PostgreSQL for analytics."""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute("""
            INSERT INTO request_logs 
            (client_id, endpoint, allowed, strategy, limit_value, remaining, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            client_id,
            endpoint,
            allowed,
            metadata.get('strategy'),
            metadata.get('limit'),
            metadata.get('remaining'),
            datetime.now()
        ))
        
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log request: {e}")


def rate_limit(limit: int = 100, window: int = 60, 
               strategy: LimiterStrategy = LimiterStrategy.SLIDING_WINDOW):
    """
    Rate limiting decorator.
    
    Args:
        limit: Maximum requests allowed
        window: Time window in seconds
        strategy: Rate limiting algorithm
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get client identifier (IP or API key)
            client_id = request.headers.get('X-API-Key') or request.remote_addr
            endpoint = request.endpoint or 'unknown'
            
            # Check rate limit
            start_time = time.time()
            allowed, metadata = limiter.check_limit(
                f"{client_id}:{endpoint}",
                limit,
                window,
                strategy
            )
            check_duration = time.time() - start_time
            
            # Log the request
            log_request(client_id, endpoint, allowed, metadata)
            
            # Add rate limit headers
            response_headers = {
                'X-RateLimit-Limit': str(metadata.get('limit', limit)),
                'X-RateLimit-Remaining': str(metadata.get('remaining', 0)),
                'X-RateLimit-Reset': str(metadata.get('reset_at', 0)),
                'X-RateLimit-Strategy': metadata.get('strategy', strategy.value),
            }
            
            if metadata.get('fallback'):
                response_headers['X-RateLimit-Fallback'] = 'true'
            
            # Track performance metrics
            logger.info(f"Rate limit check took {check_duration*1000:.2f}ms for {client_id}")
            
            if not allowed:
                response = jsonify({
                    'error': 'Rate limit exceeded',
                    'limit': metadata.get('limit'),
                    'window': window,
                    'retry_after': metadata.get('reset_at', 0) - int(time.time())
                })
                response.status_code = 429
                
                for key, value in response_headers.items():
                    response.headers[key] = value
                
                return response
            
            # Execute the route handler
            result = f(*args, **kwargs)
            
            # Add headers to successful response
            if hasattr(result, 'headers'):
                for key, value in response_headers.items():
                    result.headers[key] = value
            
            return result
        
        return decorated_function
    return decorator


# Example protected endpoints
@app.route('/api/data', methods=['GET'])
@rate_limit(limit=10, window=60, strategy=LimiterStrategy.SLIDING_WINDOW)
def get_data():
    """Example endpoint with sliding window rate limit."""
    return jsonify({
        'message': 'This is rate-limited data',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/search', methods=['GET'])
@rate_limit(limit=30, window=60, strategy=LimiterStrategy.TOKEN_BUCKET)
def search():
    """Example endpoint with token bucket (allows bursts)."""
    query = request.args.get('q', '')
    return jsonify({
        'query': query,
        'results': ['result1', 'result2', 'result3']
    })


@app.route('/api/upload', methods=['POST'])
@rate_limit(limit=5, window=300, strategy=LimiterStrategy.SLIDING_WINDOW)
def upload():
    """Expensive operation with strict rate limit."""
    return jsonify({
        'message': 'Upload successful',
        'size': request.content_length
    })


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint (no rate limit)."""
    redis_status = 'ok'
    postgres_status = 'ok'
    
    try:
        redis_client.ping()
    except Exception as e:
        redis_status = f'error: {str(e)}'
    
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT 1')
    except Exception as e:
        postgres_status = f'error: {str(e)}'
    
    return jsonify({
        'status': 'healthy' if redis_status == 'ok' and postgres_status == 'ok' else 'degraded',
        'redis': redis_status,
        'postgres': postgres_status
    })


@app.route('/metrics', methods=['GET'])
def metrics():
    """Simple metrics endpoint."""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Get request stats from last hour
        cursor.execute("""
            SELECT 
                COUNT(*) as total_requests,
                SUM(CASE WHEN allowed THEN 1 ELSE 0 END) as allowed_requests,
                SUM(CASE WHEN NOT allowed THEN 1 ELSE 0 END) as blocked_requests
            FROM request_logs
            WHERE timestamp > NOW() - INTERVAL '1 hour'
        """)
        
        stats = cursor.fetchone()
        
        return jsonify({
            'last_hour': {
                'total': stats[0],
                'allowed': stats[1],
                'blocked': stats[2],
                'block_rate': round(stats[2] / stats[0] * 100, 2) if stats[0] > 0 else 0
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
