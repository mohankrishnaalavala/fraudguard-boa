"""
FraudGuard Dashboard - Read-only UI for transaction monitoring
"""

import logging
import os
import json
from datetime import datetime
from typing import List, Dict, Any

import httpx
from flask import Flask, render_template, jsonify
import structlog

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Configuration
PORT = int(os.getenv("PORT", "8080"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
MCP_GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://mcp-gateway.fraudguard.svc.cluster.local:8080")
EXPLAIN_AGENT_URL = os.getenv("EXPLAIN_AGENT_URL", "http://explain-agent.fraudguard.svc.cluster.local:8080")
REFRESH_INTERVAL_SECONDS = int(os.getenv("REFRESH_INTERVAL_SECONDS", "10"))

# Set log level
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL))

app = Flask(__name__)

def get_risk_color(risk_score: float) -> str:
    """Get color class based on risk score"""
    if risk_score >= 0.8:
        return "danger"
    elif risk_score >= 0.6:
        return "warning"
    elif risk_score >= 0.3:
        return "info"
    else:
        return "success"

def get_action_icon(action: str) -> str:
    """Get icon for action type"""
    icons = {
        "hold": "🚨",
        "step-up": "⚠️",
        "notify": "⚡",
        "allow": "✅"
    }
    return icons.get(action, "❓")

async def fetch_transactions() -> List[Dict[str, Any]]:
    """Fetch recent transactions from MCP Gateway"""
    try:
        logger.info("fetching_transactions", url=f"{MCP_GATEWAY_URL}/api/recent-transactions")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{MCP_GATEWAY_URL}/api/recent-transactions",
                timeout=15.0
            )

            logger.info("mcp_gateway_response",
                       status_code=response.status_code,
                       headers=dict(response.headers))

            response.raise_for_status()

            data = response.json()
            transactions = data.get("transactions", [])
            logger.info("transactions_fetched",
                       count=len(transactions),
                       sample_transaction=transactions[0] if transactions else None)

            # Enhance transactions with display properties
            for txn in transactions:
                if txn.get("risk_score") is not None:
                    txn["risk_color"] = get_risk_color(float(txn["risk_score"]))
                    txn["risk_percentage"] = int(float(txn["risk_score"]) * 100)
                else:
                    txn["risk_color"] = "secondary"
                    txn["risk_percentage"] = 0
                    txn["risk_score"] = 0.0

                # Format timestamp
                if txn.get("timestamp"):
                    try:
                        if isinstance(txn["timestamp"], str):
                            timestamp = datetime.fromisoformat(txn["timestamp"].replace("Z", "+00:00"))
                        else:
                            timestamp = txn["timestamp"]
                        txn["formatted_time"] = timestamp.strftime("%H:%M:%S")
                        txn["formatted_date"] = timestamp.strftime("%Y-%m-%d")
                    except Exception as ts_error:
                        logger.warning("timestamp_parse_failed",
                                     timestamp=txn.get("timestamp"),
                                     error=str(ts_error))
                        txn["formatted_time"] = "Unknown"
                        txn["formatted_date"] = "Unknown"

            return transactions

    except httpx.TimeoutException as e:
        logger.error("mcp_gateway_timeout",
                    url=f"{MCP_GATEWAY_URL}/api/recent-transactions",
                    timeout=15.0,
                    error=str(e))
        return []
    except httpx.HTTPStatusError as e:
        logger.error("mcp_gateway_http_error",
                    status_code=e.response.status_code,
                    response_text=e.response.text,
                    url=f"{MCP_GATEWAY_URL}/api/recent-transactions",
                    error=str(e))
        return []
    except Exception as e:
        logger.error("transactions_fetch_failed",
                    url=f"{MCP_GATEWAY_URL}/api/recent-transactions",
                    error_type=type(e).__name__,
                    error=str(e))
        return []

async def fetch_audit_records() -> List[Dict[str, Any]]:
    """Fetch recent audit records from explain agent"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{EXPLAIN_AGENT_URL}/audit",
                params={"limit": 50},
                timeout=10.0
            )
            response.raise_for_status()

            records = response.json()
            logger.info("audit_records_fetched", count=len(records))

            # Enhance records with display properties
            for record in records:
                record["risk_color"] = get_risk_color(record["risk_score"])
                record["action_icon"] = get_action_icon(record["action"])
                record["risk_percentage"] = int(record["risk_score"] * 100)

                # Parse timestamp
                if isinstance(record["timestamp"], str):
                    record["timestamp"] = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))

                record["formatted_time"] = record["timestamp"].strftime("%H:%M:%S")
                record["formatted_date"] = record["timestamp"].strftime("%Y-%m-%d")

            return records

    except Exception as e:
        logger.error("audit_records_fetch_failed", error=str(e))
        return []

@app.route("/healthz")
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "dashboard",
        "timestamp": datetime.utcnow().isoformat()
    })

@app.route("/")
async def dashboard():
    """Main dashboard page with real-time data"""
    try:
        # Fetch real transaction data
        transactions = await fetch_transactions()

        # Calculate statistics
        stats = {
            "high_risk": 0,
            "medium_risk": 0,
            "low_risk": 0,
            "normal": 0
        }

        for txn in transactions:
            risk_level = txn.get("risk_level", "normal").lower()
            if risk_level == "high":
                stats["high_risk"] += 1
            elif risk_level == "medium":
                stats["medium_risk"] += 1
            elif risk_level == "low":
                stats["low_risk"] += 1
            else:
                stats["normal"] += 1

        # Get current timestamp
        current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        return render_template("dashboard.html",
                             transactions=transactions,
                             stats=stats,
                             current_time=current_time,
                             refresh_interval=REFRESH_INTERVAL_SECONDS * 1000)

    except Exception as e:
        logger.error("dashboard_render_failed", error=str(e))
        return render_template("error.html", error="Failed to load dashboard data")

@app.route("/api/records")
async def api_records():
    """API endpoint for fetching transaction records (for AJAX updates)"""
    try:
        transactions = await fetch_transactions()
        return jsonify(transactions)

    except Exception as e:
        logger.error("api_records_failed", error=str(e))
        return jsonify({"error": "Failed to fetch records"}), 500

@app.route("/api/stats")
async def api_stats():
    """API endpoint for fetching dashboard statistics"""
    try:
        transactions = await fetch_transactions()

        stats = {
            "high_risk": 0,
            "medium_risk": 0,
            "low_risk": 0,
            "normal": 0,
            "total": len(transactions)
        }

        for txn in transactions:
            risk_level = txn.get("risk_level", "normal").lower()
            if risk_level == "high":
                stats["high_risk"] += 1
            elif risk_level == "medium":
                stats["medium_risk"] += 1
            elif risk_level == "low":
                stats["low_risk"] += 1
            else:
                stats["normal"] += 1

        return jsonify(stats)

    except Exception as e:
        logger.error("api_stats_failed", error=str(e))
        return jsonify({"error": "Failed to fetch stats"}), 500

if __name__ == "__main__":
    logger.info("starting_dashboard", port=PORT, explain_agent_url=EXPLAIN_AGENT_URL)
    app.run(host="0.0.0.0", port=PORT, debug=False)
