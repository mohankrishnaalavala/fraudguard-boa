#!/usr/bin/env python3
"""
Bank of Anthos Transaction Monitor
Monitors Bank of Anthos transactions and forwards them to FraudGuard for AI analysis
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx
import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

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

app = FastAPI(
    title="Bank of Anthos Monitor",
    description="Monitors Bank of Anthos transactions and forwards to FraudGuard",
    version="1.0.0"
)

# Configuration
BOA_LEDGER_URL = os.getenv("BOA_LEDGER_URL", "http://ledgerwriter.boa.svc.cluster.local:8080")
BOA_ACCOUNTS_URL = os.getenv("BOA_ACCOUNTS_URL", "http://accounts-db.boa.svc.cluster.local:5432")
MCP_GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://mcp-gateway.fraudguard.svc.cluster.local:8080")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))  # seconds

# In-memory tracking of processed transactions
processed_transactions = set()

class Transaction(BaseModel):
    transaction_id: str
    account_id: str
    amount: float
    merchant: str
    timestamp: str
    transaction_type: str = "debit"

class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: str
    monitoring_status: str
    last_poll: Optional[str] = None

@app.get("/healthz", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        service="boa-monitor",
        timestamp=datetime.now(timezone.utc).isoformat(),
        monitoring_status="active",
        last_poll=getattr(health_check, 'last_poll', None)
    )

async def get_boa_transactions() -> List[Dict]:
    """
    Fetch recent transactions from Bank of Anthos
    This is a simplified implementation - in reality, you'd integrate with BoA's actual APIs
    """
    try:
        # For demo purposes, we'll simulate fetching transactions
        # In a real implementation, this would query the BoA ledger database
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try to get transactions from BoA ledger service
            try:
                response = await client.get(f"{BOA_LEDGER_URL}/transactions")
                if response.status_code == 200:
                    return response.json().get("transactions", [])
            except Exception as e:
                logger.warning("boa_ledger_unavailable", error=str(e))
        
        # Fallback: Generate sample transactions for demo
        current_time = datetime.now(timezone.utc)
        sample_transactions = [
            {
                "transactionId": f"boa_{int(current_time.timestamp())}_{i}",
                "accountId": f"user_{1000 + i}",
                "amount": amount,
                "description": merchant,
                "timestamp": current_time.isoformat(),
                "type": "debit" if amount < 0 else "credit"
            }
            for i, (amount, merchant) in enumerate([
                (-150.00, "ATM Withdrawal"),
                (-45.99, "Grocery Store"),
                (-2500.00, "Electronics Purchase"),
                (-8.50, "Coffee Shop"),
                (1200.00, "Salary Deposit")
            ])
        ]
        
        return sample_transactions
        
    except Exception as e:
        logger.error("failed_to_fetch_boa_transactions", error=str(e))
        return []

async def forward_to_fraudguard(transaction: Dict) -> bool:
    """Forward transaction to FraudGuard for AI analysis"""
    try:
        # Convert BoA transaction format to FraudGuard format
        fraudguard_transaction = {
            "transaction_id": transaction.get("transactionId", f"boa_{int(time.time())}"),
            "amount": abs(float(transaction.get("amount", 0))),  # Use absolute value
            "merchant": transaction.get("description", "Unknown Merchant"),
            "user_id": transaction.get("accountId", "unknown_user"),
            "timestamp": transaction.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "source": "bank_of_anthos"
        }
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{MCP_GATEWAY_URL}/api/transactions",
                json=fraudguard_transaction,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in [200, 201, 202]:
                logger.info("transaction_forwarded_to_fraudguard",
                           transaction_id=fraudguard_transaction["transaction_id"],
                           amount=fraudguard_transaction["amount"],
                           merchant=fraudguard_transaction["merchant"])
                return True
            else:
                logger.warning("failed_to_forward_transaction",
                              transaction_id=fraudguard_transaction["transaction_id"],
                              status_code=response.status_code,
                              response=response.text)
                return False
                
    except Exception as e:
        logger.error("error_forwarding_transaction",
                    transaction_id=transaction.get("transactionId"),
                    error=str(e))
        return False

async def monitor_boa_transactions():
    """Main monitoring loop"""
    logger.info("starting_boa_transaction_monitoring",
               poll_interval=POLL_INTERVAL,
               boa_ledger_url=BOA_LEDGER_URL,
               mcp_gateway_url=MCP_GATEWAY_URL)
    
    while True:
        try:
            # Fetch recent transactions from BoA
            transactions = await get_boa_transactions()
            
            new_transactions = 0
            forwarded_transactions = 0
            
            for transaction in transactions:
                transaction_id = transaction.get("transactionId")
                
                # Skip if we've already processed this transaction
                if transaction_id in processed_transactions:
                    continue
                
                new_transactions += 1
                
                # Forward to FraudGuard
                if await forward_to_fraudguard(transaction):
                    forwarded_transactions += 1
                    processed_transactions.add(transaction_id)
                
                # Limit memory usage - keep only recent transaction IDs
                if len(processed_transactions) > 1000:
                    # Remove oldest 200 entries
                    old_transactions = list(processed_transactions)[:200]
                    for old_txn in old_transactions:
                        processed_transactions.discard(old_txn)
            
            if new_transactions > 0:
                logger.info("monitoring_cycle_completed",
                           new_transactions=new_transactions,
                           forwarded_transactions=forwarded_transactions,
                           total_processed=len(processed_transactions))
            
            # Update health check timestamp
            health_check.last_poll = datetime.now(timezone.utc).isoformat()
            
        except Exception as e:
            logger.error("monitoring_cycle_failed", error=str(e))
        
        # Wait before next poll
        await asyncio.sleep(POLL_INTERVAL)

@app.on_event("startup")
async def startup_event():
    """Start the monitoring task when the app starts"""
    logger.info("boa_monitor_starting")
    
    # Start monitoring in background
    asyncio.create_task(monitor_boa_transactions())

@app.get("/status")
async def get_status():
    """Get monitoring status"""
    return {
        "service": "boa-monitor",
        "status": "running",
        "processed_transactions": len(processed_transactions),
        "poll_interval": POLL_INTERVAL,
        "boa_ledger_url": BOA_LEDGER_URL,
        "mcp_gateway_url": MCP_GATEWAY_URL,
        "last_poll": getattr(health_check, 'last_poll', None)
    }

@app.post("/manual-sync")
async def manual_sync():
    """Manually trigger a sync cycle"""
    try:
        transactions = await get_boa_transactions()
        forwarded = 0
        
        for transaction in transactions:
            if await forward_to_fraudguard(transaction):
                forwarded += 1
        
        return {
            "status": "success",
            "transactions_found": len(transactions),
            "transactions_forwarded": forwarded
        }
    except Exception as e:
        logger.error("manual_sync_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
