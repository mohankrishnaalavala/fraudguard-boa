# action-orchestrator

Executes actions based on risk analysis results from explain-agent.

## Purpose
- Perform demo-grade actions: notify, step-up, hold, allow
- Return a standard ActionResult for UI and auditing

## Key endpoints
- GET /healthz
- POST /execute { transaction_id, risk_score, action, explanation }
- GET /thresholds

## Configuration
- RISK_THRESHOLD_NOTIFY (default 0.3)
- RISK_THRESHOLD_STEPUP (default 0.6)
- RISK_THRESHOLD_HOLD (default 0.8)
- BOA_BASE_URL (placeholder for future A2A calls)

## Security & Ops
- JSON logs without PII
- Runs as non-root; readOnlyRootFilesystem; NetworkPolicy
- Exposes GET /healthz

