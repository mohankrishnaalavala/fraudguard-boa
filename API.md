# FraudGuard API Reference (Simplified Architecture)

This document lists all service endpoints for the simplified architecture using real Bank of Anthos (BoA) data via boa-monitor. All services expose GET /healthz and write JSON logs without PII.

Services:
- boa-monitor — fetches BoA transactions and forwards to MCP Gateway
- mcp-gateway — stores transactions and exposes APIs to UI/services
- risk-scorer — AI risk analysis (Vertex AI/Gemini); fetches history via MCP/BoA
- explain-agent — turns AI output into user explanations and actions
- action-orchestrator — executes actions (notify/step-up/hold/allow)
- dashboard — read-only UI calling gateway/explain-agent

Auth: In-cluster only; protected by NetworkPolicy. No external auth is required for the hackathon demo.

---
## boa-monitor
Base URL: http://boa-monitor:8080

- GET /healthz → { status, service, timestamp, monitoring_status, last_poll }
- GET /status → monitoring status and counters
- GET /transactions/{account_id}?limit=50 → list of BoA txns (normalized BoA fields)
- POST /manual-sync → forces a single fetch-forward cycle; returns counts

Environment variables:
- MCP_GATEWAY_URL, POLL_INTERVAL, BOA_USERSERVICE_URL, BOA_HISTORY_URL, BOA_USERNAME, BOA_PASSWORD

---
## mcp-gateway
Base URL: http://mcp-gateway:8080

- GET /healthz → { status, service, timestamp }
- GET /accounts/{account_id} → account summary (demo/mock)
- GET /accounts/{account_id}/transactions?limit=50 → recent txns for account (authoritative FraudGuard view)
- POST /api/transactions → submit txn and trigger async risk analysis
  Request (JSON): { transaction_id, amount, merchant|label, user_id, timestamp, type? }
  Response: { status: "accepted", transaction_id, timestamp }
- GET /api/recent-transactions?limit=20 → { transactions: [...] } newest-first across all accounts

MCP-style helpers:
- GET /mcp/schema → lightweight tool schema
- GET /mcp/transactions/{account_id}?limit=50 → raw history list
- POST /mcp/analyze { transaction: {...} } → forwards to risk-scorer

Notes:
- Rate limiting with in-cluster bypass (DISABLE_RATE_LIMIT_INTERNAL=true by default)
- SQLite storage at /var/run/transactions.db (demo)

---
## risk-scorer
Base URL: http://risk-scorer:8080

- GET /healthz → { status, service, timestamp }
- POST /analyze → risk analysis for a single transaction
  Request (JSON):
  {
    transaction_id, account_id, amount, label|merchant, timestamp,
    type?, location?, category?
  }
  Response (JSON): { risk_score: number 0..1, rationale: string, timestamp }

Config:
- USE_VERTEX_AI=true (default), PREFER_GL_API, FORCE_GL_OAUTH
- GEMINI_MODEL, GEMINI_PROJECT_ID, GEMINI_LOCATION
- MCP_GATEWAY_URL (for history), BOA_* (optional history), EXPLAIN_AGENT_URL

---
## explain-agent
Base URL: http://explain-agent:8080

- GET /healthz → { status, service, timestamp }
- POST /process → create audit record + dispatch action
  Request: { transaction_id, risk_score, rationale, timestamp }
  Response: AuditRecord { id?, transaction_id, risk_score, rationale, explanation, action, timestamp }
- GET /audit/{transaction_id} → AuditRecord
- GET /audit?limit=50 → [AuditRecord]

Env: DATABASE_URL (sqlite path), ACTION_ORCHESTRATOR_URL

---
## action-orchestrator
Base URL: http://action-orchestrator:8080

- GET /healthz → { status, service, timestamp }
- POST /execute → execute an action
  Request: { transaction_id, risk_score, action: "notify"|"step-up"|"hold"|"allow", explanation }
  Response: { transaction_id, action, success, message, timestamp }
- GET /thresholds → { notify, step_up, hold }

---
## dashboard
Base URL: http(s)://fraudguard-host/

- GET /healthz → { status, service, timestamp }
- UI / → read-only dashboard
- GET /api/records → list of recent transactions (from MCP Gateway)
- GET /api/stats → { high_risk, medium_risk, low_risk, total }
- POST /api/notify { transaction_id, risk_score, explanation } → forwards to action-orchestrator

---
## Data formats
Transaction (canonical within MCP Gateway):
- transaction_id: string
- account_id: string
- amount: number
- label/merchant: string (may be acct:recipientId)
- timestamp: ISO 8601 string
- type: debit|credit (optional)
- risk_score/risk_level/risk_explanation: added by analysis

AuditRecord:
- id?, transaction_id, risk_score, rationale, explanation, action, timestamp

Security baseline:
- No secrets in code; use K8s Secret/Secret Manager CSI for credentials
- Services run as non-root with readOnlyRootFilesystem and NetworkPolicy

