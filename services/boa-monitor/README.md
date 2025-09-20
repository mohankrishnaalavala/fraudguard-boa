# boa-monitor

Monitors Bank of Anthos (BoA) transactions and forwards them to FraudGuard (MCP Gateway) for AI analysis.

## Purpose
- Authenticate to BoA userservice to obtain a JWT
- Fetch recent transactions from transactionhistory for the current account
- Normalize and forward txns to MCP Gateway `/api/transactions` (async AI analysis)

## Key endpoints
- GET /healthz
- GET /status
- GET /transactions/{account_id}?limit=50
- POST /manual-sync

## Configuration
- MCP_GATEWAY_URL (default: http://mcp-gateway.fraudguard.svc.cluster.local:8080)
- POLL_INTERVAL (seconds, default 10)
- BOA_USERSERVICE_URL, BOA_HISTORY_URL
- BOA_USERNAME, BOA_PASSWORD (use K8s Secret, never commit secrets)

## Security & Ops
- JSON logs without PII; include {event, severity}
- Runs as non-root, readOnlyRootFilesystem, NetworkPolicy
- Exposes GET /healthz

