#!/usr/bin/env python3
"""
Simple web dashboard for Polymarket × Hyperliquid Arbitrage Bot
Run: python dashboard_server.py
Visit: http://localhost:5000
"""
import os
import json
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, jsonify
from decimal import Decimal

app = Flask(__name__)

LOG_DIR = Path("logs")


def read_latest_log():
    """Read the latest log file"""
    try:
        log_files = list(LOG_DIR.glob("bot_*.log"))
        if not log_files:
            return []

        latest_log = max(log_files, key=os.path.getmtime)
        with open(latest_log, 'r') as f:
            lines = f.readlines()
            return lines[-100:]  # Last 100 lines
    except Exception as e:
        return [f"Error reading log: {e}"]


def parse_log_stats():
    """Parse log file to extract statistics"""
    lines = read_latest_log()

    stats = {
        "total_scans": 0,
        "opportunities_found": 0,
        "trades_executed": 0,
        "errors": 0,
        "last_scan": "Never",
        "polymarket_balance": "0",
        "hyperliquid_balance": "0",
        "bot_status": "Stopped",
        "markets_checked": 0
    }

    for line in lines:
        if "Scanning for arbitrage opportunities" in line:
            stats["total_scans"] += 1
            # Extract timestamp
            try:
                timestamp = line.split(" - ")[0]
                stats["last_scan"] = timestamp
            except:
                pass

        if "Found 0 arbitrage opportunities" in line:
            stats["markets_checked"] +=1

        if "Found" in line and "active" in line and "markets" in line:
            try:
                count = int(line.split("Found")[1].split("active")[0].strip())
                stats["opportunities_found"] += count
            except:
                pass

        if "Trade Executed" in line or "Placed" in line and "order" in line:
            stats["trades_executed"] += 1

        if "ERROR" in line:
            stats["errors"] += 1

        if "Account balance:" in line and "USDC" in line:
            try:
                balance = line.split("Account balance:")[1].split("USDC")[0].strip()
                stats["polymarket_balance"] = balance
            except:
                pass

        if "Account balance: $" in line:
            try:
                balance = line.split("Account balance: $")[1].strip()
                stats["hyperliquid_balance"] = balance
            except:
                pass

        if "Starting arbitrage bot" in line:
            stats["bot_status"] = "Running"

        if "shutdown" in line.lower():
            stats["bot_status"] = "Stopped"

    return stats


@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')


@app.route('/api/stats')
def get_stats():
    """API endpoint for statistics"""
    stats = parse_log_stats()
    return jsonify(stats)


@app.route('/api/logs')
def get_logs():
    """API endpoint for recent logs"""
    lines = read_latest_log()
    return jsonify({"logs": lines})


if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)

    # Create the HTML template
    html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Polymarket × Hyperliquid Arbitrage Bot Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: #0f1419;
            color: #e7e9ea;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 {
            font-size: 2rem;
            margin-bottom: 30px;
            color: #1d9bf0;
            text-align: center;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: #16181c;
            border: 1px solid #2f3336;
            border-radius: 12px;
            padding: 20px;
        }
        .stat-label {
            color: #71767b;
            font-size: 0.9rem;
            margin-bottom: 8px;
        }
        .stat-value {
            font-size: 2rem;
            font-weight: bold;
            color: #e7e9ea;
        }
        .stat-value.green { color: #00ba7c; }
        .stat-value.red { color: #f4212e; }
        .stat-value.blue { color: #1d9bf0; }
        .log-container {
            background: #16181c;
            border: 1px solid: #2f3336;
            border-radius: 12px;
            padding: 20px;
            max-height: 600px;
            overflow-y: auto;
        }
        .log-line {
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 0.85rem;
            padding: 4px 0;
            border-bottom: 1px solid #2f3336;
        }
        .log-line.error { color: #f4212e; }
        .log-line.info { color: #1d9bf0; }
        .log-line.debug { color: #71767b; }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
        }
        .status-running { background: #00ba7c; color: #fff; }
        .status-stopped { background: #f4212e; color: #fff; }
        h2 {
            font-size: 1.5rem;
            margin-bottom: 20px;
            color: #e7e9ea;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Polymarket × Hyperliquid Arbitrage Bot</h1>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Bot Status</div>
                <div class="stat-value" id="bot-status">
                    <span class="status-badge status-stopped">Stopped</span>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Scans</div>
                <div class="stat-value blue" id="total-scans">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Opportunities Found</div>
                <div class="stat-value" id="opportunities">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Trades Executed</div>
                <div class="stat-value green" id="trades">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Polymarket Balance</div>
                <div class="stat-value" id="pm-balance">$0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Hyperliquid Balance</div>
                <div class="stat-value" id="hl-balance">$0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Errors</div>
                <div class="stat-value red" id="errors">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Last Scan</div>
                <div class="stat-value" style="font-size: 1.2rem" id="last-scan">Never</div>
            </div>
        </div>

        <h2>📋 Recent Logs</h2>
        <div class="log-container" id="logs">
            <div class="log-line">Loading...</div>
        </div>
    </div>

    <script>
        function updateDashboard() {
            fetch('/api/stats')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('total-scans').textContent = data.total_scans;
                    document.getElementById('opportunities').textContent = data.opportunities_found;
                    document.getElementById('trades').textContent = data.trades_executed;
                    document.getElementById('errors').textContent = data.errors;
                    document.getElementById('pm-balance').textContent = '$' + data.polymarket_balance;
                    document.getElementById('hl-balance').textContent = '$' + data.hyperliquid_balance;
                    document.getElementById('last-scan').textContent = data.last_scan;

                    const statusEl = document.getElementById('bot-status');
                    const statusClass = data.bot_status === 'Running' ? 'status-running' : 'status-stopped';
                    statusEl.innerHTML = `<span class="status-badge ${statusClass}">${data.bot_status}</span>`;
                });

            fetch('/api/logs')
                .then(r => r.json())
                .then(data => {
                    const logsEl = document.getElementById('logs');
                    logsEl.innerHTML = data.logs.map(line => {
                        let className = 'log-line';
                        if (line.includes('ERROR')) className += ' error';
                        else if (line.includes('INFO')) className += ' info';
                        else if (line.includes('DEBUG')) className += ' debug';
                        return `<div class="${className}">${escapeHtml(line)}</div>`;
                    }).join('');
                    logsEl.scrollTop = logsEl.scrollHeight;
                });
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Update every 2 seconds
        updateDashboard();
        setInterval(updateDashboard, 2000);
    </script>
</body>
</html>
    """

    with open('templates/dashboard.html', 'w') as f:
        f.write(html_template)

    print("🚀 Starting dashboard server...")
    print("📊 Open http://localhost:5000 in your browser")
    print("Press Ctrl+C to stop")

    app.run(host='0.0.0.0', port=5000, debug=False)
