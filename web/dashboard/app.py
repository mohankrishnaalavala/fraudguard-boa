"""
FraudGuard Dashboard - Read-only UI for transaction monitoring
"""

import logging
import os
import json
from datetime import datetime
from typing import List, Dict, Any

import httpx
from flask import Flask, render_template, jsonify, request
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
ACTION_ORCHESTRATOR_URL = os.getenv("ACTION_ORCHESTRATOR_URL", "http://action-orchestrator.fraudguard.svc.cluster.local:8080")
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

def fetch_transactions() -> List[Dict[str, Any]]:
    """Fetch recent transactions from MCP Gateway (sync)"""
    try:
        logger.debug("fetching_transactions", url=f"{MCP_GATEWAY_URL}/api/recent-transactions")

        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{MCP_GATEWAY_URL}/api/recent-transactions")

        logger.debug(
            "mcp_gateway_response",
            status_code=response.status_code,
        )

        response.raise_for_status()
        data = response.json()
        # Accept both shapes from MCP Gateway: either an object { transactions: [...] }
        # or a raw array [...]. Be tolerant to ensure metrics and records stay in sync.
        if isinstance(data, list):
            transactions = data
        else:
            transactions = data.get("transactions", [])

        # Log only safe summary to avoid serialization issues
        first_id = transactions[0].get("transaction_id") if transactions and isinstance(transactions[0], dict) else None
        logger.info("transactions_fetched", count=len(transactions), first_transaction_id=first_id)

        # Enhance transactions with display properties and safe defaults
        for txn in transactions:
            # amount default/normalize
            try:
                txn["amount"] = float(txn.get("amount", 0.0))
            except Exception:
                txn["amount"] = 0.0

            if txn.get("risk_score") is not None:
                try:
                    score = float(txn["risk_score"])
                except Exception:
                    score = 0.0
            else:
                score = 0.0
            txn["risk_score"] = score
            txn["risk_color"] = get_risk_color(score)
            txn["risk_percentage"] = int(score * 100)


            # Normalize/derive risk_level if missing or pending to keep UI and metrics consistent
            level = str(txn.get("risk_level", "")).lower().strip()
            if level not in {"high", "medium", "low"}:
                # Match gateway thresholds
                if score > 0.7:
                    level = "high"
                elif score > 0.4:
                    level = "medium"
                else:
                    level = "low"
                txn["risk_level"] = level

            # Format timestamp
            if txn.get("timestamp"):
                try:
                    if isinstance(txn["timestamp"], str):
                        ts = datetime.fromisoformat(txn["timestamp"].replace("Z", "+00:00"))
                    else:
                        ts = txn["timestamp"]
                    txn["formatted_time"] = ts.strftime("%H:%M:%S")
                    txn["formatted_date"] = ts.strftime("%Y-%m-%d")
                except Exception as ts_error:
                    logger.debug("timestamp_parse_skip", error=str(ts_error))
                    txn["formatted_time"] = "Unknown"
                    txn["formatted_date"] = "Unknown"

        return transactions

    except httpx.TimeoutException as e:
        logger.error("mcp_gateway_timeout", url=f"{MCP_GATEWAY_URL}/api/recent-transactions", timeout=15.0, error=str(e))
        return []
    except httpx.HTTPStatusError as e:
        logger.error("mcp_gateway_http_error", status_code=e.response.status_code, url=f"{MCP_GATEWAY_URL}/api/recent-transactions", error=str(e))
        return []
    except Exception as e:
        logger.error("transactions_fetch_failed", url=f"{MCP_GATEWAY_URL}/api/recent-transactions", error_type=type(e).__name__, error=str(e))
        return []

def fetch_audit_records() -> List[Dict[str, Any]]:
    """Fetch recent audit records from explain agent (sync)"""
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{EXPLAIN_AGENT_URL}/audit", params={"limit": 50})
        response.raise_for_status()

        records = response.json()
        logger.info("audit_records_fetched", count=len(records))

        # Enhance records with display properties
        for record in records:
            try:
                score = float(record.get("risk_score", 0))
            except Exception:
                score = 0.0
            record["risk_color"] = get_risk_color(score)
            record["action_icon"] = get_action_icon(record.get("action", ""))
            record["risk_percentage"] = int(score * 100)

            # Parse timestamp
            ts_raw = record.get("timestamp")
            if isinstance(ts_raw, str):
                try:
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    record["formatted_time"] = ts.strftime("%H:%M:%S")
                    record["formatted_date"] = ts.strftime("%Y-%m-%d")
                except Exception:
                    record["formatted_time"] = "Unknown"
                    record["formatted_date"] = "Unknown"

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
def dashboard():
    """Main dashboard page with real-time data (sync)"""
    try:
        transactions = fetch_transactions()

        stats = {"high_risk": 0, "medium_risk": 0, "low_risk": 0}
        for txn in transactions:
            risk_level = str(txn.get("risk_level", "")).lower()
            if risk_level == "high":
                stats["high_risk"] += 1
            elif risk_level == "medium":
                stats["medium_risk"] += 1
            elif risk_level == "low":
                stats["low_risk"] += 1
            else:
                # default any other value into low to maintain tri-level classification
                stats["low_risk"] += 1

        current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        return render_template(
            "dashboard.html",
            transactions=transactions,
            stats=stats,
            current_time=current_time,
            refresh_interval=REFRESH_INTERVAL_SECONDS * 1000,
        )
    except Exception as e:
        logger.error("dashboard_render_failed", error=str(e))
        return render_template("error.html", error="Failed to load dashboard data")

@app.route("/api/records")
def api_records():
    """API endpoint for fetching transaction records (for AJAX updates)"""
    try:
        transactions = fetch_transactions()
        return jsonify(transactions)
    except Exception as e:
        logger.error("api_records_failed", error=str(e))
        return jsonify({"error": "Failed to fetch records"}), 500

@app.route("/api/stats")
def api_stats():
    """API endpoint for fetching dashboard statistics"""
    try:
        transactions = fetch_transactions()
        stats = {"high_risk": 0, "medium_risk": 0, "low_risk": 0, "total": len(transactions)}
        for txn in transactions:
            risk_level = str(txn.get("risk_level", "")).lower()
            if risk_level == "high":
                stats["high_risk"] += 1
            elif risk_level == "medium":
                stats["medium_risk"] += 1
            elif risk_level == "low":
                stats["low_risk"] += 1
            else:
                stats["low_risk"] += 1
        return jsonify(stats)
    except Exception as e:
        logger.error("api_stats_failed", error=str(e))
        return jsonify({"error": "Failed to fetch stats"}), 500

@app.route("/api/notify", methods=["POST"])
def api_notify():
    """Trigger a user notification via action-orchestrator for a given transaction."""
    try:
        payload = request.get_json(force=True) or {}
        transaction_id = payload.get("transaction_id")
        try:
            risk_score = float(payload.get("risk_score", 0))
        except Exception:
            risk_score = 0.0
        explanation = payload.get("explanation", "Suspicious activity detected")
        if not transaction_id:
            return jsonify({"error": "transaction_id is required"}), 400

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{ACTION_ORCHESTRATOR_URL}/execute",
                json={
                    "transaction_id": transaction_id,
                    "risk_score": risk_score,
                    "action": "notify",
                    "explanation": explanation
                }
            )
        resp.raise_for_status()
        return jsonify(resp.json())

    except httpx.HTTPError as e:
        logger.error("notify_action_http_error", error=str(e))
        return jsonify({"error": "Failed to trigger notify action"}), 502
    except Exception as e:
        logger.error("notify_action_failed", error=str(e))
        return jsonify({"error": "Internal error"}), 500

if __name__ == "__main__":
    logger.info("starting_dashboard", port=PORT, explain_agent_url=EXPLAIN_AGENT_URL)
    app.run(host="0.0.0.0", port=PORT, debug=False)
