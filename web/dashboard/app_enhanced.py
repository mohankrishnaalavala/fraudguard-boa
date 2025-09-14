#!/usr/bin/env python3
"""
Enhanced FraudGuard Dashboard with Real Data
"""

import sys
import traceback
import logging
import json
import httpx
from datetime import datetime
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    from flask import Flask, render_template_string, jsonify
    logger.info("Flask imported successfully")
except Exception as e:
    logger.error(f"Failed to import Flask: {e}")
    sys.exit(1)

app = Flask(__name__)
logger.info("Flask app created successfully")

# Service URLs
EXPLAIN_AGENT_URL = "http://explain-agent.fraudguard.svc.cluster.local:8080"
MCP_GATEWAY_URL = "http://mcp-gateway.fraudguard.svc.cluster.local:8080"
RISK_SCORER_URL = "http://risk-scorer.fraudguard.svc.cluster.local:8080"

# Enhanced HTML template with real data
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🛡️ FraudGuard Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { 
            max-width: 1200px; 
            margin: 0 auto; 
            background: white; 
            border-radius: 15px; 
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .header { 
            background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
            color: white; 
            padding: 30px; 
            text-align: center; 
        }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; }
        .header p { font-size: 1.2em; opacity: 0.9; }
        .stats-grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
            gap: 20px; 
            padding: 30px; 
        }
        .stat-card { 
            background: white; 
            border-radius: 10px; 
            padding: 25px; 
            text-align: center; 
            box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            border-left: 5px solid;
            transition: transform 0.3s ease;
        }
        .stat-card:hover { transform: translateY(-5px); }
        .stat-card.high-risk { border-left-color: #e74c3c; }
        .stat-card.medium-risk { border-left-color: #f39c12; }
        .stat-card.low-risk { border-left-color: #f1c40f; }
        .stat-card.normal { border-left-color: #27ae60; }
        .stat-number { font-size: 3em; font-weight: bold; margin-bottom: 10px; }
        .stat-label { font-size: 1.1em; color: #7f8c8d; text-transform: uppercase; letter-spacing: 1px; }
        .transactions-section { 
            padding: 30px; 
            background: #f8f9fa; 
        }
        .section-title { 
            font-size: 1.8em; 
            margin-bottom: 20px; 
            color: #2c3e50; 
            border-bottom: 3px solid #3498db; 
            padding-bottom: 10px; 
        }
        .transaction-list { 
            background: white; 
            border-radius: 10px; 
            overflow: hidden; 
            box-shadow: 0 5px 15px rgba(0,0,0,0.08);
        }
        .transaction-item { 
            padding: 20px; 
            border-bottom: 1px solid #ecf0f1; 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
        }
        .transaction-item:last-child { border-bottom: none; }
        .transaction-info h4 { color: #2c3e50; margin-bottom: 5px; }
        .transaction-info p { color: #7f8c8d; font-size: 0.9em; }
        .risk-badge { 
            padding: 8px 16px; 
            border-radius: 20px; 
            color: white; 
            font-weight: bold; 
            font-size: 0.8em; 
            text-transform: uppercase; 
        }
        .risk-high { background: #e74c3c; }
        .risk-medium { background: #f39c12; }
        .risk-low { background: #f1c40f; color: #2c3e50; }
        .risk-normal { background: #27ae60; }
        .footer { 
            background: #34495e; 
            color: white; 
            text-align: center; 
            padding: 20px; 
        }
        .status-indicator { 
            display: inline-block; 
            width: 12px; 
            height: 12px; 
            border-radius: 50%; 
            margin-right: 8px; 
        }
        .status-healthy { background: #27ae60; }
        .status-warning { background: #f39c12; }
        .status-error { background: #e74c3c; }
        .refresh-info { 
            background: #3498db; 
            color: white; 
            padding: 10px; 
            text-align: center; 
            font-size: 0.9em; 
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🛡️ FraudGuard Dashboard</h1>
            <p>Real-time Fraud Detection & Prevention System</p>
        </div>
        
        <div class="refresh-info">
            <span class="status-indicator status-healthy"></span>
            Last updated: {{ current_time }} | Auto-refresh: {{ refresh_interval }}s
        </div>
        
        <div class="stats-grid">
            <div class="stat-card high-risk">
                <div class="stat-number" style="color: #e74c3c;">{{ stats.high_risk }}</div>
                <div class="stat-label">High Risk</div>
            </div>
            <div class="stat-card medium-risk">
                <div class="stat-number" style="color: #f39c12;">{{ stats.medium_risk }}</div>
                <div class="stat-label">Medium Risk</div>
            </div>
            <div class="stat-card low-risk">
                <div class="stat-number" style="color: #f1c40f;">{{ stats.low_risk }}</div>
                <div class="stat-label">Low Risk</div>
            </div>
            <div class="stat-card normal">
                <div class="stat-number" style="color: #27ae60;">{{ stats.normal }}</div>
                <div class="stat-label">Normal</div>
            </div>
        </div>
        
        <div class="transactions-section">
            <h2 class="section-title">Recent Transactions</h2>
            <div class="transaction-list">
                {% for transaction in transactions %}
                <div class="transaction-item">
                    <div class="transaction-info">
                        <h4>{{ transaction.merchant }} - ${{ "%.2f"|format(transaction.amount) }}</h4>
                        <p>ID: {{ transaction.transaction_id }} | {{ transaction.timestamp }}</p>
                    </div>
                    <div class="risk-badge risk-{{ transaction.risk_level }}">
                        {{ transaction.risk_level.upper() }}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        
        <div class="footer">
            <p>🚀 FraudGuard v1.0 | Powered by AI & Machine Learning</p>
            <p>Services: 
                <span class="status-indicator status-{{ service_status.mcp_gateway }}"></span>MCP Gateway
                <span class="status-indicator status-{{ service_status.explain_agent }}"></span>Explain Agent
                <span class="status-indicator status-{{ service_status.risk_scorer }}"></span>Risk Scorer
            </p>
        </div>
    </div>
    
    <script>
        // Auto-refresh the page
        setTimeout(function() {
            window.location.reload();
        }, {{ refresh_interval * 1000 }});
    </script>
</body>
</html>"""

def check_service_health(url: str) -> str:
    """Check if a service is healthy"""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{url}/healthz")
            return "healthy" if response.status_code == 200 else "warning"
    except Exception:
        return "error"

def get_service_data():
    """Fetch data from all services"""
    try:
        # Check service health
        service_status = {
            "mcp_gateway": check_service_health(MCP_GATEWAY_URL),
            "explain_agent": check_service_health(EXPLAIN_AGENT_URL),
            "risk_scorer": check_service_health(RISK_SCORER_URL)
        }

        # Get real transaction data from MCP Gateway
        transactions = []
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"{MCP_GATEWAY_URL}/api/recent-transactions?limit=10")
                if response.status_code == 200:
                    data = response.json()
                    raw_transactions = data.get("transactions", [])

                    for txn in raw_transactions:
                        # Determine risk level based on risk score or amount
                        risk_level = txn.get("risk_level", "pending")
                        if risk_level == "pending":
                            # Simple rule-based risk assessment for demo
                            amount = txn.get("amount", 0)
                            if amount > 1000:
                                risk_level = "high"
                            elif amount > 500:
                                risk_level = "medium"
                            elif amount > 100:
                                risk_level = "low"
                            else:
                                risk_level = "normal"

                        # Format timestamp
                        timestamp = txn.get("timestamp", "")
                        if timestamp:
                            try:
                                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                formatted_timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
                            except:
                                formatted_timestamp = timestamp
                        else:
                            formatted_timestamp = "Unknown"

                        transactions.append({
                            "transaction_id": txn.get("transaction_id", "unknown"),
                            "merchant": txn.get("merchant", "Unknown Merchant"),
                            "amount": txn.get("amount", 0.0),
                            "timestamp": formatted_timestamp,
                            "risk_level": risk_level
                        })

                else:
                    logger.warning(f"Failed to fetch transactions: {response.status_code}")

        except Exception as e:
            logger.error(f"Error fetching transactions from MCP Gateway: {e}")

        # If no real transactions, add some sample data
        if not transactions:
            transactions = [
                {
                    "transaction_id": "sample_001",
                    "merchant": "Sample Store",
                    "amount": 89.99,
                    "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "risk_level": "normal"
                }
            ]

        # Calculate stats
        stats = {
            "high_risk": len([t for t in transactions if t["risk_level"] == "high"]),
            "medium_risk": len([t for t in transactions if t["risk_level"] == "medium"]),
            "low_risk": len([t for t in transactions if t["risk_level"] == "low"]),
            "normal": len([t for t in transactions if t["risk_level"] == "normal"])
        }

        return {
            "service_status": service_status,
            "transactions": transactions,
            "stats": stats
        }

    except Exception as e:
        logger.error(f"Error fetching service data: {e}")
        # Return fallback data
        return {
            "service_status": {"mcp_gateway": "error", "explain_agent": "error", "risk_scorer": "error"},
            "transactions": [],
            "stats": {"high_risk": 0, "medium_risk": 0, "low_risk": 0, "normal": 0}
        }

@app.route("/healthz")
def health_check():
    """Health check endpoint"""
    try:
        logger.info("Health check called")
        response = {
            "status": "healthy",
            "service": "dashboard-enhanced",
            "timestamp": datetime.utcnow().isoformat(),
            "python_version": sys.version,
            "flask_version": getattr(Flask, '__version__', 'unknown')
        }
        logger.info(f"Health check response: {response}")
        return response
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        logger.error(traceback.format_exc())
        return {"error": str(e)}, 500

@app.route("/")
def dashboard():
    """Enhanced dashboard with real data"""
    try:
        logger.info("Dashboard route called")
        
        # Get data from services
        data = get_service_data()
        
        # Render template
        html_content = render_template_string(
            DASHBOARD_HTML,
            current_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            refresh_interval=10,
            **data
        )
        
        logger.info("Dashboard rendered successfully")
        return html_content
        
    except Exception as e:
        logger.error(f"Dashboard route failed: {e}")
        logger.error(traceback.format_exc())
        
        error_html = f"""<!DOCTYPE html>
<html>
<head><title>Dashboard Error</title></head>
<body>
    <h1>Dashboard Error</h1>
    <p>Error: {str(e)}</p>
    <pre>{traceback.format_exc()}</pre>
</body>
</html>"""
        return error_html, 500

if __name__ == "__main__":
    logger.info("Starting enhanced Flask dashboard")
    try:
        app.run(host="0.0.0.0", port=8080, debug=True)
    except Exception as e:
        logger.error(f"Failed to start Flask app: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)
