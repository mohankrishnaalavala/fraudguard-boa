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
MCP_GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://mcp-gateway.fraudguard.svc.cluster.local:8080")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))  # seconds

# Bank of Anthos service endpoints
BOA_USERSERVICE_URL = os.getenv("BOA_USERSERVICE_URL", "http://userservice.boa.svc.cluster.local:8080")
BOA_HISTORY_URL = os.getenv("BOA_HISTORY_URL", "http://transactionhistory.boa.svc.cluster.local:8080")

# Bank of Anthos credentials (inject via K8s Secret; do not hardcode secrets)
BOA_USERNAME = os.getenv("BOA_USERNAME", "")
# Vertex Indexer configuration (optional)
USE_VERTEX_INDEXER = os.getenv("USE_VERTEX_INDEXER", "false").lower() == "true"
GEMINI_PROJECT_ID = os.getenv("GEMINI_PROJECT_ID", "fraudguard-hackathon")
GEMINI_LOCATION = os.getenv("GEMINI_LOCATION", "us-central1")
VERTEX_EMBED_MODEL = os.getenv("VERTEX_EMBED_MODEL", "text-embedding-004")
VERTEX_ME_INDEX_RESOURCE = os.getenv("VERTEX_ME_INDEX_RESOURCE", "")  # projects/.../locations/.../indexes/...

BOA_PASSWORD = os.getenv("BOA_PASSWORD", "")

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

def _decode_jwt_noverify(token: str) -> Dict:
    """Decode a JWT payload without verifying signature (base64url)."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return {}
        import base64, json
        def b64url_decode(seg: str) -> bytes:
            padding = '=' * (-len(seg) % 4)
            return base64.urlsafe_b64decode(seg + padding)
        payload_bytes = b64url_decode(parts[1])
        return json.loads(payload_bytes.decode('utf-8'))
    except Exception:
        return {}

async def get_boa_transactions() -> List[Dict]:
    """
    Fetch recent transactions from Bank of Anthos using authenticated API calls.
    Steps:
      1) Login to userservice to obtain a JWT
      2) Extract account id (acct) from JWT payload
      3) Call transactionhistory /transactions/{acct} with Authorization: Bearer <token>
      4) Normalize BoA transaction objects to FraudGuard format
    """
    try:
        if not BOA_USERNAME or not BOA_PASSWORD:
            logger.error("boa_credentials_missing", event="auth_setup", severity="ERROR")
            return []

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1) Login to get JWT
            login_url = f"{BOA_USERSERVICE_URL}/login"
            params = {"username": BOA_USERNAME, "password": BOA_PASSWORD}
            login_resp = await client.get(login_url, params=params)
            if login_resp.status_code != 200:
                logger.error("boa_login_failed", status_code=login_resp.status_code, body=login_resp.text)
                return []
            token = login_resp.json().get("token")
            if not token:
                logger.error("boa_login_no_token")
                return []

            # 2) Extract account id from JWT (no verify; used only to route the read)
            claims = _decode_jwt_noverify(token)
            account_id = claims.get("acct")
            if not account_id:
                logger.error("boa_token_missing_acct_claim")
                return []

            # 3) Fetch transactions for this account
            hist_url = f"{BOA_HISTORY_URL}/transactions/{account_id}"
            headers = {"Authorization": f"Bearer {token}"}
            hist_resp = await client.get(hist_url, headers=headers)
            if hist_resp.status_code != 200:
                logger.error("boa_history_fetch_failed", status_code=hist_resp.status_code, body=hist_resp.text)
                return []

            raw_txns = hist_resp.json()  # list of Transaction objects

            # 4) Normalize
            norm: List[Dict] = []
            for t in raw_txns or []:
                try:
                    txn_id = str(t.get("transactionId"))
                    from_acct = t.get("fromAccountNum")
                    to_acct = t.get("toAccountNum")
                    amount_cents = t.get("amount", 0) or 0
                    # Determine sign relative to current account
                    signed_amount_cents = -amount_cents if account_id == from_acct else amount_cents
                    amount_dollars = round((signed_amount_cents or 0) / 100.0, 2)

                    ts = t.get("timestamp")
                    # Convert numeric epoch millis to ISO 8601 if needed
                    if isinstance(ts, (int, float)):
                        iso_ts = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()
                    else:
                        iso_ts = str(ts)

                    norm.append({
                        "transactionId": txn_id,
                        "accountId": str(account_id),
                        "fromAccountId": str(from_acct) if from_acct is not None else None,
                        "recipientAccountId": str(to_acct) if to_acct is not None else None,
                        "amount": amount_dollars,
                        "description": "BoA Transaction",
                        "timestamp": iso_ts,
                        "type": "debit" if amount_dollars < 0 else "credit",
                    })
                except Exception as ie:
                    logger.warning("normalize_txn_failed", error=str(ie), raw=t)
            return norm

    except Exception as e:
        logger.error("failed_to_fetch_boa_transactions", error=str(e))
        return []

# === Vertex Indexer helpers ===
async def _embed_text(text: str) -> Optional[list[float]]:
    """Get embedding vector using Vertex Text Embeddings; never raise."""
    if not USE_VERTEX_INDEXER:
        return None
    try:
        import anyio
        def _sync_embed() -> Optional[list[float]]:
            from vertexai import init
            try:
                from vertexai.language_models import TextEmbeddingModel
            except Exception:
                from vertexai.preview.language_models import TextEmbeddingModel  # type: ignore
            init(project=GEMINI_PROJECT_ID, location=GEMINI_LOCATION)
            model = TextEmbeddingModel.from_pretrained(VERTEX_EMBED_MODEL)
            res = model.get_embeddings([text])
            vec = res[0].values if res else []
            return list(vec) if vec else None
        return await anyio.to_thread.run_sync(_sync_embed)
    except Exception as e:
        logger.info("embed_failed", error=str(e))
        return None


def _build_embedding_text_from_boa_tx(tx: Dict) -> str:
    acct = str(tx.get("accountId", ""))
    label = "unknown"
    try:
        date_only = str(tx.get("timestamp", "")).split("T")[0]
    except Exception:
        date_only = ""
    tx_type = str(tx.get("type", "unknown"))
    try:
        amt = abs(float(tx.get("amount", 0) or 0))
    except Exception:
        amt = 0.0
    return f"account:{acct} label:{label} date:{date_only} type:{tx_type} amount:{amt:.2f}"


async def _upsert_to_index(tx: Dict, vector: list[float]) -> bool:
    if not (USE_VERTEX_INDEXER and VERTEX_ME_INDEX_RESOURCE and vector):
        return False
    try:
        import anyio
        def _sync_upsert() -> bool:
            from google.cloud import aiplatform_v1 as gapic
            from google.cloud.aiplatform_v1.types import index as index_types
            client = gapic.IndexServiceClient(client_options={"api_endpoint": f"{GEMINI_LOCATION}-aiplatform.googleapis.com"})
            dp = index_types.IndexDatapoint(
                datapoint_id=str(tx.get("transactionId") or tx.get("transaction_id") or ""),
                feature_vector=vector,
            )
            req = gapic.UpsertDatapointsRequest(index=VERTEX_ME_INDEX_RESOURCE, datapoints=[dp])
            client.upsert_datapoints(request=req)
            return True
        ok = await anyio.to_thread.run_sync(_sync_upsert)
        if ok:
            logger.info("vector_upsert_success", transaction_id=str(tx.get("transactionId")))
        return ok
    except Exception as e:
        logger.info("vector_upsert_failed", error=str(e))
        return False


async def forward_to_fraudguard(transaction: Dict) -> bool:
    """Forward transaction to FraudGuard for AI analysis and upsert to Vertex index (optional)."""
    transaction_id = transaction.get("transactionId", f"boa_{int(time.time())}")

    try:
        merchant_value = (
            f"acct:{transaction.get('recipientAccountId')}"
            if transaction.get('recipientAccountId') else transaction.get("description", "BoA")
        )
        inferred_type = transaction.get("type")
        if not inferred_type:
            acct = transaction.get("accountId")
            recip = transaction.get("recipientAccountId")
            inferred_type = "debit" if recip and recip != acct else "credit"

        fraudguard_transaction = {
            "transaction_id": transaction_id,
            "amount": abs(float(transaction.get("amount", 0) or 0)),
            "merchant": merchant_value,
            "user_id": transaction.get("accountId", "unknown_user"),
            "timestamp": transaction.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "type": inferred_type,
            "source": "bank_of_anthos",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{MCP_GATEWAY_URL}/api/transactions",
                json=fraudguard_transaction,
                headers={"Content-Type": "application/json"},
            )
        ok = resp.status_code in (200, 201, 202)
        logger.info("mcp_forward_result", transaction_id=transaction_id, status_code=resp.status_code, ok=ok)

        if ok and USE_VERTEX_INDEXER:
            try:
                text = _build_embedding_text_from_boa_tx(transaction)
                vec = await _embed_text(text)
                if vec:
                    await _upsert_to_index(transaction, vec)
            except Exception as ix:
                logger.info("indexer_skip_error", error=str(ix))

        return ok

    except httpx.TimeoutException as e:
        logger.error("mcp_gateway_timeout", transaction_id=transaction_id, url=f"{MCP_GATEWAY_URL}/api/transactions", timeout=15.0, error=str(e))
        return False
    except httpx.HTTPStatusError as e:
        logger.error("mcp_gateway_http_error", transaction_id=transaction_id, status_code=e.response.status_code, response_text=e.response.text, url=f"{MCP_GATEWAY_URL}/api/transactions", error=str(e))
        return False
    except Exception as e:
        logger.error("error_forwarding_transaction", transaction_id=transaction_id, error_type=type(e).__name__, error=str(e), url=f"{MCP_GATEWAY_URL}/api/transactions")
        return False
def _build_embedding_text_from_boa_tx(tx: Dict) -> str:
    # Allowed fields only: account_id(label optional), date, type, amount
    acct = str(tx.get("accountId", ""))
    # label may be unavailable; use "unknown"
    label = "unknown"
    try:
        date_only = str(tx.get("timestamp", "")).split("T")[0]
    except Exception:
        date_only = ""
    tx_type = str(tx.get("type", "unknown"))
    try:
        amt = abs(float(tx.get("amount", 0) or 0))
    except Exception:
        amt = 0.0
    return f"account:{acct} label:{label} date:{date_only} type:{tx_type} amount:{amt:.2f}"


async def _upsert_to_index(tx: Dict, vector: list[float]) -> bool:
    if not (USE_VERTEX_INDEXER and VERTEX_ME_INDEX_RESOURCE and vector):
        return False
    try:
        import anyio
        def _sync_upsert() -> bool:
            from google.cloud import aiplatform_v1 as gapic
            from google.cloud.aiplatform_v1.types import index as index_types
            client = gapic.IndexServiceClient(client_options={"api_endpoint": f"{GEMINI_LOCATION}-aiplatform.googleapis.com"})
            dp = index_types.IndexDatapoint(
                datapoint_id=str(tx.get("transactionId") or tx.get("transaction_id") or ""),
                feature_vector=vector,
            )
            req = gapic.UpsertDatapointsRequest(index=VERTEX_ME_INDEX_RESOURCE, datapoints=[dp])
            client.upsert_datapoints(request=req)
            return True
        ok = await anyio.to_thread.run_sync(_sync_upsert)
        if ok:
            logger.info("vector_upsert_success", transaction_id=str(tx.get("transactionId")))
        return ok
    except Exception as e:
        logger.info("vector_upsert_failed", error=str(e))
        return False


    except httpx.TimeoutException as e:
        logger.error("mcp_gateway_timeout",
                    transaction_id=transaction_id,
                    url=f"{MCP_GATEWAY_URL}/api/transactions",
                    timeout=15.0,
                    error=str(e))
        return False
    except httpx.HTTPStatusError as e:
        logger.error("mcp_gateway_http_error",
                    transaction_id=transaction_id,
                    status_code=e.response.status_code,
                    response_text=e.response.text,
                    url=f"{MCP_GATEWAY_URL}/api/transactions",
                    error=str(e))
        return False
    except Exception as e:
        logger.error("error_forwarding_transaction",
                    transaction_id=transaction_id,
                    error_type=type(e).__name__,
                    error=str(e),
                    url=f"{MCP_GATEWAY_URL}/api/transactions")
        return False

async def monitor_boa_transactions():
    """Main monitoring loop"""
    logger.info("starting_boa_transaction_monitoring",
               poll_interval=POLL_INTERVAL,
               boa_history_url=BOA_HISTORY_URL,
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
        "boa_history_url": BOA_HISTORY_URL,
        "mcp_gateway_url": MCP_GATEWAY_URL,
        "last_poll": getattr(health_check, 'last_poll', None)
    }

@app.get("/transactions/{account_id}")
async def get_account_transactions(account_id: str, limit: int = 50):
    """Get transaction history for a specific account from Bank of Anthos"""
    try:
        # Fetch all BoA transactions
        all_transactions = await get_boa_transactions()

        # Filter transactions for the specific account
        account_transactions = []
        for tx in all_transactions:
            # Check if this transaction involves the requested account
            if (tx.get("accountId") == account_id or
                tx.get("fromAccountId") == account_id or
                tx.get("recipientAccountId") == account_id):
                account_transactions.append(tx)

        # Sort by timestamp (newest first) and limit results
        account_transactions.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        limited_transactions = account_transactions[:limit]

        logger.info("account_transactions_retrieved",
                   account_id=account_id,
                   total_found=len(account_transactions),
                   returned=len(limited_transactions))

        return limited_transactions

    except Exception as e:
        logger.error("get_account_transactions_failed", account_id=account_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

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
