#!/bin/bash
set -euo pipefail

echo "=== RAG System Deployment Verification and Fix ==="

# Get current commit SHA
SHA=$(git rev-parse --short HEAD)
echo "Current commit SHA: $SHA"

# Check current pod status
echo "=== Current Pod Status ==="
kubectl -n fraudguard get pods | grep -E "(risk-scorer|boa-monitor)"

# Check current deployed images
echo "=== Current Deployed Images ==="
echo "risk-scorer image:"
kubectl -n fraudguard get deploy risk-scorer -o jsonpath="{.spec.template.spec.containers[0].image}"
echo ""

echo "boa-monitor image:"
kubectl -n fraudguard get deploy boa-monitor-workload -o jsonpath="{.spec.template.spec.containers[0].image}"
echo ""

# Build and push updated images
echo "=== Building Updated Images ==="
echo "Building risk-scorer:$SHA..."
docker build -t us-docker.pkg.dev/fraudguard-hackathon/fraudguard/risk-scorer:$SHA services/risk-scorer/

echo "Building boa-monitor:$SHA..."
docker build -t us-docker.pkg.dev/fraudguard-hackathon/fraudguard/boa-monitor:$SHA services/boa-monitor/

echo "=== Pushing Images ==="
docker push us-docker.pkg.dev/fraudguard-hackathon/fraudguard/risk-scorer:$SHA
docker push us-docker.pkg.dev/fraudguard-hackathon/fraudguard/boa-monitor:$SHA

# Update deployments
echo "=== Updating Deployments ==="
kubectl -n fraudguard set image deployment/risk-scorer workload=us-docker.pkg.dev/fraudguard-hackathon/fraudguard/risk-scorer:$SHA
kubectl -n fraudguard set image deployment/boa-monitor-workload workload=us-docker.pkg.dev/fraudguard-hackathon/fraudguard/boa-monitor:$SHA

# Wait for rollouts
echo "=== Waiting for Rollouts ==="
kubectl -n fraudguard rollout status deployment/risk-scorer --timeout=300s
kubectl -n fraudguard rollout status deployment/boa-monitor-workload --timeout=300s

# Verify new pods
echo "=== New Pod Status ==="
kubectl -n fraudguard get pods | grep -E "(risk-scorer|boa-monitor)"

# Test the RAG system
echo "=== Testing RAG System ==="

# Port-forward to services
kubectl -n fraudguard port-forward svc/mcp-gateway 18081:8080 &
MCP_PID=$!
kubectl -n fraudguard port-forward svc/boa-monitor-workload 18082:8080 &
BOA_PID=$!
sleep 5

# Test BoA monitor endpoint
echo "Testing BoA monitor endpoint..."
curl -s http://localhost:18082/healthz | head -c 100 || echo "BoA monitor health check failed"

# Create test transactions to same recipient
ACCOUNT="test-rag-user"
RECIPIENT="acct:1033623433"

echo "Creating test transactions to $RECIPIENT..."
for i in 1 2 3; do
  TXN_ID="rag-test-$i-$SHA"
  AMOUNT=$((100 + i * 50))
  NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  
  echo "Creating transaction $TXN_ID: \$${AMOUNT} to $RECIPIENT"
  
  curl -s -X POST http://localhost:18081/api/transactions \
    -H "Content-Type: application/json" \
    -d "{\"transaction_id\":\"$TXN_ID\",\"amount\":$AMOUNT,\"merchant\":\"$RECIPIENT\",\"user_id\":\"$ACCOUNT\",\"timestamp\":\"$NOW\"}" | head -c 200
  
  echo ""
  sleep 5  # Allow time for risk analysis
done

# Check risk-scorer logs for pattern signals
echo "=== Risk-scorer logs (pattern signals) ==="
kubectl -n fraudguard logs deploy/risk-scorer --tail=20 | grep -E "(pattern_signals|known_recipient|recipient_key)" || echo "No pattern signals found"

# Check recent transactions
echo "=== Recent transactions with AI analysis ==="
curl -s http://localhost:18081/api/recent-transactions | jq '.transactions[:3] | .[] | {transaction_id, merchant, amount, risk_explanation}' || echo "API failed"

# Cleanup
kill $MCP_PID $BOA_PID 2>/dev/null || true

echo "=== RAG System Test Complete ==="
