"""
Transaction Watcher Service - Polls for new transactions and triggers risk analysis
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Set

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
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
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
RISK_SCORER_URL = os.getenv("RISK_SCORER_URL", "http://risk-scorer.fraudguard.svc.cluster.local:8080")

# Set log level
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL))

app = FastAPI(
    title="Transaction Watcher",
    description="Polls for new transactions and triggers risk analysis",
    version="0.1.0"
)

# Track processed transactions to avoid duplicates
processed_transactions: Set[str] = set()

class WatcherStatus(BaseModel):
    """Watcher status model"""
    status: str
    last_poll: datetime
    processed_count: int
    poll_interval_seconds: int

# Global status tracking
watcher_status = {
    "last_poll": datetime.utcnow(),
    "processed_count": 0,
    "running": False
}

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "service": "txn-watcher", 
        "timestamp": datetime.utcnow(),
        "watcher_running": watcher_status["running"]
    }

@app.get("/status", response_model=WatcherStatus)
async def get_status():
    """Get watcher status"""
    return WatcherStatus(
        status="running" if watcher_status["running"] else "stopped",
        last_poll=watcher_status["last_poll"],
        processed_count=watcher_status["processed_count"],
        poll_interval_seconds=POLL_INTERVAL_SECONDS
    )

async def fetch_recent_transactions():
    """Fetch recent transactions from MCP Gateway"""
    try:
        # Demo: poll a few sample accounts
        sample_accounts = ["acc_001", "acc_002", "acc_003"]
        all_transactions = []
        
        async with httpx.AsyncClient() as client:
            for account_id in sample_accounts:
                try:
                    response = await client.get(
                        f"{MCP_GATEWAY_URL}/accounts/{account_id}/transactions",
                        params={"limit": 5},
                        timeout=10.0
                    )
                    response.raise_for_status()
                    transactions = response.json()
                    all_transactions.extend(transactions)
                    
                    logger.info(
                        "transactions_fetched",
                        account_id=account_id,
                        count=len(transactions)
                    )
                    
                except httpx.HTTPError as e:
                    logger.error(
                        "transaction_fetch_failed",
                        account_id=account_id,
                        error=str(e)
                    )
        
        return all_transactions
        
    except Exception as e:
        logger.error("fetch_transactions_error", error=str(e))
        return []

async def send_for_risk_analysis(transaction):
    """Send transaction to risk scorer"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{RISK_SCORER_URL}/analyze",
                json=transaction,
                timeout=30.0
            )
            response.raise_for_status()
            
            logger.info(
                "transaction_sent_for_analysis",
                transaction_id=transaction["transaction_id"]
            )
            
    except httpx.HTTPError as e:
        logger.error(
            "risk_analysis_failed",
            transaction_id=transaction["transaction_id"],
            error=str(e)
        )

async def poll_transactions():
    """Main polling loop"""
    logger.info("transaction_watcher_started", poll_interval=POLL_INTERVAL_SECONDS)
    watcher_status["running"] = True
    
    while True:
        try:
            watcher_status["last_poll"] = datetime.utcnow()
            
            # Fetch recent transactions
            transactions = await fetch_recent_transactions()
            
            # Process new transactions
            new_transactions = []
            for txn in transactions:
                txn_id = txn["transaction_id"]
                if txn_id not in processed_transactions:
                    processed_transactions.add(txn_id)
                    new_transactions.append(txn)
            
            logger.info(
                "poll_completed",
                total_transactions=len(transactions),
                new_transactions=len(new_transactions)
            )
            
            # Send new transactions for risk analysis
            for txn in new_transactions:
                await send_for_risk_analysis(txn)
                watcher_status["processed_count"] += 1
            
            # Clean up old processed transaction IDs to prevent memory growth
            if len(processed_transactions) > 10000:
                # Keep only the most recent 5000
                processed_transactions.clear()
                logger.info("processed_transactions_cleared")
            
        except Exception as e:
            logger.error("poll_error", error=str(e))
        
        # Wait for next poll
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

@app.on_event("startup")
async def startup_event():
    """Start the transaction watcher on startup"""
    asyncio.create_task(poll_transactions())

if __name__ == "__main__":
    import uvicorn
    logger.info("starting_txn_watcher", port=PORT, mcp_gateway_url=MCP_GATEWAY_URL)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
