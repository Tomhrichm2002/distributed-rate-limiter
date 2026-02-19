-- PostgreSQL schema for rate limiter analytics

CREATE TABLE IF NOT EXISTS request_logs (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(255) NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    allowed BOOLEAN NOT NULL,
    strategy VARCHAR(50),
    limit_value INTEGER,
    remaining INTEGER,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_request_logs_client ON request_logs(client_id);
CREATE INDEX idx_request_logs_timestamp ON request_logs(timestamp DESC);
CREATE INDEX idx_request_logs_endpoint ON request_logs(endpoint);
CREATE INDEX idx_request_logs_allowed ON request_logs(allowed);

-- View for hourly statistics
CREATE OR REPLACE VIEW hourly_stats AS
SELECT 
    date_trunc('hour', timestamp) as hour,
    endpoint,
    COUNT(*) as total_requests,
    SUM(CASE WHEN allowed THEN 1 ELSE 0 END) as allowed_requests,
    SUM(CASE WHEN NOT allowed THEN 1 ELSE 0 END) as blocked_requests,
    ROUND(100.0 * SUM(CASE WHEN NOT allowed THEN 1 ELSE 0 END) / COUNT(*), 2) as block_percentage
FROM request_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY date_trunc('hour', timestamp), endpoint
ORDER BY hour DESC;

-- View for top abusers
CREATE OR REPLACE VIEW top_blocked_clients AS
SELECT 
    client_id,
    COUNT(*) as blocked_count,
    MAX(timestamp) as last_blocked,
    ARRAY_AGG(DISTINCT endpoint) as endpoints
FROM request_logs
WHERE NOT allowed 
AND timestamp > NOW() - INTERVAL '24 hours'
GROUP BY client_id
HAVING COUNT(*) > 10
ORDER BY blocked_count DESC
LIMIT 100;

-- View for endpoint performance
CREATE OR REPLACE VIEW endpoint_stats AS
SELECT 
    endpoint,
    strategy,
    COUNT(*) as total_requests,
    SUM(CASE WHEN allowed THEN 1 ELSE 0 END) as allowed,
    SUM(CASE WHEN NOT allowed THEN 1 ELSE 0 END) as blocked,
    ROUND(AVG(limit_value), 2) as avg_limit,
    ROUND(AVG(remaining), 2) as avg_remaining
FROM request_logs
WHERE timestamp > NOW() - INTERVAL '1 hour'
GROUP BY endpoint, strategy
ORDER BY total_requests DESC;
