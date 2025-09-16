"""
Action Orchestrator Service - Executes actions based on risk analysis
"""

import logging
import os
from datetime import datetime
from typing import Dict, Any

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
BOA_BASE_URL = os.getenv("BOA_BASE_URL", "http://frontend.boa.svc.cluster.local:80")
RISK_THRESHOLD_NOTIFY = float(os.getenv("RISK_THRESHOLD_NOTIFY", "0.3"))
RISK_THRESHOLD_STEPUP = float(os.getenv("RISK_THRESHOLD_STEPUP", "0.6"))
RISK_THRESHOLD_HOLD = float(os.getenv("RISK_THRESHOLD_HOLD", "0.8"))

# Set log level
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL))

app = FastAPI(
    title="Action Orchestrator",
    description="Executes actions based on risk analysis results",
    version="0.1.0"
)

class ActionRequest(BaseModel):
    """Action request model"""
    transaction_id: str = Field(..., description="Transaction ID")
    risk_score: float = Field(..., description="Risk score")
    action: str = Field(..., description="Action to execute")
    explanation: str = Field(..., description="User-friendly explanation")

class ActionResult(BaseModel):
    """Action execution result"""
    transaction_id: str = Field(..., description="Transaction ID")
    action: str = Field(..., description="Executed action")
    success: bool = Field(..., description="Whether action was successful")
    message: str = Field(..., description="Result message")
    timestamp: datetime = Field(..., description="Execution timestamp")

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "action-orchestrator", "timestamp": datetime.utcnow()}

async def execute_notify_action(transaction_id: str, explanation: str) -> Dict[str, Any]:
    """Execute notify action - send notification to user"""
    try:
        # In production, this would integrate with notification systems
        # For demo, we'll just log the notification
        logger.info(
            "notification_sent",
            transaction_id=transaction_id,
            explanation=explanation,
            action="notify"
        )

        return {
            "success": True,
            "message": f"Notification sent for transaction {transaction_id}"
        }

    except Exception as e:
        logger.error("notify_action_failed", transaction_id=transaction_id, error=str(e))
        return {
            "success": False,
            "message": f"Failed to send notification: {str(e)}"
        }

async def execute_stepup_action(transaction_id: str, explanation: str) -> Dict[str, Any]:
    """Execute step-up authentication action"""
    try:
        # In production, this would trigger step-up auth via BoA APIs
        # For demo, we'll simulate the API call
        logger.info(
            "stepup_auth_triggered",
            transaction_id=transaction_id,
            explanation=explanation,
            action="step-up"
        )

        # Simulate API call to BoA
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(
        #         f"{BOA_BASE_URL}/api/auth/stepup",
        #         json={"transaction_id": transaction_id, "reason": explanation},
        #         timeout=10.0
        #     )
        #     response.raise_for_status()

        return {
            "success": True,
            "message": f"Step-up authentication triggered for transaction {transaction_id}"
        }

    except Exception as e:
        logger.error("stepup_action_failed", transaction_id=transaction_id, error=str(e))
        return {
            "success": False,
            "message": f"Failed to trigger step-up auth: {str(e)}"
        }

async def execute_hold_action(transaction_id: str, explanation: str) -> Dict[str, Any]:
    """Execute hold action - temporarily hold the transaction"""
    try:
        # In production, this would call BoA APIs to hold the transaction
        # For demo, we'll simulate the API call
        logger.info(
            "transaction_held",
            transaction_id=transaction_id,
            explanation=explanation,
            action="hold"
        )

        # Simulate API call to BoA
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(
        #         f"{BOA_BASE_URL}/api/transactions/{transaction_id}/hold",
        #         json={"reason": explanation},
        #         timeout=10.0
        #     )
        #     response.raise_for_status()

        return {
            "success": True,
            "message": f"Transaction {transaction_id} placed on hold"
        }

    except Exception as e:
        logger.error("hold_action_failed", transaction_id=transaction_id, error=str(e))
        return {
            "success": False,
            "message": f"Failed to hold transaction: {str(e)}"
        }

async def execute_allow_action(transaction_id: str, explanation: str) -> Dict[str, Any]:
    """Execute allow action - transaction proceeds normally"""
    try:
        logger.info(
            "transaction_allowed",
            transaction_id=transaction_id,
            explanation=explanation,
            action="allow"
        )

        return {
            "success": True,
            "message": f"Transaction {transaction_id} allowed to proceed"
        }

    except Exception as e:
        logger.error("allow_action_failed", transaction_id=transaction_id, error=str(e))
        return {
            "success": False,
            "message": f"Failed to process allow action: {str(e)}"
        }

@app.post("/execute", response_model=ActionResult)
async def execute_action(request: ActionRequest):
    """Execute the specified action"""
    try:
        logger.info(
            "action_execution_started",
            transaction_id=request.transaction_id,
            action=request.action,
            risk_score=request.risk_score
        )

        # Execute the appropriate action
        if request.action == "notify":
            result = await execute_notify_action(request.transaction_id, request.explanation)
        elif request.action == "step-up":
            result = await execute_stepup_action(request.transaction_id, request.explanation)
        elif request.action == "hold":
            result = await execute_hold_action(request.transaction_id, request.explanation)
        elif request.action == "allow":
            result = await execute_allow_action(request.transaction_id, request.explanation)
        else:
            logger.error("unknown_action", action=request.action, transaction_id=request.transaction_id)
            raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")

        # Create action result
        action_result = ActionResult(
            transaction_id=request.transaction_id,
            action=request.action,
            success=result["success"],
            message=result["message"],
            timestamp=datetime.utcnow()
        )

        logger.info(
            "action_execution_completed",
            transaction_id=request.transaction_id,
            action=request.action,
            success=result["success"]
        )

        return action_result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "action_execution_failed",
            transaction_id=request.transaction_id,
            action=request.action,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Action execution failed")

@app.get("/thresholds")
async def get_risk_thresholds():
    """Get current risk thresholds"""
    return {
        "notify": RISK_THRESHOLD_NOTIFY,
        "step_up": RISK_THRESHOLD_STEPUP,
        "hold": RISK_THRESHOLD_HOLD
    }

if __name__ == "__main__":
    import uvicorn
    logger.info("starting_action_orchestrator", port=PORT, boa_base_url=BOA_BASE_URL)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
