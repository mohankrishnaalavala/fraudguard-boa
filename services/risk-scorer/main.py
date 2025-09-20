"""
Risk Scorer Service - Uses Gemini to analyze transaction risk
"""

import logging
import os
import json
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
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
GEMINI_API_KEY_FILE = os.getenv("GEMINI_API_KEY_FILE", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_PROJECT_ID = os.getenv("GEMINI_PROJECT_ID", "PROJECT_ID")
GEMINI_LOCATION = os.getenv("GEMINI_LOCATION", "us-central1")
USE_VERTEX_AI = os.getenv("USE_VERTEX_AI", "true").lower() == "true"
USE_VERTEX_SDK = os.getenv("USE_VERTEX_SDK", "false").lower() == "true"
# Force GL API first (OAuth) and optionally disable Vertex usage path
PREFER_GL_API = os.getenv("PREFER_GL_API", "true").lower() == "true"
FORCE_GL_OAUTH = os.getenv("FORCE_GL_OAUTH", "true").lower() == "true"
MCP_GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://mcp-gateway.fraudguard.svc.cluster.local:8080")
EXPLAIN_AGENT_URL = os.getenv("EXPLAIN_AGENT_URL", "http://explain-agent.fraudguard.svc.cluster.local:8080")
SKIP_RAG_HISTORY = os.getenv("SKIP_RAG_HISTORY", "false").lower() == "true"
DISABLE_EXPLAIN_AGENT = os.getenv("DISABLE_EXPLAIN_AGENT", "false").lower() == "true"
# Optional: include Bank of Anthos history in RAG
RAG_INCLUDE_BOA = os.getenv("RAG_INCLUDE_BOA", "true").lower() == "true"
BOA_USERSERVICE_URL = os.getenv("BOA_USERSERVICE_URL", "http://userservice.boa.svc.cluster.local:8080")
BOA_HISTORY_URL = os.getenv("BOA_HISTORY_URL", "http://transactionhistory.boa.svc.cluster.local:8080")
BOA_USERNAME = os.getenv("BOA_USERNAME", "")
BOA_PASSWORD = os.getenv("BOA_PASSWORD", "")

# Load API key from file (Secret Manager CSI) if provided
if GEMINI_API_KEY_FILE:
    try:
        with open(GEMINI_API_KEY_FILE, "r") as f:
            GEMINI_API_KEY = f.read().strip()
            logger.info("gemini_api_key_loaded_via_csi", path=GEMINI_API_KEY_FILE)
    except Exception as e:
        logger.error("gemini_api_key_file_error", path=GEMINI_API_KEY_FILE, error=str(e))

# Set log level
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL))

app = FastAPI(
    title="Risk Scorer",
    description="Analyzes transaction risk using Gemini AI",
    version="0.1.0"
)

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    try:
        logger.info(
            "request_in",
            method=request.method,
            path=request.url.path,
            content_length=request.headers.get("content-length", "0"),
            content_type=request.headers.get("content-type", "")
        )
        response = await call_next(request)
        logger.info(
            "request_out",
            method=request.method,
            path=request.url.path,
            status=getattr(response, "status_code", None)
        )
        return response
    except Exception as e:
        logger.error("request_failed", method=request.method, path=request.url.path, error=str(e))
        raise

class Transaction(BaseModel):
    """Transaction input model"""
    transaction_id: str = Field(..., description="Unique transaction ID")
    account_id: str = Field(..., description="Account ID")
    amount: float = Field(..., description="Transaction amount")
    merchant: str = Field(..., description="Merchant name")
    category: str = Field(..., description="Transaction category")
    timestamp: datetime = Field(..., description="Transaction timestamp")
    location: Optional[str] = Field(None, description="Transaction location")
    type: Optional[str] = Field(None, description="Transaction type (debit/credit)")
    label: Optional[str] = Field(None, description="Recipient label/description")

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

# Helper: decode JWT payload without verification (base64url)
def _decode_jwt_noverify(token: str) -> dict:
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return {}
        import base64
        padding = '=' * (-len(parts[1]) % 4)
        payload_bytes = base64.urlsafe_b64decode(parts[1] + padding)
        return json.loads(payload_bytes.decode('utf-8'))
    except Exception:
        return {}


def create_risk_analysis_prompt(transaction: Transaction) -> str:
    """Create a privacy-safe prompt using only Bank of Anthos fields."""
    # Map gateway fields to BoA-aligned feature names
    label = getattr(transaction, "label", None) or transaction.merchant
    tx_type = getattr(transaction, "type", None) or "unknown"
    prompt = f"""
Analyze this transaction for fraud risk. Return a JSON response with risk_score (0.0-1.0) and rationale.

Use only these fields for analysis (no category, merchant-type, or location):
- Amount: ${transaction.amount:.2f}
- Account ID: {transaction.account_id}
- Label: {label}
- Type: {tx_type}
- Timestamp: {transaction.timestamp.isoformat()}

Consider these fraud indicators strictly from the above fields:
- Amount patterns vs past for the same label (recipient) and account
- Repeated amounts to the same label
- Temporal patterns (time-of-day, weekday/weekend), and velocity bursts

Respond ONLY with a single JSON object: {{"risk_score": number between 0 and 1, "rationale": string}}
"""
    return prompt

async def fetch_boa_history_for_account(account_id: str, limit: int = 100) -> list[dict]:
    """Fetch transaction history from Bank of Anthos for the given account.

    This function connects to the boa-monitor service to get actual Bank of Anthos
    transaction data for the specified account.
    """
    try:
        boa_monitor_url = os.getenv("BOA_MONITOR_URL", "http://boa-monitor-workload.fraudguard.svc.cluster.local:8080")

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Try to get BoA transactions for this account
            resp = await client.get(f"{boa_monitor_url}/transactions/{account_id}", params={"limit": limit})

            if resp.status_code == 200:
                boa_transactions = resp.json()
                logger.info("boa_history_fetched", account_id=account_id, count=len(boa_transactions))

                # Convert BoA format to standard format for RAG
                normalized = []
                for tx in boa_transactions:
                    try:
                        # Convert BoA transaction to standard format
                        normalized_tx = {
                            "transaction_id": tx.get("transactionId", tx.get("transaction_id")),
                            "account_id": tx.get("accountId", tx.get("account_id", account_id)),
                            "amount": abs(float(tx.get("amount", 0))),
                            "merchant": tx.get("merchant", f"acct:{tx.get('recipientAccountId', 'unknown')}"),
                            "label": tx.get("label") or tx.get("merchant") or f"acct:{tx.get('recipientAccountId', 'unknown')}",
                            "type": tx.get("type"),

                            "timestamp": tx.get("timestamp"),
                            "source": "bank_of_anthos"
                        }
                        normalized.append(normalized_tx)
                    except Exception as e:
                        logger.warning("boa_tx_normalization_failed", error=str(e), tx=tx)

                return normalized
            else:
                logger.warning("boa_history_fetch_failed", account_id=account_id, status=resp.status_code)
                return []

    except Exception as e:
        logger.warning("boa_history_error", account_id=account_id, error=str(e))
        return []

async def fetch_account_history(account_id: str, limit: int = 100) -> list[dict]:
    """Retrieve recent transactions for the account for RAG from multiple sources.
    Sources:
      - MCP Gateway (authoritative FraudGuard view)
      - Bank of Anthos (optional, when credentials and account match)
    """
    if SKIP_RAG_HISTORY:
        logger.info("history_skipped", account_id=account_id)
        return []
    combined: list[dict] = []

    # 1) MCP Gateway - Primary source for FraudGuard processed transactions
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{MCP_GATEWAY_URL}/accounts/{account_id}/transactions", params={"limit": limit})
            if resp.status_code == 200:
                mcp_data = resp.json()
                if isinstance(mcp_data, list):
                    combined.extend(mcp_data)
                elif isinstance(mcp_data, dict) and "transactions" in mcp_data:
                    combined.extend(mcp_data["transactions"])
                logger.info("mcp_history_fetched", account_id=account_id, count=len(combined))
            else:
                logger.warning("history_fetch_non200", source="mcp", status=resp.status_code)
    except Exception as e:
        logger.warning("history_fetch_failed", source="mcp", account_id=account_id, error=str(e))

    # 2) Bank of Anthos (optional) - Additional historical context
    try:
        boa_hist = await fetch_boa_history_for_account(account_id, limit=limit)
        combined.extend(boa_hist)
        logger.info("boa_history_added", account_id=account_id, boa_count=len(boa_hist), total_count=len(combined))
    except Exception as e:
        logger.info("boa_history_not_used", account_id=account_id, error=str(e))

    # Deduplicate by minimal signature (timestamp+amount+merchant)
    seen = set()
    deduped = []
    for tx in combined:
        # Dedup by timestamp+amount+label/merchant
        label = str(tx.get("label") or tx.get("merchant", ""))
        key = (str(tx.get("timestamp")), str(tx.get("amount")), label)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tx)

    logger.info("history_deduped", account_id=account_id, original_count=len(combined), final_count=len(deduped))
    return deduped[:limit]

def extract_recipient_key(transaction: dict) -> str:
    """Extract a consistent recipient key using BoA-aligned fields.

    Prefer 'label' (BoA label/description). Fallback to 'merchant'.
    If either starts with 'acct:' treat it as recipient account key.
    """
    label = str(transaction.get("label") or "").strip()
    merchant = str(transaction.get("merchant") or "").strip()

    candidate = label or merchant
    if candidate.startswith("acct:"):
        return candidate.lower()
    if candidate:
        return candidate.lower()
    return "unknown_recipient"

def summarize_history_for_rag(history: list[dict]) -> dict:
    """Summarize history with richer stats for RAG and pattern signals.
    - known recipients with counts, typical amount, last_seen
    - typical amount overall
    - common hours and weekday/weekend split
    - recent velocity windows (15m/60m)
    """
    from collections import defaultdict, Counter
    import statistics
    recipients_amounts: dict[str, list[float]] = defaultdict(list)
    recipients_last_seen: dict[str, str] = {}
    hours: list[int] = []
    weekdays: list[int] = []
    amounts: list[float] = []
    timestamps: list[datetime] = []

    for tx in history:
        # Use improved recipient extraction
        recipient_key = extract_recipient_key(tx)
        amt = float(tx.get("amount", 0))
        amounts.append(amt)
        ts = tx.get("timestamp") or ""

        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            # Normalize to timezone-aware UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            timestamps.append(dt)
            hours.append(dt.hour)
            weekdays.append(dt.weekday())
        except Exception:
            pass

        # Track recipient patterns for both account transfers and merchant transactions
        if recipient_key and recipient_key != "unknown_recipient":
            recipients_amounts[recipient_key].append(amt)
            if ts:
                recipients_last_seen[recipient_key] = str(ts)

    top_known = []
    for m, vals in recipients_amounts.items():
        try:
            typical = statistics.median(vals)
        except statistics.StatisticsError:
            typical = vals[0] if vals else 0
        top_known.append({
            "recipient": m,
            "count": len(vals),
            "typical_amount": round(typical, 2),
            "last_seen": recipients_last_seen.get(m)
        })
    top_known.sort(key=lambda x: x["count"], reverse=True)

    typical_amount = round(statistics.median(amounts), 2) if amounts else 0
    common_hours = [h for h, _ in Counter(hours).most_common(3)] if hours else []
    weekday_count = sum(1 for d in weekdays if d < 5)
    weekend_count = sum(1 for d in weekdays if d >= 5)

    # Velocity windows relative to latest timestamp if present, else now
    now_ref = max(timestamps).astimezone(timezone.utc) if timestamps else datetime.now(timezone.utc)
    # Ensure subtraction between timezone-aware datetimes in UTC
    count_last_15m = sum(1 for dt in timestamps if (now_ref - dt.astimezone(timezone.utc)).total_seconds() <= 15 * 60)
    count_last_60m = sum(1 for dt in timestamps if (now_ref - dt.astimezone(timezone.utc)).total_seconds() <= 60 * 60)

    return {
        "known_recipients": top_known[:10],
        "typical_amount": typical_amount,
        "common_hours": common_hours,
        "weekday_count": weekday_count,
        "weekend_count": weekend_count,
        "velocity": {"count_last_15m": count_last_15m, "count_last_60m": count_last_60m},
        "history_count": len(history)
    }



def analyze_pattern_signals(tx: dict, rag_summary: dict) -> dict:
    """Derive structured pattern signals (no PII) from tx + RAG summary."""
    try:
        import math
        amount = float(tx.get("amount", 0))

        # Use consistent recipient key extraction
        recipient_key = extract_recipient_key(tx)
        ts = str(tx.get("timestamp", ""))

        # recipient stats - check against known recipients using consistent key
        known_map = {k["recipient"]: k for k in rag_summary.get("known_recipients", [])}
        is_known = recipient_key in known_map
        typical_known = known_map.get(recipient_key, {}).get("typical_amount") if is_known else None
        deviation_ratio = None
        if is_known and typical_known and typical_known > 0:
            deviation_ratio = round(amount / float(typical_known), 2)
        # time signals
        common_hours = rag_summary.get("common_hours", [])
        try:
            hour = datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
        except Exception:
            hour = None
        off_hours = hour is not None and common_hours and (hour not in common_hours)
        # weekday/weekend
        weekend_bias = None
        wd = rag_summary.get("weekday_count", 0)
        we = rag_summary.get("weekend_count", 0)
        if (wd + we) > 0:
            weekend_bias = round(we / max(1, (wd + we)), 2)
        # velocity
        vel = rag_summary.get("velocity", {})
        v15 = int(vel.get("count_last_15m", 0))
        v60 = int(vel.get("count_last_60m", 0))
        signals = {
            "known_recipient": bool(is_known),
            "new_recipient": (not is_known) and bool(recipient_key) and recipient_key != "unknown_recipient",
            "recipient_key": recipient_key,  # For debugging
            "amount_deviation_from_known": deviation_ratio,
            "amount_deviation_flag": deviation_ratio is not None and deviation_ratio >= 1.5,
            "off_hours": bool(off_hours),
            "weekend_bias": weekend_bias,
            "velocity_15m": v15,
            "velocity_60m": v60,
            "velocity_flag": (v15 >= 3) or (v60 >= 5)
        }
        return signals
    except Exception:
        return {"signal_error": True}


# Local heuristic as a last-resort when AI output is unavailable/unparsable
# Mirrors gateway's simple rules but kept here to provide a useful rationale
# without leaking PII.
def heuristic_risk_from_tx(tx: dict) -> tuple[float, str]:
    try:
        amount = float(tx.get("amount", 0))
        ts = str(tx.get("timestamp", ""))
        risk = 0.1
        reasons = []
        # Amount-based risk only (no merchant/category/location assumptions)
        if amount > 2000:
            risk += 0.5; reasons.append(f"High amount ${amount}")
        elif amount > 1000:
            risk += 0.4; reasons.append(f"Large amount ${amount}")
        elif amount > 500:
            risk += 0.2; reasons.append(f"Medium amount ${amount}")
        # Temporal signal (late night)
        if any(x in ts for x in ["T01:", "T02:", "T03:"]):
            risk += 0.2; reasons.append("Late night activity")
        risk = min(max(risk, 0.05), 0.95)
        rationale = "; ".join(reasons) or "Standard transaction pattern"
        return round(risk, 2), rationale
    except Exception:
        return 0.5, "Heuristic fallback due to error"

def build_vertex_prompt(transaction: dict, rag_summary: dict, pattern_signals: dict | None = None) -> str:
    """Construct a Vertex AI prompt using only BoA fields and derived signals."""
    signals_json = json.dumps(pattern_signals or {}, default=str)

    # Normalize BoA-aligned features
    label = transaction.get("label") or transaction.get("merchant", "unknown")
    amount = float(transaction.get("amount", 0))
    tx_type = transaction.get("type", "unknown")

    # Build intelligent historical context (recipient == label)
    historical_context = ""
    if rag_summary.get("known_recipients"):
        for recip_data in rag_summary["known_recipients"]:
            if str(recip_data.get("recipient", "")).lower() == str(label).lower():
                typical_amount = float(recip_data.get("typical_amount", 0) or 0)
                count = int(recip_data.get("count", 0) or 0)
                if typical_amount > 0 and count > 0:
                    deviation_ratio = amount / typical_amount if typical_amount > 0 else 1.0
                    historical_context = (
                        f"HISTORICAL ANALYSIS: Label '{label}' has {count} prior txns with typical ${typical_amount:.2f}. "
                        f"Current ${amount:.2f} is {deviation_ratio:.1f}x typical."
                    )
                break

    if not historical_context and float(rag_summary.get("typical_amount", 0) or 0) > 0:
        account_typical = float(rag_summary["typical_amount"])
        deviation_ratio = amount / account_typical if account_typical > 0 else 1.0
        historical_context = (
            f"ACCOUNT ANALYSIS: Account typical is ${account_typical:.2f}. Current ${amount:.2f} is {deviation_ratio:.1f}x account typical."
        )

    # Provide a sanitized current transaction payload limited to allowed fields
    sanitized_current = {
        "transaction_id": transaction.get("transaction_id"),
        "account_id": transaction.get("account_id"),
        "amount": amount,
        "label": label,
        "type": tx_type,
        "timestamp": transaction.get("timestamp"),
    }

    return (
        "You are an AI fraud analyst. Analyze this Bank of Anthos transaction using historical context and patterns. "
        "Only use these fields: amount, account_id, label, type, timestamp. Do not use category, merchant type, or location. "
        "Output ONLY a single minified JSON object exactly matching this schema: "
        "{\"risk_score\": number between 0 and 1, \"rationale\": string}. "
        "No additional text, no explanations, no markdown, no code fences.\n\n"
        f"CURRENT TRANSACTION: {json.dumps(sanitized_current, default=str)}\n\n"
        f"HISTORICAL CONTEXT: {historical_context}\n\n"
        f"RAG SUMMARY: {json.dumps(rag_summary, default=str)}\n\n"
        f"PATTERN SIGNALS: {signals_json}\n\n"
        "ANALYSIS INSTRUCTIONS:\n"
        "- If the label (recipient) has history, compare current amount vs typical for that label.\n"
        "- Flag deviations >2x from the label's typical as suspicious; note repeated equal amounts.\n"
        "- Consider account-level typical when label history is insufficient.\n"
        "- Consider velocity (>=3 in 15m or >=5 in 60m) and off-hours time-of-day.\n"
        "- Provide a concise rationale referencing these specific factors only.\n"
        "- If rag_summary.history_count > 0, explicitly reference historical stats in the rationale (e.g., Known recipient X with N previous transactions averaging $Y).\n"
        "- Do not claim lack of historical data when history_count > 0; instead, use the provided context."
    )

async def call_vertex_ai(prompt: str) -> dict:
    """Call Vertex AI (HTTP or SDK) using ADC; never crash caller.
    Prefers SDK when USE_VERTEX_SDK=true, else falls back to HTTP.
    """
    # 1) Try SDK path if enabled
    if USE_VERTEX_SDK:
        try:
            import anyio
            def _sdk_invoke() -> dict:
                from vertexai import init
                from vertexai.generative_models import GenerativeModel, GenerationConfig
                init(project=GEMINI_PROJECT_ID, location=GEMINI_LOCATION)
                model = GenerativeModel(GEMINI_MODEL)
                schema = {
                    "type": "object",
                    "properties": {
                        "risk_score": {"type": "number"},
                        "rationale": {"type": "string"}
                    },
                    "required": ["risk_score", "rationale"]
                }
                resp = model.generate_content(
                    prompt,
                    generation_config=GenerationConfig(
                        temperature=0.1,
                        max_output_tokens=1024,
                        response_mime_type="application/json",
                        response_schema=schema,
                    ),
                )
                # Prefer the SDK's text if present; otherwise try to concatenate parts
                text = getattr(resp, "text", None)
                if not text:
                    pieces = []
                    try:
                        cands = getattr(resp, "candidates", []) or []
                        if cands:
                            content = getattr(cands[0], "content", None)
                            if content:
                                parts = getattr(content, "parts", []) or []
                                for p in parts:
                                    t = getattr(p, "text", None)
                                    if t:
                                        pieces.append(t)
                    except Exception:
                        pass
                    text = "".join(pieces)
                return {"_raw": text}
            data = await anyio.to_thread.run_sync(_sdk_invoke)
            text = data.get("_raw", "")
            try:
                result = json.loads(text)
            except Exception:
                import re
                m = re.search(r"\{[\s\S]*\}", text)
                result = json.loads(m.group(0)) if m else {"risk_score": 0.5, "rationale": "Unparsable AI output"}
            logger.info("vertex_ai_call_success", parsed=bool("risk_score" in result), sdk=True)
            # If SDK result is not valid JSON payload, try GL API fallback
            if not (isinstance(result, dict) and "risk_score" in result and str(result.get("rationale", "")).lower() != "unparsable ai output"):
                try:
                    gl_result = anyio.run(call_gemini_api, prompt)  # run sync fallback
                    if isinstance(gl_result, dict) and "risk_score" in gl_result:
                        return gl_result
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.error("vertex_ai_error", error=str(e), sdk=True)
            # fall through to HTTP

    # 2) HTTP path (publishers/google/models/*:generateContent)
    try:
        import anyio
        async def get_token_async() -> str:
            def _sync_get_token() -> str:
                import google.auth
                from google.auth.transport.requests import Request
                credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
                credentials.refresh(Request())
                return credentials.token
            return await anyio.to_thread.run_sync(_sync_get_token, cancellable=True)

        token = await get_token_async()
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1024,
                "response_mime_type": "application/json",
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "risk_score": {"type": "number"},
                        "rationale": {"type": "string"}
                    },
                    "required": ["risk_score", "rationale"]
                }
            }        }

        async def _invoke(url: str) -> dict:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                # Handle functionCall(args={...}) structure first
                try:
                    for p in parts:
                        if isinstance(p, dict):
                            fc = p.get("function_call") or p.get("functionCall")
                            if fc and isinstance(fc, dict):
                                args = fc.get("args")
                                if isinstance(args, dict) and "risk_score" in args and "rationale" in args:
                                    return args
                except Exception:
                    pass
                def decode_inline(part: dict) -> str:
                    try:
                        import base64
                        # GL API uses inline_data; Vertex may use inlineData
                        idata = part.get("inline_data") or part.get("inlineData")
                        if isinstance(idata, dict):
                            mt = idata.get("mime_type") or idata.get("mimeType")
                            if mt and "json" in mt.lower():
                                b64 = idata.get("data")
                                if b64:
                                    return base64.b64decode(b64).decode("utf-8", errors="ignore")
                    except Exception:
                        return ""
                    return ""
                pieces = []
                for p in parts:
                    if not isinstance(p, dict):
                        continue
                    t = p.get("text")
                    if t:
                        pieces.append(t)
                        continue
                    decoded = decode_inline(p)
                    if decoded:
                        pieces.append(decoded)
                agg = "".join(pieces)
                # Primary: parse concatenated text or decoded inline JSON
                try:
                    return json.loads(agg)
                except Exception:
                    pass
                # Secondary: search json in concatenated text
                try:
                    import re
                    m = re.search(r"\{[\s\S]*\}", agg)
                    if m:
                        return json.loads(m.group(0))
                except Exception:
                    pass
                # Tertiary: deep search in the entire response structure
                def find_json_obj(o):
                    if isinstance(o, dict):
                        if "risk_score" in o and "rationale" in o:
                            return o
                        for v in o.values():
                            r = find_json_obj(v)
                            if r is not None:
                                return r
                    elif isinstance(o, list):
                        for v in o:
                            r = find_json_obj(v)
                            if r is not None:
                                return r
                    elif isinstance(o, str):
                        try:
                            jo = json.loads(o)
                            if isinstance(jo, dict) and "risk_score" in jo and "rationale" in jo:
                                return jo
                        except Exception:
                            try:
                                m2 = re.search(r"\{[\s\S]*\}", o)
                                if m2:
                                    jo2 = json.loads(m2.group(0))
                                    if isinstance(jo2, dict) and "risk_score" in jo2 and "rationale" in jo2:
                                        return jo2
                            except Exception:
                                pass
                    return None
                found = find_json_obj(data)
                if found is not None:
                    return found
                return {"risk_score": 0.5, "rationale": "Unparsable AI output"}

        # Try v1 first, then v1beta1 on 404
        v1_url = (
            f"https://{GEMINI_LOCATION}-aiplatform.googleapis.com/v1/"
            f"projects/{GEMINI_PROJECT_ID}/locations/{GEMINI_LOCATION}/publishers/google/models/{GEMINI_MODEL}:generateContent"
        )
        try:
            result = await _invoke(v1_url)
            logger.info("vertex_ai_call_success", parsed=bool("risk_score" in result), sdk=False, api_version="v1")
            if not (isinstance(result, dict) and "risk_score" in result and str(result.get("rationale", "")).lower() != "unparsable ai output"):
                try:
                    gl_result = await call_gemini_api(prompt)
                    if isinstance(gl_result, dict) and "risk_score" in gl_result:
                        return gl_result
                except Exception:
                    pass
            return result
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                v1b_url = (
                    f"https://{GEMINI_LOCATION}-aiplatform.googleapis.com/v1beta1/"
                    f"projects/{GEMINI_PROJECT_ID}/locations/{GEMINI_LOCATION}/publishers/google/models/{GEMINI_MODEL}:generateContent"
                )
                try:
                    result = await _invoke(v1b_url)
                    logger.info("vertex_ai_call_success", parsed=bool("risk_score" in result), sdk=False, api_version="v1beta1")
                    if not (isinstance(result, dict) and "risk_score" in result and str(result.get("rationale", "")).lower() != "unparsable ai output"):
                        try:
                            gl_result = await call_gemini_api(prompt)
                            if isinstance(gl_result, dict) and "risk_score" in gl_result:
                                return gl_result
                        except Exception:
                            pass
                    return result
                except Exception as e2:
                    logger.error("vertex_ai_error", error=str(e2), sdk=False, api_version="v1beta1")
                    raise
            else:
                logger.error("vertex_ai_error", error=str(e), sdk=False, api_version="v1")
                raise
    except Exception as e:
        logger.error("vertex_ai_error", error=str(e), sdk=False)
        # Optional fallback to Gemini API if API key is present
        if GEMINI_API_KEY and GEMINI_API_KEY != "PLACEHOLDER_GEMINI_API_KEY":
            try:
                alt = await call_gemini_api(prompt)
                logger.info("ai_result_received", source="gemini_api", risk_score=float(alt.get("risk_score", 0.5)), rationale_preview=(str(alt.get("rationale", ""))[:80]))
                return alt
            except Exception as e2:
                logger.error("gemini_api_fallback_error", error=str(e2))
        return {"risk_score": 0.5, "rationale": "Vertex AI error - fallback used"}

    return {"risk_score": 0.5, "rationale": "No AI response - default applied"}

async def call_gemini_api(prompt: str) -> dict:
    """Call Gemini API (generativelanguage.googleapis.com) using OAuth (preferred) or API key.
    When FORCE_GL_OAUTH=true, skip API key path entirely.
    """
    try:
        # If neither OAuth nor API key available, use intelligent mock for demo
        if (not GEMINI_API_KEY or GEMINI_API_KEY == "PLACEHOLDER_GEMINI_API_KEY") and not FORCE_GL_OAUTH:
            logger.info("using_enhanced_mock_with_historical_analysis")

            # Enhanced intelligent mock that uses historical context from prompt
            import re

            # Extract transaction details from prompt for intelligent analysis
            amount_match = re.search(r'"amount":\s*(\d+\.?\d*)', prompt)
            amount = float(amount_match.group(1)) if amount_match else 0

            merchant_match = re.search(r'"merchant":\s*"([^"]*)"', prompt)
            merchant = merchant_match.group(1) if merchant_match else ""

            # Extract historical context from enhanced prompt
            historical_context = ""
            if "HISTORICAL ANALYSIS:" in prompt:
                hist_match = re.search(r'HISTORICAL ANALYSIS: ([^\\n]+)', prompt)
                if hist_match:
                    historical_context = hist_match.group(1)
            elif "ACCOUNT ANALYSIS:" in prompt:
                hist_match = re.search(r'ACCOUNT ANALYSIS: ([^\\n]+)', prompt)
                if hist_match:
                    historical_context = hist_match.group(1)

            # Extract pattern signals for intelligent analysis
            known_recipient = "known_recipient.*true" in prompt

            # Intelligent risk scoring based on historical patterns
            risk_score = 0.1  # Base risk
            risk_factors = []

            # Historical analysis-based scoring
            if historical_context:
                if "typical amount" in historical_context and "is" in historical_context and "x" in historical_context:
                    # Extract deviation ratio from historical context
                    ratio_match = re.search(r'(\d+\.?\d*)x', historical_context)
                    if ratio_match:
                        deviation_ratio = float(ratio_match.group(1))
                        if deviation_ratio >= 3.0:
                            risk_score += 0.5
                            risk_factors.append(f"Amount is {deviation_ratio}x higher than historical pattern")
                        elif deviation_ratio >= 2.0:
                            risk_score += 0.3
                            risk_factors.append(f"Amount is {deviation_ratio}x higher than typical")
                        elif deviation_ratio <= 0.5:
                            risk_score -= 0.1
                            risk_factors.append("Amount consistent with historical pattern")

            # Recipient analysis
            if known_recipient:
                if not risk_factors:  # No historical deviation detected
                    risk_score = max(0.05, risk_score - 0.1)
                    risk_factors.append("Known recipient with consistent transaction pattern")
            else:
                risk_score += 0.2
                risk_factors.append("New recipient - first transaction to this account")

            # Amount-based risk (fallback if no historical context)
            if not historical_context:
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

            # Generate intelligent rationale based on analysis
            if historical_context and risk_factors:
                # Use historical context for explanation
                primary_factor = risk_factors[0] if risk_factors else "Transaction analysis"
                if known_recipient:
                    if "higher than" in primary_factor:
                        rationale = f"Known recipient account with unusual transaction pattern. {primary_factor}. This deviation from typical spending behavior warrants investigation."
                    else:
                        rationale = f"Known recipient account with {primary_factor.lower()}. Transaction appears consistent with established patterns."
                else:
                    rationale = f"New recipient account. {primary_factor}. First-time transactions to new recipients require additional verification."
            elif risk_score > 0.7:
                rationale = f"HIGH RISK: {', '.join(risk_factors[:3])}"
            elif risk_score > 0.4:
                rationale = f"MEDIUM RISK: {', '.join(risk_factors[:2])}"
            else:
                rationale = f"LOW RISK: Standard transaction pattern"

            return {
                "risk_score": round(risk_score, 2),
                "rationale": rationale
            }

        # Real Gemini API call (Generative Language API)
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1024,
                "response_mime_type": "application/json",
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "risk_score": {"type": "number"},
                        "rationale": {"type": "string"}
                    },
                    "required": ["risk_score", "rationale"]
                }
            }        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Normalize model name for GL API (strip trailing -001 for 2.x variants)
            gl_model = GEMINI_MODEL
            if gl_model.startswith("gemini-2") and gl_model.endswith("-001"):
                gl_model = gl_model.rsplit("-", 1)[0]
            # Preferred: OAuth flow (Workload Identity / ADC)
            if FORCE_GL_OAUTH:
                try:
                    import google.auth
                    import google.auth.transport.requests as gar
                    req = gar.Request()
                    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/generative-language"])
                    creds.refresh(req)
                    oauth_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {creds.token}"}
                    resp = await client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{gl_model}:generateContent",
                        headers=oauth_headers,
                        json=body,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as oe:
                    logger.error("gemini_api_oauth_error", error=str(oe))
                    raise
            else:
                # Try API key first; if unauthorized, fall back to OAuth
                try:
                    resp = await client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{gl_model}:generateContent",
                        headers={
                            "Content-Type": "application/json",
                            "x-goog-api-key": GEMINI_API_KEY,
                        },
                        json=body,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPStatusError as he:
                    status = he.response.status_code
                    if status in (401, 403):
                        try:
                            import google.auth
                            import google.auth.transport.requests as gar
                            req = gar.Request()
                            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/generative-language"])
                            creds.refresh(req)
                            oauth_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {creds.token}"}
                            resp2 = await client.post(
                                f"https://generativelanguage.googleapis.com/v1beta/models/{gl_model}:generateContent",
                                headers=oauth_headers,
                                json=body,
                            )
                            resp2.raise_for_status()
                            data = resp2.json()
                        except Exception as oe:
                            logger.error("gemini_api_oauth_error", error=str(oe))
                            raise
                    else:
                        raise
            # Structure-only debug and safety handling (no PII)
            try:
                candidates = data.get("candidates", []) if isinstance(data, dict) else []
                cand_count = len(candidates)
                pf = data.get("promptFeedback") or data.get("prompt_feedback") or {}
                block_reason = pf.get("blockReason") or pf.get("block_reason")
                first_parts = []
                if cand_count > 0:
                    maybe_parts = candidates[0].get("content", {}).get("parts", [])
                    for prt in maybe_parts:
                        if isinstance(prt, dict):
                            ks = set(prt.keys()) & {"text","functionCall","function_call","inlineData","inline_data"}
                            first_parts.append(sorted(list(ks)))
                logger.info(
                    "gemini_api_response_shape",
                    cand_count=cand_count,
                    has_prompt_feedback=bool(pf),
                    block_reason=block_reason or "",
                    first_part_kinds=first_parts,
                )
                if cand_count == 0:
                    rationale = "Model returned no content (safety or empty). Conservative assessment applied."
                    if block_reason:
                        rationale = f"Model blocked ({block_reason}). Conservative assessment applied."
                    return {"risk_score": 0.5, "rationale": rationale}
            except Exception:
                logger.info("gemini_api_shape_log_skip")
            parts = (data.get("candidates", [{}])[0].get("content", {}).get("parts", []) if isinstance(data, dict) else [])
            # Handle functionCall(args={...}) structure first
            try:
                for p in parts:
                    if isinstance(p, dict):
                        fc = p.get("function_call") or p.get("functionCall")
                        if fc and isinstance(fc, dict):
                            args = fc.get("args")
                            if isinstance(args, dict) and "risk_score" in args and "rationale" in args:
                                return args
            except Exception:
                pass
            def decode_inline(part: dict) -> str:
                try:
                    import base64
                    idata = part.get("inline_data") or part.get("inlineData")
                    if isinstance(idata, dict):
                        mt = idata.get("mime_type") or idata.get("mimeType")
                        if mt and "json" in mt.lower():
                            b64 = idata.get("data")
                            if b64:
                                return base64.b64decode(b64).decode("utf-8", errors="ignore")
                except Exception:
                    return ""
                return ""
            pieces = []
            for p in parts:
                if not isinstance(p, dict):
                    continue
                t = p.get("text")
                if t:
                    pieces.append(t)
                    continue
                decoded = decode_inline(p)
                if decoded:
                    pieces.append(decoded)
            agg = "".join(pieces)
            # Primary: parse concatenated text or decoded inline JSON
            try:
                return json.loads(agg)
            except Exception:
                pass
            # Secondary: search json in concatenated text
            try:
                import re
                m = re.search(r"\{[\s\S]*\}", agg)
                if m:
                    return json.loads(m.group(0))
            except Exception:
                pass
            # Tertiary: deep search in the entire response structure
            def find_json_obj(o):
                if isinstance(o, dict):
                    if "risk_score" in o and "rationale" in o:
                        return o
                    for v in o.values():
                        r = find_json_obj(v)
                        if r is not None:
                            return r
                elif isinstance(o, list):
                    for v in o:
                        r = find_json_obj(v)
                        if r is not None:
                            return r
                elif isinstance(o, str):
                    try:
                        jo = json.loads(o)
                        if isinstance(jo, dict) and "risk_score" in jo and "rationale" in jo:
                            return jo
                    except Exception:
                        try:
                            m2 = re.search(r"\{[\s\S]*\}", o)
                            if m2:
                                jo2 = json.loads(m2.group(0))
                                if isinstance(jo2, dict) and "risk_score" in jo2 and "rationale" in jo2:
                                    return jo2
                        except Exception:
                            pass
                return None
            found = find_json_obj(data)
            if found is not None:
                return found
            return {"risk_score": 0.5, "rationale": "Model response unavailable (format). Conservative assessment applied."}

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
        # Ensure JSON-serializable payload (datetime → ISO string)
        try:
            payload = json.loads(risk_result.model_dump_json())  # Pydantic v2
        except AttributeError:
            payload = json.loads(risk_result.json())  # Pydantic v1 fallback
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{EXPLAIN_AGENT_URL}/process",
                json=payload,
                timeout=10.0
            )
            response.raise_for_status()

            logger.info(
                "result_sent_to_explain_agent",
                transaction_id=risk_result.transaction_id
            )

    except Exception as e:
        # Catch any serialization or HTTP errors and log; do not fail the analysis
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
            amount=transaction.amount
        )

        # RAG: fetch and summarize account history
        history = await fetch_account_history(transaction.account_id, limit=50)
        try:
            rag_summary = summarize_history_for_rag(history)
        except Exception as e:
            logger.error("rag_summary_failed", error=str(e))
            rag_summary = {"known_recipients": [], "typical_amount": 0, "common_hours": [], "history_count": 0}

        # Build Vertex prompt with RAG context
        # BoA-aligned payload (restrict to allowed fields)
        label = getattr(transaction, "label", None) or transaction.merchant
        tx_payload = {
            "transaction_id": transaction.transaction_id,
            "account_id": transaction.account_id,
            "amount": transaction.amount,
            "label": label,
            "type": getattr(transaction, "type", None) or "unknown",
            "timestamp": transaction.timestamp.isoformat(),
        }
        pattern_signals = analyze_pattern_signals(tx_payload, rag_summary)
        prompt = build_vertex_prompt(tx_payload, rag_summary, pattern_signals)

        # Debug logging for enhanced prompting
        logger.info(
            "enhanced_prompt_debug",
            transaction_id=transaction.transaction_id,
            history_count=len(history),
            rag_recipients=len(rag_summary.get("known_recipients", [])),
            prompt_contains_historical="HISTORICAL ANALYSIS:" in prompt,
            prompt_preview=prompt[:200] + "..." if len(prompt) > 200 else prompt
        )

        # Build baseline historical rationale (even if AI falls back)
        baseline_rationale = None
        try:
            recipient_key = str(tx_payload.get("label") or "").lower()
            amount_val = float(tx_payload.get("amount") or 0)
            for recip in rag_summary.get("known_recipients", []):
                if str(recip.get("recipient", "")).lower() == recipient_key:
                    typical = float(recip.get("typical_amount") or 0)
                    count = int(recip.get("count") or 0)
                    if typical > 0 and count > 0:
                        ratio = amount_val / typical if typical > 0 else 1.0
                        baseline_rationale = (
                            f"Known recipient {recipient_key} with {count} prior txns (typical ${typical:.2f}). "
                            f"Current ${amount_val:.2f} is {ratio:.1f}x typical."
                        )
                        break
        except Exception:
            baseline_rationale = None
        # If no recipient-specific baseline, provide overall account baseline when history exists
        if not baseline_rationale:
            try:
                hc = int(rag_summary.get("history_count", 0) or 0)
                if hc > 0:
                    typical_overall = float(rag_summary.get("typical_amount", 0) or 0)
                    baseline_rationale = (
                        f"History available: {hc} prior transactions overall (typical ${typical_overall:.2f})."
                    )
            except Exception:
                pass

        # Structured signals (no PII) for debugging and model improvement
        try:
            logger.info(
                "pattern_signals",
                transaction_id=transaction.transaction_id,
                known_recipient=bool(pattern_signals.get("known_recipient")),
                amount_deviation_flag=bool(pattern_signals.get("amount_deviation_flag")),
                off_hours=bool(pattern_signals.get("off_hours")),
                velocity_15m=int(pattern_signals.get("velocity_15m", 0)),
                velocity_60m=int(pattern_signals.get("velocity_60m", 0)),
                velocity_flag=bool(pattern_signals.get("velocity_flag")),
            )
        except Exception:
            pass

        # Temporary debug (no PII): log invocation mode and RAG size
        logger.info(
            "ai_invoke",
            transaction_id=transaction.transaction_id,
            use_vertex=bool(USE_VERTEX_AI and GEMINI_PROJECT_ID != "PROJECT_ID"),
            use_sdk=bool(USE_VERTEX_SDK),
            project=GEMINI_PROJECT_ID,
            location=GEMINI_LOCATION,
            model=GEMINI_MODEL,
            rag_history_count=int(rag_summary.get("history_count", 0)),
            signals_included=True,
        )

        # Prefer GL API first when enabled
        if PREFER_GL_API:
            # Use the same strict prompt used for Vertex path
            try:
                ai_result = await call_gemini_api(prompt)
            except Exception:
                ai_result = {"risk_score": 0.5, "rationale": "Gemini API error - fallback used"}
            # If GL result looks like fallback, optionally try Vertex
            if (not isinstance(ai_result, dict)) or ("risk_score" not in ai_result) or (lambda _r: (_r == "unparsable ai output" or "conservative assessment applied" in _r))(str(ai_result.get("rationale", "")).lower()):
                if USE_VERTEX_AI and GEMINI_PROJECT_ID != "PROJECT_ID":
                    ai_result = await call_vertex_ai(prompt)
        else:
            # Prefer Vertex AI call when enabled and configured
            if USE_VERTEX_AI and GEMINI_PROJECT_ID != "PROJECT_ID":
                ai_result = await call_vertex_ai(prompt)
            else:
                # Fallback to GL API with legacy prompt
                legacy_prompt = create_risk_analysis_prompt(transaction)
                ai_result = await call_gemini_api(legacy_prompt)

        # Temporary debug (no PII): log source and a short rationale preview
        source = (
            "gemini_api" if PREFER_GL_API else (
                "vertex" if (USE_VERTEX_AI and GEMINI_PROJECT_ID != "PROJECT_ID") else (
                    "gemini_api" if (GEMINI_API_KEY and GEMINI_API_KEY != "PLACEHOLDER_GEMINI_API_KEY") else "fallback"
                )
            )
        )
        logger.info(
            "ai_result_received",
            transaction_id=transaction.transaction_id,
            source=source,
            risk_score=float(ai_result.get("risk_score", 0.5)),
            rationale_preview=(str(ai_result.get("rationale", ""))[:80]),
        )

        # Normalize result (and improve when AI output format is unavailable)
        score_val = float(ai_result.get("risk_score", 0.5))
        rationale_val = ai_result.get("rationale", "No rationale provided")
        rlow = str(rationale_val).strip().lower()
        if (
            "conservative assessment applied" in rlow
            or rlow == "unparsable ai output"
            or rlow.startswith("vertex ai error")
            or rlow.startswith("unable to analyze")
        ):
            h_score, h_reason = heuristic_risk_from_tx(tx_payload)
            score_val = h_score
            rationale_val = f"Heuristic fallback: {h_reason}"

        # Prefer baseline historical rationale when available (ensures intelligent context)
        if baseline_rationale:
            rv = str(rationale_val or "").lower()
            generic = (
                ("standard transaction pattern" in rv) or
                ("medium amount" in rv) or
                ("model response unavailable" in rv) or
                ("heuristic fallback" in rv)
            )
            if (not rationale_val) or generic:
                rationale_val = baseline_rationale
        # If AI incorrectly claims no history while we have it, override with baseline
        rv2 = str(rationale_val or "").lower()
        misleading_no_history = any(p in rv2 for p in [
            "without historical data",
            "lack of historical data",
            "insufficient data",
            "no historical data",
            "without history"
        ])
        try:
            if int(rag_summary.get("history_count", 0) or 0) > 0 and misleading_no_history:
                if baseline_rationale:
                    rationale_val = baseline_rationale
        except Exception:
            pass

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
        if not DISABLE_EXPLAIN_AGENT:
            await send_to_explain_agent(risk_score)
        else:
            logger.info("explain_agent_disabled")

        return risk_score

    except Exception as e:
        # Log via structlog and stdlib logger (with traceback) to ensure visibility
        logger.error(
            "risk_analysis_failed",
            transaction_id=transaction.transaction_id,
            error=str(e)
        )
        logging.exception("risk_analysis_failed_exception")
        raise HTTPException(status_code=500, detail="Risk analysis failed")


@app.post("/a2a/route")
async def a2a_route(payload: dict):
    """Lightweight A2A routing endpoint for demo purposes.
    Accepts: {"target": "explain-agent" | "risk-scorer", "message": {...}}
    """
    try:
        target = str(payload.get("target", "")).lower()
        message = payload.get("message", {})
        if target == "explain-agent":
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{EXPLAIN_AGENT_URL}/process", json=message, timeout=10.0)
                resp.raise_for_status()
            logger.info("a2a_forwarded", target=target)
            return {"status": "ok", "forwarded_to": target}
        else:
            # For demo, echo back
            logger.info("a2a_echo", target=target)
            return {"status": "ok", "echo": True}
    except Exception as e:
        logger.error("a2a_route_error", error=str(e))
        raise HTTPException(status_code=500, detail="A2A routing failed")


if __name__ == "__main__":
    import uvicorn
    logger.info("starting_risk_scorer", port=PORT, gemini_model=GEMINI_MODEL)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
