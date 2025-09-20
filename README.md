# FraudGuard on GKE — Hackathon Submission

## Problem
Real-time fraud detection on consumer banking requires analyzing transaction patterns (frequency, timing, velocity), typical amounts, and recipient anomalies without disrupting users or modifying core banking services.

## Solution
FraudGuard is an AI extension built on Bank of Anthos (BoA). It ingests BoA transactions via APIs, applies Vertex AI/Gemini RAG-driven analysis, and surfaces a tri-level risk dashboard (High/Medium/Low). No changes to BoA core; we integrate via services and APIs.

- Built on Bank of Anthos: https://github.com/GoogleCloudPlatform/bank-of-anthos
- Deployed on GKE Autopilot with Google Managed Certs and Ingress

## Components on GKE
- mcp-gateway: Ingests/stores transactions, exposes APIs to UI and services
- boa-monitor: Authenticates to BoA, fetches history, forwards to mcp-gateway
- risk-scorer: Gemini-powered analysis + RAG over history (50 recent records)
- explain-agent + action-orchestrator: Explainability and mitigations
- txn-watcher: Poll/sample watcher for additional analysis paths
- dashboard: Flask UI, tri-level risk (no "Normal")

## AI model(s) used
- Gemini 2.5 Flash via Generative Language API and/or Vertex AI SDK (configurable)
- RAG over recent 50 transactions, with pattern/velocity/recipient analysis

## ADK/MCP/A2A usage
- MCP Gateway stores and serves transactions, supports service-to-service calls
- A2A style internal calls with NetworkPolicies and least-privileged SAs
- No BoA schema changes; only API reads and derived insights

## Deploy steps (Helm/Manifests)
1) kubectl create ns boa; kubectl create ns fraudguard
2) kubectl apply -f fraudguard-boa/k8s/boa-ingress.yaml
3) helm upgrade --install <service> fraudguard-boa/helm/workload -n fraudguard -f fraudguard-boa/values/<service>.yaml (repeat for all)
4) Create K8s Secret boa-api-credentials with BOA_USERNAME/BOA_PASSWORD in fraudguard ns
5) Configure Managed Certificates and Cloud DNS for fraudguard.mohankrishna.site and boa.mohankrishna.site

## Quickstart (≤5 min)
- Make a transfer in BoA UI, then open dashboard: https://fraudguard.mohankrishna.site/
- Watch risk buckets update (High/Medium/Low) and logs in risk-scorer/mcp-gateway

## Test creds
Use the BoA demo credentials shown on the BoA login page of your deployment (do not hardcode credentials).

## Limitations / Roadmap
- Demo-grade SQLite storage; replace with Cloud SQL/Spanner for prod
- Expand model prompts and feature engineering; add BigQuery historical store
- Vertex AI as default path (config toggle already present)


![FraudGuard Architecture](images/architecture.png)
---

## Architecture diagram (conceptual)

```text
[ BoA UI ] -> [ BoA Services ] --(JWT, APIs)--> [ boa-monitor ] --POST--> [ mcp-gateway ]
                                                                                |
                                                                                v
[ txn-watcher ] ---(demo/sample txns)---> [ risk-scorer ] <--GET /api/transactions--
                                                |
                                                v
                                          [ explain-agent ] ---> [ action-orchestrator ]
                                                |
                                                v
                                           [ Dashboard ] (High/Medium/Low)

GKE Autopilot, Ingress + Managed Certs, Workload Identity, NetworkPolicy, Cloud Logging/Monitoring
(No changes to BoA core; extension via APIs only)
```

---

## License
Apache 2.0 (inherits from BoA and this repo)

## Submission page 
This solution deploys fully on Google Kubernetes Engine (GKE Autopilot) and uses Google AI (Gemini) for fraud analysis. It integrates with the open-source Bank of Anthos application strictly via APIs and services with no changes to BoA core. The architecture includes MCP Gateway, BoA Monitor, Risk Scorer (Gemini), Explain Agent, and a tri-level risk Dashboard on GKE, secured by NetworkPolicies and Managed Certificates. Observability is provided via Cloud Logging/Monitoring. DNS is managed in Cloud DNS.

