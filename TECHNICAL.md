# TECHNICAL.md

0) Top metadata (at-a-glance)
- One-liner: FraudGuard adds AI-powered fraud risk scoring to Bank of Anthos without changing BoA core – API-only integration, deployable on GKE Autopilot.
- Live Demo:
  - Dashboard: https://fraudguard.mohankrishna.site/
  - Bank of Anthos: https://boa.mohankrishna.site/
  - Test creds: use the demo credentials shown on your BoA login page (do not hardcode in docs).
- Demo Commit/Tag: Deployed images are SHA-pinned per workflow run (see GitHub Actions logs for the exact commit SHA used in Helm `--set image.tag=<sha>`).
- Required Roles/Permissions (brief):
  - Google Cloud project with Billing
  - Artifact Registry push (Workload Identity Federation from GitHub)
  - GKE Autopilot cluster access (gcloud + GKE auth plugin)
  - DNS/ManagedCertificate for HTTPS
- BoA note: No BoA core changes; we consume BoA via its public services/APIs only.

1) System overview
- FraudGuard ingests BoA transactions (via boa-monitor → mcp-gateway), analyzes them with Gemini/Vertex AI in risk-scorer using RAG over recent history, explains outcomes (explain-agent), suggests actions (action-orchestrator), and visualizes in a tri-level risk dashboard.
- High-level architecture diagram: see images/architecture.png (also referenced in README). A conceptual ASCII is below.
  - Data flow (prod): boa-monitor → mcp-gateway → risk-scorer → explain-agent → action-orchestrator → dashboard
  - Demo feeder: txn-watcher (optional) → mcp-gateway → risk-scorer → … (same pipeline)

```text
[ BoA UI/Services ] --(JWT, APIs)--> [ boa-monitor ] --POST--> [ mcp-gateway ]
                                                |                      |
                                                |                      v
                                          [ risk-scorer ] <---- GET /accounts/{id}/transactions
                                                |
                                                v
                                         [ explain-agent ] -> [ action-orchestrator ]
                                                |
                                                v
                                            [ dashboard ] (High/Medium/Low)

[ txn-watcher (demo feeder) ] --POST--> [ mcp-gateway ]  (shares the same risk pipeline)
```

2) Prerequisites
- Google Cloud project with billing enabled
- GKE Autopilot cluster (region us-central1 recommended)
- Artifact Registry: `us-docker.pkg.dev/<PROJECT_ID>/fraudguard`
- Domain & DNS (Cloud DNS or external)
- CLI tools: gcloud, kubectl, helm, terraform (if using infra repo)

3) Local development (fast loop)
- Run a single service locally (example: risk-scorer)
  - Env vars: minimally `PORT=8080`, AI config (see Section 5)
  - Start: `cd services/risk-scorer && python main.py`
  - Health: `curl -f localhost:8080/healthz`
  - Simulate analysis:
    ```bash
    curl -sS -X POST localhost:8080/analyze -H 'Content-Type: application/json' -d '{
      "transaction_id":"local-1","amount":1200.0,"currency":"USD","account_id":"demo1",
      "label":"merchant-a","type":"debit","category":"transfer","timestamp":"2025-01-01T00:00:00Z"
    }'
    ```
- View structured logs: `kubectl logs deploy/risk-scorer -n fraudguard -f | jq .`

4) GKE deployment (end-to-end)
- Namespaces: `boa`, `fraudguard`
- Secrets: `boa-api-credentials` (BOA_USERNAME, BOA_PASSWORD) in `fraudguard`
- Helm install/upgrade (SHA tag used by CI/CD):
  ```bash
  helm upgrade --install risk-scorer ./helm/workload -n fraudguard -f values/risk-scorer.yaml --set image.tag=<SHA> --atomic --wait
  # repeat for: mcp-gateway, dashboard, boa-monitor, explain-agent, action-orchestrator
  ```
- Readiness: `kubectl wait --for=condition=available deploy -n fraudguard --all --timeout=300s`
- Smoke: create a BoA transfer, then open the dashboard and verify a risk row appears

5) How Google AI is used
- Paths: Gemini Generative Language API and/or Vertex AI SDK (configurable)
- Env vars (representative):
  - GL path: `GEMINI_MODEL`, `GEMINI_API_KEY`
  - Vertex path: `GEMINI_MODEL`, `GEMINI_PROJECT_ID`, `GEMINI_LOCATION`, `USE_VERTEX_AI=true`, `FORCE_GL_OAUTH=false` (use ADC)
- RAG context:
  - Recent history window: `RAG_HISTORY_LIMIT` (default 50)
  - Signals: frequency, timing (ToD/DOW), typical amounts, recipient anomaly, velocity
- Verifying AI invocation
  - Search logs for events like `ai_request_started`, `ai_request_completed`, `rag_summary`, `pattern_signals`

6) Optional components (used: what/why/how)
- MCP Gateway (used)
  - Purpose: central API for ingesting and serving transactions, and handing off to the risk pipeline.
  - Entrypoints:
    - Local: `cd services/mcp-gateway && python main.py`
    - Helm: `helm upgrade --install mcp-gateway ./helm/workload -n fraudguard -f values/mcp-gateway.yaml --set image.tag=<SHA> --atomic --wait`
  - On/Off: deploy/undeploy the `mcp-gateway` Helm release. Disabling it stops ingest and end-to-end analysis.
- A2A service-to-service (used)
  - Purpose: internal calls among services (boa-monitor → mcp-gateway; mcp-gateway → risk-scorer; risk-scorer → explain-agent/action-orchestrator; mcp-gateway → dashboard).
  - How: ClusterIP Services with NetworkPolicies; no public exposure.
  - On/Off: controlled via K8s Services/Deployments and NetworkPolicies. Tightening/denying specific policies will block the corresponding flows; keep defaults for normal operation.

7) Helm charts (app)
- Location: `helm/workload`
- Values to change: hostnames, image tags, resources, history window (`RAG_HISTORY_LIMIT`)
- Override safely: `--set` for one-offs; or copy values/<service>.yaml and keep under version control
- Installs: Deployments, Services, optional Ingress/ManagedCert (via k8s manifests), NetworkPolicy; HPA optional

8) Terraform (infra)
- Repo: https://github.com/mohankrishnaalavala/infra-gcp-gke
- Resources: GKE Autopilot, Artifact Registry, DNS, static IP, ManagedCertificate, Workload Identity bindings
- Minimal apply sequence: init → plan → apply; then apply the app repo k8s manifests and Helm charts

9) Security
- Containers: runAsNonRoot, readOnlyRootFilesystem
- RBAC: least-privileged service accounts; Workload Identity for CI/CD
- NetworkPolicy: restrict east-west; allow only necessary service communications
- Secrets: Secret Manager CSI or K8s Secret; no secrets in code
- Privacy: logs exclude PII; prompts limited to non-PII features

10) Networking
- Services: ClusterIP for internal services, Ingress for public endpoints
- Public hosts: dashboard + BoA on HTTPS (Managed Certificates)
- Probes: liveness/readiness; HPA optional

11) DNS & TLS
- Reserve static IP for Ingress
- Create A records for dashboard + BoA
- Apply ManagedCertificate manifests; wait for `Active`
- Verify HTTPS end-to-end by loading domains in a browser and checking cert

12) Observability & operations
- Health endpoints: every service exposes `GET /healthz` (200 JSON)
- Logs: JSON structured; search keys like `event`, `severity`, `transaction_id`
- Common tail: `kubectl logs -n fraudguard deploy/<svc> -f | jq .`
- “Good looks like”: Dashboard shows recent BoA transfers; High/Medium/Low buckets update within seconds

13) Error handling & failures
- Common failures: BoA auth issues, AI timeouts, history fetch errors
- Fallbacks: deterministic rules (e.g., new recipient + amount threshold; >= N× typical) even when AI path is slow
- Logs to search: `boa_history_error`, `amount_vs_typical_*`, `rule_escalation_applied`, `ai_request_*`

14) Performance & scaling
- Defaults: conservative resource requests; scale with HPA as needed
- `RAG_HISTORY_LIMIT=50` balances latency and context
- Vector upserts are async fire-and-forget to avoid blocking main path

15) Configuration reference (examples)
- Global/AI:
  - `USE_VERTEX_AI` (bool), `GEMINI_MODEL`, `GEMINI_PROJECT_ID`, `GEMINI_LOCATION`, `FORCE_GL_OAUTH`
- Risk rules:
  - `DEVIATION_HIGH_MULTIPLIER` (default 9), `DEVIATION_MIN_SCORE` (default 0.8)
  - `NEW_RECIPIENT_HIGH_AMOUNT_THRESHOLD` (default 999), `NEW_RECIPIENT_MIN_SCORE` (default 0.8)
- RAG/Vector:
  - `RAG_HISTORY_LIMIT` (default 50), `USE_VERTEX_MATCHING`, `ENABLE_VECTOR_UPSERTS`, `VERTEX_EMBED_MODEL`, `VERTEX_ME_INDEX*`

16) API entry points (brief)
- mcp-gateway:
  - POST `/api/transactions` (ingest)
  - GET `/accounts/{id}/transactions?limit=…` (history)
  - POST `/mcp/analyze` (forward to risk-scorer)
  - GET `/healthz`
- risk-scorer:
  - POST `/analyze`
  - GET `/healthz`
- boa-monitor / txn-watcher:
  - GET `/healthz`, GET `/status` (watcher)

17) Demo scenarios (for judges)
- New payee + high amount → expect HOLD/High; rationale mentions new recipient threshold
- Known recipient + typical amount → expect Low/Medium; rationale shows pattern alignment
- Reset between runs: redeploy mcp-gateway or clear its demo DB if needed (demo-grade storage)

18) Limitations
- Demo-grade local storage; single-account emphasis; limited categories
- AI fallback rules kick in if API keys/ADC missing
- For full scale: multi-account feature store, durable DB, rate limits, drift checks

19) Future enhancements
- Make Vertex path default; richer features; BigQuery/Feature Store; streaming (Pub/Sub)
- Alerting/notifications; policy-as-code for actions; audit viewer; expanded A2A/ADK/MCP tooling

