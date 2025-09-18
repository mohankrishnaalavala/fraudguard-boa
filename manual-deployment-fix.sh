#!/bin/bash
# Manual deployment fix for RAG system

echo "=== Manual RAG System Deployment Fix ==="

# Get current commit (should be the one with RAG fixes)
SHA=$(git rev-parse --short HEAD)
echo "Deploying commit SHA: $SHA"

# Step 1: Build images with explicit SHA tags
echo "=== Step 1: Building Docker Images ==="
echo "Building risk-scorer with RAG fixes..."
docker build -t us-docker.pkg.dev/fraudguard-hackathon/fraudguard/risk-scorer:$SHA services/risk-scorer/

echo "Building boa-monitor with account endpoint..."
docker build -t us-docker.pkg.dev/fraudguard-hackathon/fraudguard/boa-monitor:$SHA services/boa-monitor/

# Step 2: Push images to registry
echo "=== Step 2: Pushing Images ==="
docker push us-docker.pkg.dev/fraudguard-hackathon/fraudguard/risk-scorer:$SHA
docker push us-docker.pkg.dev/fraudguard-hackathon/fraudguard/boa-monitor:$SHA

# Step 3: Update Kubernetes deployments
echo "=== Step 3: Updating Kubernetes Deployments ==="

# Update risk-scorer deployment
kubectl -n fraudguard set image deployment/risk-scorer workload=us-docker.pkg.dev/fraudguard-hackathon/fraudguard/risk-scorer:$SHA

# Update boa-monitor deployment  
kubectl -n fraudguard set image deployment/boa-monitor-workload workload=us-docker.pkg.dev/fraudguard-hackathon/fraudguard/boa-monitor:$SHA

# Step 4: Wait for rollouts to complete
echo "=== Step 4: Waiting for Rollouts ==="
kubectl -n fraudguard rollout status deployment/risk-scorer --timeout=300s
kubectl -n fraudguard rollout status deployment/boa-monitor-workload --timeout=300s

# Step 5: Verify deployment
echo "=== Step 5: Verifying Deployment ==="
echo "New pod status:"
kubectl -n fraudguard get pods | grep -E "(risk-scorer|boa-monitor)"

echo "Deployed images:"
echo "risk-scorer: $(kubectl -n fraudguard get deploy risk-scorer -o jsonpath='{.spec.template.spec.containers[0].image}')"
echo "boa-monitor: $(kubectl -n fraudguard get deploy boa-monitor-workload -o jsonpath='{.spec.template.spec.containers[0].image}')"

# Step 6: Test the fixed RAG system
echo "=== Step 6: Testing RAG System ==="

# Port-forward to services
kubectl -n fraudguard port-forward svc/mcp-gateway 18081:8080 &
MCP_PID=$!
kubectl -n fraudguard port-forward svc/boa-monitor-workload 18082:8080 &
BOA_PID=$!
sleep 5

# Test BoA monitor new endpoint
echo "Testing BoA monitor /transactions endpoint..."
curl -s "http://localhost:18082/transactions/1033623433?limit=5" | head -c 200 || echo "BoA endpoint test failed"

# Create test transactions to verify recipient recognition
ACCOUNT="test-rag-fix"
RECIPIENT="acct:1033623433"

echo "Creating test transactions to verify RAG fixes..."
for i in 1 2 3; do
  TXN_ID="rag-fix-test-$i-$SHA"
  AMOUNT=$((150 + i * 25))
  NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  
  echo "Transaction $i: $TXN_ID (\$${AMOUNT} to $RECIPIENT)"
  
  curl -s -X POST http://localhost:18081/api/transactions \
    -H "Content-Type: application/json" \
    -d "{\"transaction_id\":\"$TXN_ID\",\"amount\":$AMOUNT,\"merchant\":\"$RECIPIENT\",\"user_id\":\"$ACCOUNT\",\"timestamp\":\"$NOW\"}" > /dev/null
  
  sleep 8  # Allow time for risk analysis
done

# Check for pattern signals in logs
echo "=== Checking risk-scorer logs for pattern signals ==="
kubectl -n fraudguard logs deploy/risk-scorer --tail=30 | grep -E "(pattern_signals|known_recipient|recipient_key)" || echo "No pattern signals found yet"

# Check recent transactions for improved AI analysis
echo "=== Checking recent transactions ==="
curl -s http://localhost:18081/api/recent-transactions | jq '.transactions[:3] | .[] | {transaction_id, merchant, amount, risk_explanation}' 2>/dev/null || echo "API response check failed"

# Cleanup
kill $MCP_PID $BOA_PID 2>/dev/null || true

echo "=== Manual Deployment Fix Complete ==="
echo "Expected behavior:"
echo "- Transaction 1 to $RECIPIENT: 'New recipient' (correct)"
echo "- Transaction 2 to $RECIPIENT: 'Known recipient' (should be fixed)"
echo "- Transaction 3 to $RECIPIENT: 'Known recipient' (should be fixed)"
