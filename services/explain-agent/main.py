"""
Explain Agent Service - Processes risk analysis results and creates user-friendly explanations
"""

import logging
import os
import sqlite3
from datetime import datetime
from typing import List, Optional

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
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///tmp/audit.db")
ACTION_ORCHESTRATOR_URL = os.getenv("ACTION_ORCHESTRATOR_URL", "http://action-orchestrator.fraudguard.svc.cluster.local:8080")

# Set log level
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL))

app = FastAPI(
    title="Explain Agent",
    description="Processes risk analysis and creates user-friendly explanations",
    version="0.1.0"
)

class RiskAnalysis(BaseModel):
    """Risk analysis input model"""
    transaction_id: str = Field(..., description="Transaction ID")
    risk_score: float = Field(..., description="Risk score between 0 and 1")
    rationale: str = Field(..., description="AI-generated rationale")
    timestamp: datetime = Field(..., description="Analysis timestamp")

class AuditRecord(BaseModel):
    """Audit record model"""
    id: Optional[int] = Field(None, description="Record ID")
    transaction_id: str = Field(..., description="Transaction ID")
    risk_score: float = Field(..., description="Risk score")
    rationale: str = Field(..., description="AI rationale")
    explanation: str = Field(..., description="User-friendly explanation")
    action: str = Field(..., description="Recommended action")
    timestamp: datetime = Field(..., description="Record timestamp")

# Initialize database
def init_database():
    """Initialize SQLite database for audit records"""
    db_path = DATABASE_URL.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id TEXT UNIQUE NOT NULL,
            risk_score REAL NOT NULL,
            rationale TEXT NOT NULL,
            explanation TEXT NOT NULL,
            action TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_database()

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "explain-agent", "timestamp": datetime.utcnow()}

def create_user_friendly_explanation(risk_score: float, rationale: str) -> str:
    """Convert AI rationale to user-friendly explanation"""
    if risk_score >= 0.8:
        return f"🚨 High Risk: {rationale}. This transaction requires immediate attention."
    elif risk_score >= 0.6:
        return f"⚠️ Medium Risk: {rationale}. Additional verification recommended."
    elif risk_score >= 0.3:
        return f"⚡ Low Risk: {rationale}. Monitor for patterns."
    else:
        return f"✅ Normal: {rationale}. Transaction appears legitimate."

def determine_action(risk_score: float) -> str:
    """Determine recommended action based on risk score"""
    if risk_score >= 0.8:
        return "hold"
    elif risk_score >= 0.6:
        return "step-up"
    elif risk_score >= 0.3:
        return "notify"
    else:
        return "allow"

def save_audit_record(record: AuditRecord):
    """Save audit record to database"""
    db_path = DATABASE_URL.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO audit_records 
            (transaction_id, risk_score, rationale, explanation, action, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            record.transaction_id,
            record.risk_score,
            record.rationale,
            record.explanation,
            record.action,
            record.timestamp.isoformat()
        ))
        
        conn.commit()
        logger.info("audit_record_saved", transaction_id=record.transaction_id)
        
    except Exception as e:
        logger.error("audit_record_save_failed", transaction_id=record.transaction_id, error=str(e))
        raise
    finally:
        conn.close()

async def send_to_action_orchestrator(record: AuditRecord):
    """Send processed record to action orchestrator"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{ACTION_ORCHESTRATOR_URL}/execute",
                json={
                    "transaction_id": record.transaction_id,
                    "risk_score": record.risk_score,
                    "action": record.action,
                    "explanation": record.explanation
                },
                timeout=10.0
            )
            response.raise_for_status()
            
            logger.info(
                "action_orchestrator_notified",
                transaction_id=record.transaction_id,
                action=record.action
            )
            
    except httpx.HTTPError as e:
        logger.error(
            "action_orchestrator_failed",
            transaction_id=record.transaction_id,
            error=str(e)
        )

@app.post("/process", response_model=AuditRecord)
async def process_risk_analysis(analysis: RiskAnalysis):
    """Process risk analysis and create audit record"""
    try:
        logger.info(
            "processing_risk_analysis",
            transaction_id=analysis.transaction_id,
            risk_score=analysis.risk_score
        )
        
        # Create user-friendly explanation
        explanation = create_user_friendly_explanation(analysis.risk_score, analysis.rationale)
        
        # Determine recommended action
        action = determine_action(analysis.risk_score)
        
        # Create audit record
        audit_record = AuditRecord(
            transaction_id=analysis.transaction_id,
            risk_score=analysis.risk_score,
            rationale=analysis.rationale,
            explanation=explanation,
            action=action,
            timestamp=datetime.utcnow()
        )
        
        # Save to database
        save_audit_record(audit_record)
        
        # Send to action orchestrator
        await send_to_action_orchestrator(audit_record)
        
        logger.info(
            "risk_analysis_processed",
            transaction_id=analysis.transaction_id,
            action=action
        )
        
        return audit_record
        
    except Exception as e:
        logger.error(
            "risk_analysis_processing_failed",
            transaction_id=analysis.transaction_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Processing failed")

@app.get("/audit/{transaction_id}", response_model=AuditRecord)
async def get_audit_record(transaction_id: str):
    """Get audit record for a transaction"""
    db_path = DATABASE_URL.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, transaction_id, risk_score, rationale, explanation, action, timestamp
            FROM audit_records WHERE transaction_id = ?
        """, (transaction_id,))
        
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Audit record not found")
        
        return AuditRecord(
            id=row[0],
            transaction_id=row[1],
            risk_score=row[2],
            rationale=row[3],
            explanation=row[4],
            action=row[5],
            timestamp=datetime.fromisoformat(row[6])
        )
        
    finally:
        conn.close()

@app.get("/audit", response_model=List[AuditRecord])
async def get_recent_audit_records(limit: int = 50):
    """Get recent audit records"""
    db_path = DATABASE_URL.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, transaction_id, risk_score, rationale, explanation, action, timestamp
            FROM audit_records ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        return [
            AuditRecord(
                id=row[0],
                transaction_id=row[1],
                risk_score=row[2],
                rationale=row[3],
                explanation=row[4],
                action=row[5],
                timestamp=datetime.fromisoformat(row[6])
            )
            for row in rows
        ]
        
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn
    logger.info("starting_explain_agent", port=PORT, database_url=DATABASE_URL)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
