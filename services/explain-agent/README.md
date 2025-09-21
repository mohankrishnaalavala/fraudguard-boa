# explain-agent

Converts AI risk analysis into user-friendly explanations and orchestrates actions.

## Purpose
- Receive risk analysis (risk-scorer) and create an AuditRecord
- Persist audit records (SQLite for demo) and expose read APIs
- Notify action-orchestrator to execute recommended action

## Key endpoints
- GET /healthz
- POST /process → returns AuditRecord
- GET /audit/{transaction_id}
- GET /audit?limit=50

## Configuration
- DATABASE_URL (e.g., sqlite:///var/run/audit.db)
- ACTION_ORCHESTRATOR_URL (default: http://action-orchestrator.fraudguard.svc.cluster.local:8080)

## Security & Ops
- JSON logs without PII
- Runs as non-root; readOnlyRootFilesystem; NetworkPolicy
- Exposes GET /healthz

