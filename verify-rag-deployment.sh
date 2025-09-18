#!/bin/bash

echo "=== RAG System Deployment Verification ==="

# Check deployment status
echo "1. Current pod status:"
kubectl -n fraudguard get pods | grep -E "(risk-scorer|boa-monitor)"

echo -e "\n2. Deployed images:"
echo "risk-scorer: $(kubectl -n fraudguard get deploy risk-scorer -o jsonpath='{.spec.template.spec.containers[0].image}')"
echo "boa-monitor: $(kubectl -n fraudguard get deploy boa-monitor-workload -o jsonpath='{.spec.template.spec.containers[0].image}')"

echo -e "\n3. Testing BoA monitor endpoint..."
kubectl -n fraudguard port-forward svc/boa-monitor-workload 18082:8080 &
BOA_PID=$!
sleep 3

# Test health endpoint
echo "Health check:"
curl -s "http://localhost:18082/healthz" || echo "Health check failed"

# Test transactions endpoint
echo -e "\nTransactions endpoint test:"
curl -s "http://localhost:18082/transactions/1033623433?limit=2" | head -c 200 || echo "Transactions endpoint failed"

kill $BOA_PID 2>/dev/null || true

echo -e "\n\n4. Recent risk-scorer logs:"
kubectl -n fraudguard logs deploy/risk-scorer --tail=10 | head -20

echo -e "\n=== Verification Complete ==="
echo "Expected: Both services should be running with image tag 4a55409"
echo "Expected: BoA monitor should respond to /transactions/{account_id} endpoint"
echo "Expected: Risk-scorer should have RAG fixes for recipient recognition"
