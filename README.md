# FraudGuard for Bank of Anthos

AI-powered fraud detection system that runs alongside Bank of Anthos on GKE Autopilot. Uses Gemini AI to analyze transactions in real-time and trigger appropriate actions.

## 🚀 Reproduce in 10 Minutes

### Prerequisites

- GKE Autopilot cluster running
- Artifact Registry repository configured
- `kubectl` configured for your cluster
- `helm` installed (v3.0+)

### Quick Start

1. **Clone and navigate to the repository:**
   ```bash
   git clone <repository-url>
   cd fraudguard-boa
   ```

2. **Update values files with your project details:**
   ```bash
   # Replace PROJECT_ID and REGISTRY in all values/*.yaml files
   find values/ -name "*.yaml" -exec sed -i 's/PROJECT_ID/your-project-id/g' {} \;
   find values/ -name "*.yaml" -exec sed -i 's/REGISTRY/your-registry-name/g' {} \;
   ```

3. **Create namespace and deploy all services:**
   ```bash
   kubectl create namespace fraudguard
   make deploy-all NAMESPACE=fraudguard
   ```

4. **Verify deployment:**
   ```bash
   kubectl get pods -n fraudguard
   make health NAMESPACE=fraudguard
   ```

5. **Run demo to seed test transactions:**
   ```bash
   make demo
   ```

6. **Access the dashboard:**
   ```bash
   kubectl port-forward -n fraudguard svc/dashboard 8080:8080
   # Open http://localhost:8080 in your browser
   ```

### Individual Service Deployment

Deploy services individually using per-service values:

```bash
# Deploy MCP Gateway
helm upgrade --install mcp-gateway ./helm/workload -n fraudguard -f values/mcp-gateway.yaml

# Deploy Transaction Watcher
helm upgrade --install txn-watcher ./helm/workload -n fraudguard -f values/txn-watcher.yaml

# Deploy Risk Scorer
helm upgrade --install risk-scorer ./helm/workload -n fraudguard -f values/risk-scorer.yaml

# Deploy Explain Agent
helm upgrade --install explain-agent ./helm/workload -n fraudguard -f values/explain-agent.yaml

# Deploy Action Orchestrator
helm upgrade --install action-orchestrator ./helm/workload -n fraudguard -f values/action-orchestrator.yaml

# Deploy Dashboard
helm upgrade --install dashboard ./helm/workload -n fraudguard -f values/dashboard.yaml

# Deploy BoA Monitor (requires Secret boa-api-credentials)
# Create secret once:
# kubectl -n fraudguard create secret generic boa-api-credentials \
#   --from-literal=BOA_USERNAME=testuser \
#   --from-literal=BOA_PASSWORD=bankofanthos
helm upgrade --install boa-monitor-workload ./helm/workload -n fraudguard -f values/boa-monitor.yaml
```

## 🏗️ Architecture

FraudGuard consists of 6 microservices that work together to provide real-time fraud detection:

1. **MCP Gateway** - Read-only facade over Bank of Anthos APIs
2. **Transaction Watcher** - Polls for new transactions and triggers analysis
3. **Risk Scorer** - Uses Gemini AI to analyze transaction risk
4. **Explain Agent** - Creates user-friendly explanations and audit records
5. **Action Orchestrator** - Executes actions based on risk scores
6. **Dashboard** - Real-time UI for monitoring transactions and risk scores

### Data Flow

```
Bank of Anthos → MCP Gateway → Txn Watcher → Risk Scorer (Gemini) → Explain Agent → Action Orchestrator
                                                                            ↓
                                                                      Dashboard (UI)
```

## 🛡️ Security Features

- **Least Privilege**: Each service runs with minimal RBAC permissions
- **Network Policies**: Deny-by-default with explicit allow rules
- **Pod Security**: Non-root containers with read-only root filesystem
- **Secret Management**: Integration with Secret Manager CSI
- **No PII in Logs**: Privacy-safe logging and AI prompts

## 📊 Service Details

### MCP Gateway
- **Purpose**: Read-only API facade over Bank of Anthos
- **Features**: Rate limiting, audit logging, MCP tool exposure
- **Port**: 8080
- **Health**: `GET /healthz`

### Transaction Watcher
- **Purpose**: Polls for new transactions and triggers analysis
- **Features**: Configurable polling interval, duplicate detection
- **Port**: 8080
- **Health**: `GET /healthz`

### Risk Scorer
- **Purpose**: AI-powered transaction risk analysis using Gemini
- **Features**: Privacy-safe prompts, configurable thresholds
- **Port**: 8080
- **Health**: `GET /healthz`

### Explain Agent
- **Purpose**: Creates user-friendly explanations and audit records
- **Features**: SQLite audit storage, action determination
- **Port**: 8080
- **Health**: `GET /healthz`

### Action Orchestrator
- **Purpose**: Executes actions based on risk analysis
- **Features**: Configurable thresholds, BoA API integration
- **Port**: 8080
- **Health**: `GET /healthz`

### Dashboard
- **Purpose**: Real-time monitoring UI
- **Features**: Auto-refresh, risk visualization, transaction history
- **Port**: 8080
- **Health**: `GET /healthz`

## 🔧 Configuration

Each service can be configured via environment variables. See individual values files in `values/` directory for service-specific configuration options.

### Key Environment Variables

- `LOG_LEVEL`: Logging level (debug, info, warning, error)
- `PORT`: Service port (default: 8080)
- `GEMINI_API_KEY`: Gemini API key for risk scoring
- `BOA_BASE_URL`: Bank of Anthos base URL
- `BOA_USERSERVICE_URL`: BoA userservice base URL (default: http://userservice.boa.svc.cluster.local:8080)
- `BOA_HISTORY_URL`: BoA transactionhistory base URL (default: http://transactionhistory.boa.svc.cluster.local:8080)
- `BOA_USERNAME`, `BOA_PASSWORD`: Injected via Kubernetes Secret `boa-api-credentials` (do not commit to Git)

## 🧪 Testing

Run tests for all services:

```bash
make test
```

Run linting:

```bash
make lint
```

## 📝 Development

### Building Images

```bash
make build
```

### Viewing Logs

```bash
make logs SERVICE=risk-scorer
```

### Cleanup

```bash
make clean NAMESPACE=fraudguard
```

## 🎯 Demo Script

The included demo script creates sample transactions to demonstrate the fraud detection pipeline:

```bash
./scripts/make_demo.sh
```

This creates:
- Normal grocery transaction (low risk)
- High-value online purchase (high risk)
- Late-night restaurant transaction (medium risk)

## 📋 Helm Chart

The project uses a single, reusable Helm chart (`helm/workload/`) that can be deployed multiple times with different values files. This approach provides:

- **DRY**: Single chart definition for all services
- **Flexibility**: Per-service customization via values files
- **Independence**: Each service can be deployed/updated separately

## 🧱 Infrastructure (infra-gcp-gke)

Infra-as-code lives in a separate repo: https://github.com/mohankrishnaalavala/infra-gcp-gke

High-level spin-up steps (see that repo for full details):
- Prepare env: `gcloud auth application-default login` and set project
- Terraform init/plan/apply under `infra-gcp-gke/envs/<env>` to create:
  - GKE Autopilot cluster (Workload Identity enabled)
  - Artifact Registry (us-docker.pkg.dev/<project>/fraudguard)
  - Service accounts (builder/deployer) and optional budgets
- Networking & DNS for HTTPS:
  - Reserve a global static IP named `fraudguard-ip`
  - Create A records in Cloud DNS (or your DNS provider) pointing both hosts to the Ingress IP
    - fraudguard.mohankrishna.site → <INGRESS_IP>
    - boa.mohankrishna.site → <INGRESS_IP>
  - Apply k8s manifests for Ingress and ManagedCertificate:
    - fraudguard namespace: `k8s/ingress.yaml` (host fraudguard.mohankrishna.site)
    - bank-of-anthos namespace: `k8s/boa-ingress.yaml` (host boa.mohankrishna.site)
  - Wait for ManagedCertificate status = Active; HTTPS will appear automatically

Notes:
- All services expose GET /healthz and use JSON logs without PII
- Security: non-root, readOnlyRootFilesystem, NetPol, Secret Manager CSI
- Dashboard UI shows tri-level risk only (High/Medium/Low)

## 🚨 Troubleshooting

### Common Issues

1. **Services not starting**: Check resource limits in values files
2. **Network connectivity**: Verify NetworkPolicy configurations
3. **Gemini API errors**: Ensure API key is configured correctly
4. **Dashboard not loading**: Check explain-agent service health

### Debug Commands

```bash
# Check pod status
kubectl get pods -n fraudguard

# View service logs
kubectl logs -n fraudguard -l app.kubernetes.io/name=risk-scorer

# Test service connectivity
kubectl exec -n fraudguard -it deployment/mcp-gateway -- curl http://risk-scorer:8080/healthz
```

## 📄 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.