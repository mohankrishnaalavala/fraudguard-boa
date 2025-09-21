# FraudGuard Deployment Guide (Simplified: boa-monitor → mcp-gateway → risk-scorer)

This guide installs the simplified FraudGuard stack that uses real Bank of Anthos (BoA) data via boa-monitor. All services run in the `fraudguard` namespace. BoA runs in the `boa` namespace.

Components:
- boa-monitor, mcp-gateway, risk-scorer, explain-agent, action-orchestrator, dashboard

## Prerequisites
- gcloud, kubectl, helm installed
- GKE Autopilot cluster with Workload Identity (see infra repo)
- Logged in: `gcloud auth login` and `gcloud auth application-default login`
- Cluster context: `gcloud container clusters get-credentials fraudguard-auto --region us-central1`
- Namespaces:
  - `kubectl create ns boa || true`
  - `kubectl create ns fraudguard || true`
- Bank of Anthos deployed in `boa` (see https://github.com/GoogleCloudPlatform/bank-of-anthos)
- DNS/Ingress (optional): apply `k8s/ingress.yaml` and `k8s/boa-ingress.yaml`

## Configure BoA credentials for boa-monitor
Create a secret with BoA demo credentials (do not commit credentials):

```
kubectl -n fraudguard create secret generic boa-api-credentials \
  --from-literal=BOA_USERNAME="<boa-username>" \
  --from-literal=BOA_PASSWORD="<boa-password>"
```

Ensure `values/boa-monitor.yaml` mounts or envFrom this secret (or set via workload identity and env vars in Helm values).

## Deploy services via Helm
Option A: Makefile convenience (recommended)

```
make install-helm NAMESPACE=fraudguard
```

Option B: Helm directly

```
for s in mcp-gateway boa-monitor risk-scorer explain-agent action-orchestrator dashboard; do 
  helm upgrade --install $s ./helm/workload -n fraudguard -f values/$s.yaml --create-namespace
done
```

## Uninstall txn-watcher (legacy)
If previously installed, remove it from cluster:

```
helm uninstall txn-watcher -n fraudguard || true
```

## Verify deployment
```
kubectl get pods -n fraudguard
kubectl get svc -n fraudguard
```

Health checks (port-forward one by one):
```
# MCP Gateway
kubectl -n fraudguard port-forward svc/mcp-gateway 8082:8080 &
curl -f http://localhost:8082/healthz
curl -s http://localhost:8082/api/recent-transactions | head -c 400; echo
kill %1

# boa-monitor
kubectl -n fraudguard port-forward svc/boa-monitor-workload 8091:8080 &
curl -f http://localhost:8091/healthz
kill %1

# risk-scorer
kubectl -n fraudguard port-forward svc/risk-scorer 8092:8080 &
curl -f http://localhost:8092/healthz
kill %1

# dashboard
kubectl -n fraudguard port-forward svc/dashboard 8080:8080 &
curl -f http://localhost:8080/healthz
kill %1
```

## Trigger end-to-end flow (BoA → boa-monitor → MCP → risk-scorer)
- Make a transfer in Bank of Anthos UI (boa namespace/ingress), or
- Manually trigger boa-monitor fetch-forward cycle:

```
kubectl -n fraudguard port-forward svc/boa-monitor-workload 8091:8080 &
curl -X POST http://localhost:8091/manual-sync
kill %1
```

Then query recent transactions from MCP Gateway:
```
kubectl -n fraudguard port-forward svc/mcp-gateway 8082:8080 &
curl -s "http://localhost:8082/api/recent-transactions?limit=5" | jq .
kill %1
```

## Configuration notes
- All services provide GET /healthz and structured JSON logs with no PII.
- Security baseline: non-root, readOnlyRootFilesystem, NetworkPolicy, Secret Manager/Secrets (no secrets in code).
- Vertex AI is preferred in risk-scorer (USE_VERTEX_AI=true). Fallbacks to GL API or heuristic mock preserved for demo resilience.
- MCP Gateway caps history at 50 recent transactions per account for RAG context.

## Cleanup
```
for s in mcp-gateway boa-monitor risk-scorer explain-agent action-orchestrator dashboard; do
  helm uninstall $s -n fraudguard || true
done
```

