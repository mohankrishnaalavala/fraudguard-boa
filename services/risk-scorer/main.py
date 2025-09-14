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
    return prompt

async def call_gemini_api(prompt: str) -> dict:
    """Call Gemini API for risk analysis"""
    try:
        # For demo purposes, return mock response
        # In production, implement actual Gemini API call
        if GEMINI_API_KEY == "PLACEHOLDER_GEMINI_API_KEY":
            logger.info("using_mock_gemini_response")

            # Simple rule-based mock scoring for demo
            if "restaurant" in prompt.lower() and "22:" in prompt:
                return {
                    "risk_score": 0.7,
                    "rationale": "Late night restaurant transaction - unusual pattern"
                }
            elif "online" in prompt.lower() and "$" in prompt and "500" in prompt:
                return {
                    "risk_score": 0.8,
                    "rationale": "High-value online transaction - requires verification"
                }
            else:
                return {
                    "risk_score": 0.2,
                    "rationale": "Normal transaction pattern - low risk"
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
    """Analyze transaction risk using Gemini"""
    try:
        logger.info(
            "risk_analysis_started",
            transaction_id=transaction.transaction_id,
            amount=transaction.amount,
            category=transaction.category
        )

        # Create privacy-safe prompt
        prompt = create_risk_analysis_prompt(transaction)

        # Call Gemini API
        gemini_result = await call_gemini_api(prompt)

        # Create risk score response
        risk_score = RiskScore(
            transaction_id=transaction.transaction_id,
            risk_score=gemini_result["risk_score"],
            rationale=gemini_result["rationale"],
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
