"""
Risk Scorer Service - Uses Gemini to analyze transaction risk
"""

import logging
import os
import json
from datetime import datetime
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "PLACEHOLDER_GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_PROJECT_ID = os.getenv("GEMINI_PROJECT_ID", "PROJECT_ID")
GEMINI_LOCATION = os.getenv("GEMINI_LOCATION", "us-central1")
USE_VERTEX_AI = os.getenv("USE_VERTEX_AI", "true").lower() == "true"
MCP_GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://mcp-gateway.fraudguard.svc.cluster.local:8080")
EXPLAIN_AGENT_URL = os.getenv("EXPLAIN_AGENT_URL", "http://explain-agent.fraudguard.svc.cluster.local:8080")

# Set log level
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL))

app = FastAPI(
    title="Risk Scorer",
    description="Analyzes transaction risk using Gemini AI",
    version="0.1.0"
)

class Transaction(BaseModel):
    """Transaction input model"""
    transaction_id: str = Field(..., description="Unique transaction ID")
    account_id: str = Field(..., description="Account ID")
    amount: float = Field(..., description="Transaction amount")
    merchant: str = Field(..., description="Merchant name")
    category: str = Field(..., description="Transaction category")
    timestamp: datetime = Field(..., description="Transaction timestamp")
    location: Optional[str] = Field(None, description="Transaction location")

class RiskScore(BaseModel):
    """Risk score output model"""
    transaction_id: str = Field(..., description="Transaction ID")
    risk_score: float = Field(..., description="Risk score between 0 and 1")
    rationale: str = Field(..., description="AI-generated rationale")
    timestamp: datetime = Field(..., description="Analysis timestamp")

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "risk-scorer", "timestamp": datetime.utcnow()}

def create_risk_analysis_prompt(transaction: Transaction) -> str:
    """Create a privacy-safe prompt for Gemini analysis"""
    # Remove PII and create compact features
    prompt = f"""
Analyze this transaction for fraud risk. Return a JSON response with risk_score (0.0-1.0) and rationale.

Transaction Features:
- Amount: ${transaction.amount:.2f}
- Category: {transaction.category}
- Merchant Type: {transaction.merchant.split('_')[0] if '_' in transaction.merchant else 'unknown'}
- Time: {transaction.timestamp.strftime('%H:%M')} on {transaction.timestamp.strftime('%A')}
- Location: {transaction.location or 'unknown'}

Consider these fraud indicators:
- Unusual amounts for category
- Off-hours transactions
- High-risk merchant types
- Geographic anomalies

Response format:
{{
    "risk_score": 0.0-1.0,
    "rationale": "Brief explanation of risk factors"
}}
"""

async def fetch_account_history(account_id: str, limit: int = 100) -> list[dict]:
    """Retrieve recent transactions for the account from MCP Gateway for RAG."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{MCP_GATEWAY_URL}/accounts/{account_id}/transactions", params={"limit": limit})
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning("history_fetch_failed", account_id=account_id, error=str(e))
    return []

def summarize_history_for_rag(history: list[dict]) -> dict:
    """Summarize history into compact stats: known recipients, typical amounts, time windows."""
    from collections import defaultdict
    import statistics
    recipients = defaultdict(list)
    hours = []
    amounts = []
    for tx in history:
        merchant = (tx.get("merchant") or "").lower()
        amounts.append(float(tx.get("amount", 0)))
        ts = tx.get("timestamp") or ""
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            hours.append(dt.hour)
        except Exception:
            pass
        if merchant.startswith("acct:"):
            recipients[merchant].append(float(tx.get("amount", 0)))
    top_known = []
    for m, vals in recipients.items():
        try:
            typical = statistics.median(vals)
        except statistics.StatisticsError:
            typical = vals[0] if vals else 0
        top_known.append({"recipient": m, "count": len(vals), "typical_amount": round(typical, 2)})
    top_known.sort(key=lambda x: x["count"], reverse=True)
    typical_amount = round(statistics.median(amounts), 2) if amounts else 0
    common_hours = []
    if hours:
        from collections import Counter
        common_hours = [h for h, _ in Counter(hours).most_common(3)]
    return {
        "known_recipients": top_known[:5],
        "typical_amount": typical_amount,
        "common_hours": common_hours,
        "history_count": len(history)
    }

def build_vertex_prompt(transaction: dict, rag_summary: dict) -> str:
    """Construct a Vertex AI prompt with structured context from RAG summary."""
    return (
        "You are an AI fraud analyst. Analyze the transaction with context. "
        "Return strict JSON with keys: risk_score (0.0-1.0), rationale (short).\n"
        f"Transaction: {json.dumps(transaction, default=str)}\n"
        f"Context: {json.dumps(rag_summary, default=str)}\n"
        "Guidelines:\n"
        "- Flag new/unknown recipients above $500 as higher risk.\n"
        "- If recipient is known with typical high amount (e.g., $1500), lower risk.\n"
        "- Consider unusual time (02:00-04:00) and deviation from typical amounts.\n"
        "- Consider recent frequency bursts. Keep rationale concise."
    )

async def call_vertex_ai(prompt: str) -> dict:
    """Call Vertex AI Generative API (Gemini) using ADC. Fallback to mock on error."""
    try:
        import google.auth
        from google.auth.transport.requests import Request
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(Request())
        token = credentials.token
        url = (
            f"https://{GEMINI_LOCATION}-aiplatform.googleapis.com/v1/"
            f"projects/{GEMINI_PROJECT_ID}/locations/{GEMINI_LOCATION}/publishers/google/models/{GEMINI_MODEL}:generateContent"
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 256}
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=body)
            resp.raise_for_status()
            data = resp.json()
            # Extract first text part
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            try:
                return json.loads(text)
            except Exception:
                # Attempt to extract JSON substring
                import re
                m = re.search(r"\{[\s\S]*\}", text)
                return json.loads(m.group(0)) if m else {"risk_score": 0.5, "rationale": "Unparsable AI output"}
    except Exception as e:
        logger.error("vertex_ai_error", error=str(e))
        return {"risk_score": 0.5, "rationale": "Vertex AI error - fallback used"}

    return {"risk_score": 0.5, "rationale": "No AI response - default applied"}

async def call_gemini_api(prompt: str) -> dict:
    """Call Gemini API for risk analysis"""
    try:
        # For demo purposes, return mock response
        # In production, implement actual Gemini API call
        if GEMINI_API_KEY == "PLACEHOLDER_GEMINI_API_KEY":
            logger.info("using_mock_gemini_response")

            # Intelligent rule-based mock scoring for demo
            import re

            # Extract transaction details from prompt for intelligent analysis
            amount_match = re.search(r'"amount":\s*(\d+\.?\d*)', prompt)
            amount = float(amount_match.group(1)) if amount_match else 0

            merchant_match = re.search(r'"merchant":\s*"([^"]*)"', prompt)
            merchant = merchant_match.group(1) if merchant_match else ""

            time_match = re.search(r'"timestamp":\s*"([^"]*)"', prompt)
            timestamp = time_match.group(1) if time_match else ""

            # Intelligent risk scoring based on patterns
            risk_score = 0.1  # Base risk
            risk_factors = []

            # Amount-based risk
            if amount > 1000:
                risk_score += 0.4
                risk_factors.append(f"High amount transaction (${amount})")
            elif amount > 500:
                risk_score += 0.2
                risk_factors.append(f"Medium amount transaction (${amount})")

            # Merchant-based risk
            suspicious_merchants = ["suspicious", "unknown", "cash", "atm", "foreign"]
            if any(word in merchant.lower() for word in suspicious_merchants):
                risk_score += 0.3
                risk_factors.append(f"Suspicious merchant: {merchant}")

            # Time-based risk
            if "T2" in timestamp or "T0" in timestamp:  # Late night/early morning
                risk_score += 0.2
                risk_factors.append("Late night transaction")

            # Category-based patterns
            if "electronics" in merchant.lower():
                risk_score += 0.1
                risk_factors.append("High-value electronics purchase")
            elif "coffee" in merchant.lower() or "restaurant" in merchant.lower():
                risk_score -= 0.1  # Lower risk for common purchases
                risk_factors.append("Common merchant type")

            # Cap risk score
            risk_score = min(risk_score, 0.95)
            risk_score = max(risk_score, 0.05)

            # Generate rationale
            if risk_score > 0.7:
                rationale = f"HIGH RISK: {', '.join(risk_factors[:3])}"
            elif risk_score > 0.4:
                rationale = f"MEDIUM RISK: {', '.join(risk_factors[:2])}"
            else:
                rationale = f"LOW RISK: Standard transaction pattern"

            return {
                "risk_score": round(risk_score, 2),
                "rationale": rationale
            }

        # Production Gemini API call would go here
        # Example structure:
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(
        #         f"https://{GEMINI_LOCATION}-aiplatform.googleapis.com/v1/projects/{GEMINI_PROJECT_ID}/locations/{GEMINI_LOCATION}/publishers/google/models/{GEMINI_MODEL}:generateContent",
        #         headers={
        #             "Authorization": f"Bearer {GEMINI_API_KEY}",
        #             "Content-Type": "application/json"
        #         },
        #         json={
        #             "contents": [{"parts": [{"text": prompt}]}],
        #             "generationConfig": {
        #                 "temperature": 0.1,
        #                 "maxOutputTokens": 256
        #             }
        #         },
        #         timeout=30.0
        #     )
        #     response.raise_for_status()
        #     return parse_gemini_response(response.json())

    except Exception as e:
        logger.error("gemini_api_error", error=str(e))
        # Fallback to conservative scoring
        return {
            "risk_score": 0.5,
            "rationale": "Unable to analyze - manual review recommended"
        }

async def send_to_explain_agent(risk_result: RiskScore):
    """Send risk analysis result to explain agent"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{EXPLAIN_AGENT_URL}/process",
                json=risk_result.dict(),
                timeout=10.0
            )
            response.raise_for_status()

            logger.info(
                "result_sent_to_explain_agent",
                transaction_id=risk_result.transaction_id
            )

    except httpx.HTTPError as e:
        logger.error(
            "explain_agent_send_failed",
            transaction_id=risk_result.transaction_id,
            error=str(e)
        )

@app.post("/analyze", response_model=RiskScore)
async def analyze_transaction(transaction: Transaction):
    """Analyze transaction risk using Vertex AI with RAG (fallback to mock)."""
    try:
        logger.info(
            "risk_analysis_started",
            transaction_id=transaction.transaction_id,
            amount=transaction.amount,
            category=transaction.category
        )

        # RAG: fetch and summarize account history
        history = await fetch_account_history(transaction.account_id, limit=100)
        rag_summary = summarize_history_for_rag(history)

        # Build Vertex prompt with RAG context
        tx_payload = {
            "transaction_id": transaction.transaction_id,
            "account_id": transaction.account_id,
            "amount": transaction.amount,
            "merchant": transaction.merchant,
            "category": transaction.category,
            "timestamp": transaction.timestamp.isoformat(),
            "location": transaction.location,
        }
        prompt = build_vertex_prompt(tx_payload, rag_summary)

        # Prefer Vertex AI call when enabled and configured
        if USE_VERTEX_AI and GEMINI_PROJECT_ID != "PROJECT_ID":
            ai_result = await call_vertex_ai(prompt)
        else:
            # Fallback to local mock Gemini logic
            # Reuse the older prompt generator for compatibility
            legacy_prompt = create_risk_analysis_prompt(transaction)
            ai_result = await call_gemini_api(legacy_prompt)

        # Normalize result
        score_val = float(ai_result.get("risk_score", 0.5))
        rationale_val = ai_result.get("rationale", "No rationale provided")

        # Create risk score response
        risk_score = RiskScore(
            transaction_id=transaction.transaction_id,
            risk_score=round(min(max(score_val, 0.0), 1.0), 4),
            rationale=rationale_val,
            timestamp=datetime.utcnow()
        )

        logger.info(
            "risk_analysis_completed",
            transaction_id=transaction.transaction_id,
            risk_score=risk_score.risk_score
        )

        # Send to explain agent for further processing
        await send_to_explain_agent(risk_score)

        return risk_score

    except Exception as e:
        logger.error(
            "risk_analysis_failed",
            transaction_id=transaction.transaction_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Risk analysis failed")

if __name__ == "__main__":
    import uvicorn
    logger.info("starting_risk_scorer", port=PORT, gemini_model=GEMINI_MODEL)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
