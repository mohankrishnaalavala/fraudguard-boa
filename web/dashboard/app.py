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
    """Main dashboard page"""
    try:
        # Try to fetch records, but don't fail if service is unavailable
        try:
            records = await fetch_audit_records()
        except Exception as e:
            logger.warning("audit_service_unavailable", error=str(e))
            # Create demo data if service is unavailable
            records = [
                {
                    "transaction_id": "demo_001",
                    "risk_score": 0.2,
                    "action": "allow",
                    "explanation": "Normal transaction pattern",
                    "timestamp": datetime.utcnow(),
                    "risk_color": "success",
                    "action_icon": "✅",
                    "risk_percentage": 20,
                    "formatted_time": datetime.utcnow().strftime("%H:%M:%S"),
                    "formatted_date": datetime.utcnow().strftime("%Y-%m-%d")
                },
                {
                    "transaction_id": "demo_002",
                    "risk_score": 0.7,
                    "action": "review",
                    "explanation": "Unusual transaction amount",
                    "timestamp": datetime.utcnow(),
                    "risk_color": "warning",
                    "action_icon": "⚠️",
                    "risk_percentage": 70,
                    "formatted_time": datetime.utcnow().strftime("%H:%M:%S"),
                    "formatted_date": datetime.utcnow().strftime("%Y-%m-%d")
                }
            ]

        # Calculate summary statistics
        total_transactions = len(records)
        high_risk_count = sum(1 for r in records if r["risk_score"] >= 0.8)
        medium_risk_count = sum(1 for r in records if 0.6 <= r["risk_score"] < 0.8)
        low_risk_count = sum(1 for r in records if 0.3 <= r["risk_score"] < 0.6)
        normal_count = sum(1 for r in records if r["risk_score"] < 0.3)

        stats = {
            "total": total_transactions,
            "high_risk": high_risk_count,
            "medium_risk": medium_risk_count,
            "low_risk": low_risk_count,
            "normal": normal_count
        }

        return render_template(
            "dashboard.html",
            records=records,
            stats=stats,
            refresh_interval=REFRESH_INTERVAL_SECONDS * 1000,  # Convert to milliseconds
            current_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        )

    except Exception as e:
        logger.error("dashboard_render_failed", error=str(e))
        return render_template(
            "error.html",
            error="Failed to load dashboard data"
        ), 500

@app.route("/api/records")
async def api_records():
    """API endpoint for fetching records (for AJAX updates)"""
    try:
        records = await fetch_audit_records()
        return jsonify(records)

    except Exception as e:
        logger.error("api_records_failed", error=str(e))
        return jsonify({"error": "Failed to fetch records"}), 500

if __name__ == "__main__":
    logger.info("starting_dashboard", port=PORT, explain_agent_url=EXPLAIN_AGENT_URL)
    app.run(host="0.0.0.0", port=PORT, debug=False)
