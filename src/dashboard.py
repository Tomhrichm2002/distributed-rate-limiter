"""
Simple admin dashboard for rate limiter analytics.
"""
from flask import Flask, render_template_string, jsonify
import psycopg2
import os
from datetime import datetime, timedelta

app = Flask(__name__)

POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_DB = os.getenv('POSTGRES_DB', 'ratelimiter')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'postgres')


def get_db():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )


DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Rate Limiter Dashboard</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            color: #333;
            margin-bottom: 30px;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stat-label {
            color: #666;
            font-size: 14px;
            margin-bottom: 5px;
        }
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            color: #333;
        }
        .stat-value.good { color: #10b981; }
        .stat-value.warning { color: #f59e0b; }
        .stat-value.danger { color: #ef4444; }
        table {
            width: 100%;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }
        th {
            background: #f9fafb;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #374151;
            border-bottom: 2px solid #e5e7eb;
        }
        td {
            padding: 12px;
            border-bottom: 1px solid #e5e7eb;
        }
        tr:last-child td {
            border-bottom: none;
        }
        .refresh-btn {
            background: #3b82f6;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            margin-bottom: 20px;
        }
        .refresh-btn:hover {
            background: #2563eb;
        }
        .section-title {
            font-size: 20px;
            font-weight: 600;
            margin: 30px 0 15px 0;
            color: #1f2937;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚦 Rate Limiter Dashboard</h1>
        
        <button class="refresh-btn" onclick="location.reload()">🔄 Refresh</button>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Total Requests (1h)</div>
                <div class="stat-value">{{ stats.total }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Allowed</div>
                <div class="stat-value good">{{ stats.allowed }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Blocked</div>
                <div class="stat-value danger">{{ stats.blocked }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Block Rate</div>
                <div class="stat-value {{ 'danger' if stats.block_rate > 20 else 'warning' if stats.block_rate > 10 else 'good' }}">
                    {{ stats.block_rate }}%
                </div>
            </div>
        </div>
        
        <div class="section-title">📊 Endpoint Performance</div>
        <table>
            <thead>
                <tr>
                    <th>Endpoint</th>
                    <th>Strategy</th>
                    <th>Total</th>
                    <th>Allowed</th>
                    <th>Blocked</th>
                    <th>Avg Limit</th>
                    <th>Avg Remaining</th>
                </tr>
            </thead>
            <tbody>
                {% for row in endpoint_stats %}
                <tr>
                    <td><code>{{ row[0] }}</code></td>
                    <td>{{ row[1] }}</td>
                    <td>{{ row[2] }}</td>
                    <td style="color: #10b981;">{{ row[3] }}</td>
                    <td style="color: #ef4444;">{{ row[4] }}</td>
                    <td>{{ row[5] }}</td>
                    <td>{{ row[6] }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        
        <div class="section-title">⚠️ Top Blocked Clients (24h)</div>
        <table>
            <thead>
                <tr>
                    <th>Client ID</th>
                    <th>Blocked Count</th>
                    <th>Last Blocked</th>
                    <th>Endpoints</th>
                </tr>
            </thead>
            <tbody>
                {% for row in top_blocked %}
                <tr>
                    <td><code>{{ row[0] }}</code></td>
                    <td style="color: #ef4444; font-weight: bold;">{{ row[1] }}</td>
                    <td>{{ row[2] }}</td>
                    <td>{{ row[3]|join(', ') }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
"""


@app.route('/')
def dashboard():
    """Main dashboard view."""
    db = get_db()
    cursor = db.cursor()
    
    # Get overall stats
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN allowed THEN 1 ELSE 0 END) as allowed,
            SUM(CASE WHEN NOT allowed THEN 1 ELSE 0 END) as blocked
        FROM request_logs
        WHERE timestamp > NOW() - INTERVAL '1 hour'
    """)
    stats_row = cursor.fetchone()
    stats = {
        'total': stats_row[0] or 0,
        'allowed': stats_row[1] or 0,
        'blocked': stats_row[2] or 0,
        'block_rate': round((stats_row[2] or 0) / (stats_row[0] or 1) * 100, 1)
    }
    
    # Get endpoint stats
    cursor.execute("SELECT * FROM endpoint_stats")
    endpoint_stats = cursor.fetchall()
    
    # Get top blocked clients
    cursor.execute("SELECT * FROM top_blocked_clients LIMIT 20")
    top_blocked = cursor.fetchall()
    
    db.close()
    
    return render_template_string(
        DASHBOARD_HTML,
        stats=stats,
        endpoint_stats=endpoint_stats,
        top_blocked=top_blocked
    )


@app.route('/api/stats')
def api_stats():
    """JSON API for stats."""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        SELECT 
            date_trunc('minute', timestamp) as minute,
            COUNT(*) as total,
            SUM(CASE WHEN allowed THEN 1 ELSE 0 END) as allowed,
            SUM(CASE WHEN NOT allowed THEN 1 ELSE 0 END) as blocked
        FROM request_logs
        WHERE timestamp > NOW() - INTERVAL '1 hour'
        GROUP BY date_trunc('minute', timestamp)
        ORDER BY minute DESC
    """)
    
    timeseries = []
    for row in cursor.fetchall():
        timeseries.append({
            'timestamp': row[0].isoformat(),
            'total': row[1],
            'allowed': row[2],
            'blocked': row[3]
        })
    
    db.close()
    
    return jsonify(timeseries)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
