# FraudGuard on GKE — Bank of Anthos (API-only extension)

**One-liner:** Agentic fraud risk analysis for **Bank of Anthos** on **GKE Autopilot** using **Gemini / Vertex AI** — **no BoA core changes**.  
**Same cluster:** namespaces **`boa`** (BoA) and **`fraudguard`** (FraudGuard).

## Problem
Real-time fraud detection needs velocity/deviation/recipient analysis without disrupting users or modifying core banking services.

## Solution
FraudGuard ingests BoA transactions via read-only APIs, applies **Gemini/Vertex AI** (with a small RAG window over recent history), and surfaces a **read-only** risk dashboard (High / Medium / Low). **No changes to BoA core; API-only integration.**

**Links**
- 🎥 **Submission video (≤ 3 min):** _ADD PUBLIC LINK HERE_
- 🌐 **Dashboard:** https://fraudguard.mohankrishna.site/  *(user/pass: `admin` / `admin`)*
- 🏦 **BoA (demo):** https://boa.mohankrishna.site/
- 📘 **Technical details:** [TECHNICAL.md](./TECHNICAL.md)

---

## What it does (30-sec read)
- Reads BoA transactions via **JWT + APIs**, normalizes, and posts to the pipeline.  
- Scores risk with **Gemini/Vertex AI** using recent history for velocity, deviation, and recipient patterns.  
- Explains each decision and displays **High / Medium / Low** on a **read-only** dashboard.  
- Optional **action-orchestrator** can hold/flag via BoA API.

**Core components:** `boa-monitor → mcp-gateway → risk-scorer → explain-agent → dashboard` (+ optional `action-orchestrator`).  
**Security/ops:** Workload Identity, Secret Manager CSI, NetworkPolicy, non-root containers, Managed Certs, Cloud Logging/Monitoring.

---

## Components on GKE (brief)
- **mcp-gateway** — ingest & history APIs for services/UI  
- **boa-monitor** — authenticates to BoA, fetches history, forwards events  
- **risk-scorer** — Gemini/Vertex AI analysis with RAG over recent **N** (default 50)  
- **explain-agent** — rationale/audit store  
- **action-orchestrator (optional)** — can hold/flag via BoA API  
- **dashboard** — Flask UI; tri-level risk (read-only)

## AI models used (brief)
- **Gemini 2.5 Flash** (Generative Language API) and/or **Vertex AI** (configurable)  
- RAG over the **last 50** transactions by default (pattern/velocity/recipient signals)

## Optional components (used)
- **MCP-style gateway** for discoverable service tools/endpoints  
- **A2A service-to-service** calls inside the cluster, restricted by **NetworkPolicies**  
> Details, commands, and toggles are in **TECHNICAL.md**.

---

## Quickstart (≤ 5 minutes)
1. Open **BoA** and make a transfer: https://boa.mohankrishna.site/  
2. Open **FraudGuard dashboard**: https://fraudguard.mohankrishna.site/ *(admin/admin)*  
3. See the bucket update (**High / Medium / Low**) and rationale text.  
4. Need deploy/env/API details? See **[TECHNICAL.md](./TECHNICAL.md)**.

---

## Architecture
![FraudGuard Architecture](images/architecture.png)

> BoA (`ns: boa`) and FraudGuard (`ns: fraudguard`) run in the **same GKE Autopilot cluster**. Integration is via BoA APIs only; **no core changes**.

---

## Screens (replace with captures)
- BoA transfer
![BoA transfer](images/boatransaction.png)
- FraudGuard dashboard 
![FraudGuard login](images/login.png)
![FraudGuard dashboard](images/dashboard.png)

---

## License
Apache-2.0
