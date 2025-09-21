# dashboard (web)

Read-only Flask UI for FraudGuard. Displays tri-level risk buckets and recent transactions.

## Purpose
- Fetch recent transactions from MCP Gateway and render a live dashboard
- Show audit records and recommended actions
- Allow triggering a demo notify action (POST /api/notify)

## Key endpoints
- GET /healthz
- GET / (UI)
- GET /api/records
- GET /api/stats
- POST /api/notify { transaction_id, risk_score, explanation }

## Configuration
- MCP_GATEWAY_URL (default: http://mcp-gateway.fraudguard.svc.cluster.local:8080)
- EXPLAIN_AGENT_URL (default: http://explain-agent.fraudguard.svc.cluster.local:8080)
- ACTION_ORCHESTRATOR_URL (default: http://action-orchestrator.fraudguard.svc.cluster.local:8080)
- REFRESH_INTERVAL_SECONDS (default: 10)

## Security & Ops
- JSON logs without PII
- Runs as non-root; readOnlyRootFilesystem; NetworkPolicy
- Exposes GET /healthz

