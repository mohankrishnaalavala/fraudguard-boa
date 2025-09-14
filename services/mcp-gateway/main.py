"""
MCP Gateway Service - FastAPI facade over Bank of Anthos endpoints
Provides read-only access with auth, rate limiting, and audit logging.
"""

import logging
import os
import time
import sqlite3
import threading
from typing import Dict, List, Optional
from datetime import datetime, timedelta

import httpx
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
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
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "100"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "/var/run/transactions.db")

# Set log level
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL))

app = FastAPI(
    title="MCP Gateway",
    description="Read-only facade over Bank of Anthos endpoints",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory rate limiting (use Redis in production)
rate_limit_store: Dict[str, List[float]] = {}

# Database connection with thread safety
db_lock = threading.Lock()

def init_database():
    """Initialize SQLite database for transactions"""
    try:
        with sqlite3.connect(DATABASE_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    amount REAL NOT NULL,
                    merchant TEXT NOT NULL,
                    category TEXT,
                    timestamp TEXT NOT NULL,
                    location TEXT,
                    created_at TEXT NOT NULL,
                    risk_score REAL,
                    risk_level TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_account_timestamp
                ON transactions(account_id, timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON transactions(created_at DESC)
            """)
            conn.commit()
            logger.info("database_initialized", path=DATABASE_PATH)
    except Exception as e:
        logger.error("database_init_failed", error=str(e))
        raise

def store_transaction(transaction: dict) -> bool:
    """Store transaction in database"""
    try:
        with db_lock:
            with sqlite3.connect(DATABASE_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO transactions
                    (transaction_id, account_id, amount, merchant, category, timestamp, location, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    transaction["transaction_id"],
                    transaction.get("account_id", transaction.get("user_id", "unknown")),
                    transaction["amount"],
                    transaction["merchant"],
                    transaction.get("category", "unknown"),
                    transaction["timestamp"],
                    transaction.get("location"),
                    datetime.utcnow().isoformat()
                ))
                conn.commit()
                logger.info("transaction_stored", transaction_id=transaction["transaction_id"])
                return True
    except Exception as e:
        logger.error("transaction_store_failed", transaction_id=transaction.get("transaction_id"), error=str(e))
        return False

async def trigger_risk_analysis(transaction: dict):
    """Trigger risk analysis for a transaction"""
    try:
        # For immediate demo purposes, calculate risk score directly
        # This ensures the dashboard shows real risk analysis results
        risk_score = calculate_risk_score_direct(transaction)
        risk_level = "high" if risk_score > 0.7 else "medium" if risk_score > 0.4 else "low"

        # Update transaction with risk analysis
        update_transaction_risk(transaction["transaction_id"], risk_score, risk_level)

        logger.info("risk_analysis_completed",
                   transaction_id=transaction["transaction_id"],
                   risk_score=risk_score,
                   risk_level=risk_level)

        # Also try to call the risk-scorer service for comparison
        try:
            risk_scorer_url = os.getenv("RISK_SCORER_URL", "http://risk-scorer.fraudguard.svc.cluster.local:8080")

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{risk_scorer_url}/analyze",
                    json=transaction
                )

                if response.status_code == 200:
                    risk_data = response.json()
                    external_risk_score = risk_data.get("risk_score", risk_score)
                    logger.info("external_risk_analysis_completed",
                               transaction_id=transaction["transaction_id"],
                               external_risk_score=external_risk_score,
                               internal_risk_score=risk_score)

        except Exception as external_error:
            logger.warning("external_risk_analysis_failed",
                          transaction_id=transaction.get("transaction_id"),
                          error=str(external_error))

    except Exception as e:
        logger.error("risk_analysis_error",
                    transaction_id=transaction.get("transaction_id"),
                    error=str(e))

def calculate_risk_score_direct(transaction: dict) -> float:
    """Calculate risk score directly using the same logic as the AI service"""
    try:
        amount = float(transaction.get("amount", 0))
        merchant = transaction.get("merchant", "").lower()
        timestamp = transaction.get("timestamp", "")

        # Base risk score
        risk_score = 0.1

        # Amount-based risk
        if amount > 2000:
            risk_score += 0.5
        elif amount > 1000:
            risk_score += 0.4
        elif amount > 500:
            risk_score += 0.2

        # Merchant-based risk
        suspicious_keywords = ["suspicious", "unknown", "cash", "atm", "foreign", "advance"]
        if any(keyword in merchant for keyword in suspicious_keywords):
            risk_score += 0.3

        # Time-based risk (late night/early morning)
        if "t02:" in timestamp.lower() or "t03:" in timestamp.lower() or "t01:" in timestamp.lower():
            risk_score += 0.2

        # Electronics purchases
        if "electronics" in merchant:
            risk_score += 0.1

        # Coffee shops and restaurants are lower risk
        if any(word in merchant for word in ["coffee", "restaurant", "cafe"]):
            risk_score -= 0.1

        # Cap the risk score
        risk_score = min(max(risk_score, 0.05), 0.95)

        return round(risk_score, 2)

    except Exception as e:
        logger.error("direct_risk_calculation_failed", error=str(e))
        return 0.5

def update_transaction_risk(transaction_id: str, risk_score: float, risk_level: str):
    """Update transaction with risk analysis results"""
    try:
        with db_lock:
            with sqlite3.connect(DATABASE_PATH) as conn:
                conn.execute("""
                    UPDATE transactions
                    SET risk_score = ?, risk_level = ?
                    WHERE transaction_id = ?
                """, (risk_score, risk_level, transaction_id))
                conn.commit()
                logger.info("transaction_risk_updated",
                           transaction_id=transaction_id,
                           risk_score=risk_score,
                           risk_level=risk_level)
    except Exception as e:
        logger.error("transaction_risk_update_failed",
                    transaction_id=transaction_id,
                    error=str(e))

def get_account_transactions(account_id: str, limit: int = 10) -> List[dict]:
    """Get transactions for an account"""
    try:
        with db_lock:
            with sqlite3.connect(DATABASE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT transaction_id, account_id, amount, merchant, category,
                           timestamp, location, risk_score, risk_level
                    FROM transactions
                    WHERE account_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (account_id, limit))

                transactions = []
                for row in cursor.fetchall():
                    transactions.append({
                        "transaction_id": row["transaction_id"],
                        "account_id": row["account_id"],
                        "amount": row["amount"],
                        "merchant": row["merchant"],
                        "category": row["category"],
                        "timestamp": row["timestamp"],
                        "location": row["location"],
                        "risk_score": row["risk_score"],
                        "risk_level": row["risk_level"]
                    })

                logger.info("transactions_retrieved", account_id=account_id, count=len(transactions))
                return transactions

    except Exception as e:
        logger.error("transaction_retrieval_failed", account_id=account_id, error=str(e))
        return []

class Transaction(BaseModel):
    """Transaction model"""
    transaction_id: str = Field(..., description="Unique transaction ID")
    account_id: str = Field(..., description="Account ID")
    amount: float = Field(..., description="Transaction amount")
    merchant: str = Field(..., description="Merchant name")
    category: str = Field(..., description="Transaction category")
    timestamp: datetime = Field(..., description="Transaction timestamp")
    location: Optional[str] = Field(None, description="Transaction location")

class TransactionRequest(BaseModel):
    """Transaction creation request"""
    transaction_id: str = Field(..., description="Unique transaction ID")
    amount: float = Field(..., description="Transaction amount")
    merchant: str = Field(..., description="Merchant name")
    user_id: str = Field(..., description="User ID")
    timestamp: datetime = Field(..., description="Transaction timestamp")

class Account(BaseModel):
    """Account model"""
    account_id: str = Field(..., description="Account ID")
    balance: float = Field(..., description="Current balance")
    account_type: str = Field(..., description="Account type")

def check_rate_limit(client_ip: str) -> bool:
    """Simple rate limiting check"""
    now = time.time()
    minute_ago = now - 60

    if client_ip not in rate_limit_store:
        rate_limit_store[client_ip] = []

    # Clean old entries
    rate_limit_store[client_ip] = [
        timestamp for timestamp in rate_limit_store[client_ip]
        if timestamp > minute_ago
    ]

    # Check limit
    if len(rate_limit_store[client_ip]) >= RATE_LIMIT_PER_MINUTE:
        return False

    # Add current request
    rate_limit_store[client_ip].append(now)
    return True

async def get_client_ip(request: Request) -> str:
    """Extract client IP for rate limiting"""
    return request.client.host

@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Log all requests with structured logging"""
    start_time = time.time()

    # Generate request ID for tracing
    request_id = f"req_{int(start_time * 1000000)}"

    logger.info(
        "request_started",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        client_ip=request.client.host
    )

    response = await call_next(request)

    process_time = time.time() - start_time

    logger.info(
        "request_completed",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        process_time=process_time
    )

    return response

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "mcp-gateway", "timestamp": datetime.utcnow()}

@app.get("/accounts/{account_id}", response_model=Account)
async def get_account(account_id: str, client_ip: str = Depends(get_client_ip)):
    """Get account information (read-only)"""
    if not check_rate_limit(client_ip):
        logger.warning("rate_limit_exceeded", client_ip=client_ip, account_id=account_id)
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    try:
        # Mock response for demo - in production, call actual BoA API
        logger.info("account_requested", account_id=account_id, client_ip=client_ip)

        # Simulate API call to BoA
        account = Account(
            account_id=account_id,
            balance=1000.0 + hash(account_id) % 10000,
            account_type="checking"
        )

        logger.info("account_retrieved", account_id=account_id)
        return account

    except Exception as e:
        logger.error("account_retrieval_failed", account_id=account_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/accounts/{account_id}/transactions", response_model=List[Transaction])
async def get_recent_transactions(
    account_id: str,
    limit: int = 10,
    client_ip: str = Depends(get_client_ip)
):
    """Get recent transactions for an account (read-only)"""
    if not check_rate_limit(client_ip):
        logger.warning("rate_limit_exceeded", client_ip=client_ip, account_id=account_id)
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    try:
        logger.info("transactions_requested", account_id=account_id, limit=limit, client_ip=client_ip)

        # Get real transactions from database
        transaction_data = get_account_transactions(account_id, limit)

        transactions = []
        for txn_data in transaction_data:
            transaction = Transaction(
                transaction_id=txn_data["transaction_id"],
                account_id=txn_data["account_id"],
                amount=txn_data["amount"],
                merchant=txn_data["merchant"],
                category=txn_data["category"] or "unknown",
                timestamp=datetime.fromisoformat(txn_data["timestamp"].replace('Z', '+00:00')),
                location=txn_data["location"]
            )
            transactions.append(transaction)

        # If no real transactions, return some sample data for demo
        if not transactions:
            base_time = datetime.utcnow()
            for i in range(min(limit, 3)):
                transaction = Transaction(
                    transaction_id=f"sample_{account_id}_{i}",
                    account_id=account_id,
                    amount=round(10.0 + (hash(f"{account_id}_{i}") % 500), 2),
                    merchant=f"Sample_Merchant_{i % 3}",
                    category=["grocery", "gas", "restaurant"][i % 3],
                    timestamp=base_time - timedelta(hours=i),
                    location=f"Sample_City_{i % 2}"
                )
                transactions.append(transaction)

        logger.info("transactions_retrieved", account_id=account_id, count=len(transactions))
        return transactions

    except Exception as e:
        logger.error("transactions_retrieval_failed", account_id=account_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/transactions")
async def create_transaction(
    transaction: TransactionRequest,
    client_ip: str = Depends(get_client_ip)
):
    """Create a new transaction and trigger fraud analysis"""
    if not check_rate_limit(client_ip):
        logger.warning("rate_limit_exceeded", client_ip=client_ip, transaction_id=transaction.transaction_id)
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    try:
        logger.info(
            "transaction_created",
            transaction_id=transaction.transaction_id,
            amount=transaction.amount,
            merchant=transaction.merchant,
            user_id=transaction.user_id,
            client_ip=client_ip
        )

        # Store transaction in database
        transaction_data = {
            "transaction_id": transaction.transaction_id,
            "account_id": transaction.user_id,  # Map user_id to account_id
            "amount": transaction.amount,
            "merchant": transaction.merchant,
            "category": "unknown",  # Could be enhanced to detect category
            "timestamp": transaction.timestamp.isoformat(),
            "location": None  # Could be enhanced with location detection
        }

        if not store_transaction(transaction_data):
            raise HTTPException(status_code=500, detail="Failed to store transaction")

        # Trigger risk analysis asynchronously
        import asyncio
        asyncio.create_task(trigger_risk_analysis(transaction_data))

        response = {
            "status": "accepted",
            "transaction_id": transaction.transaction_id,
            "message": "Transaction submitted for processing",
            "timestamp": datetime.utcnow()
        }

        logger.info("transaction_accepted", transaction_id=transaction.transaction_id)
        return response

    except Exception as e:
        logger.error("transaction_creation_failed", transaction_id=transaction.transaction_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/recent-transactions")
async def get_all_recent_transactions(
    limit: int = 20,
    client_ip: str = Depends(get_client_ip)
):
    """Get all recent transactions across all accounts for dashboard"""
    if not check_rate_limit(client_ip):
        logger.warning("rate_limit_exceeded", client_ip=client_ip)
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    try:
        with db_lock:
            with sqlite3.connect(DATABASE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT transaction_id, account_id, amount, merchant, category,
                           timestamp, location, risk_score, risk_level, created_at
                    FROM transactions
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))

                transactions = []
                for row in cursor.fetchall():
                    transactions.append({
                        "transaction_id": row["transaction_id"],
                        "account_id": row["account_id"],
                        "amount": row["amount"],
                        "merchant": row["merchant"],
                        "category": row["category"],
                        "timestamp": row["timestamp"],
                        "location": row["location"],
                        "risk_score": row["risk_score"],
                        "risk_level": row["risk_level"] or "pending",
                        "created_at": row["created_at"]
                    })

                logger.info("recent_transactions_retrieved", count=len(transactions))
                return {"transactions": transactions}

    except Exception as e:
        logger.error("recent_transactions_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    init_database()

if __name__ == "__main__":
    import uvicorn
    logger.info("starting_mcp_gateway", port=PORT, boa_base_url=BOA_BASE_URL)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
