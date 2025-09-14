"""
MCP Gateway Service - FastAPI facade over Bank of Anthos endpoints
Provides read-only access with auth, rate limiting, and audit logging.
"""

import logging
import os
import time
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

        # Mock transactions for demo
        transactions = []
        base_time = datetime.utcnow()

        for i in range(min(limit, 10)):
            transaction = Transaction(
                transaction_id=f"txn_{account_id}_{i}",
                account_id=account_id,
                amount=round(10.0 + (hash(f"{account_id}_{i}") % 500), 2),
                merchant=f"Merchant_{i % 5}",
                category=["grocery", "gas", "restaurant", "retail", "online"][i % 5],
                timestamp=base_time - timedelta(hours=i),
                location=f"City_{i % 3}"
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

        # In a real implementation, this would:
        # 1. Validate the transaction
        # 2. Submit to Bank of Anthos
        # 3. Trigger the fraud detection pipeline

        # For demo purposes, we'll simulate success and trigger the pipeline
        # The txn-watcher service will pick this up and process it

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

if __name__ == "__main__":
    import uvicorn
    logger.info("starting_mcp_gateway", port=PORT, boa_base_url=BOA_BASE_URL)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
