#!/bin/bash

echo "=== Testing Enhanced RAG System with Historical Intelligence ==="

# Port-forward to services
kubectl -n fraudguard port-forward svc/mcp-gateway 18081:8080 &
MCP_PID=$!
sleep 5

ACCOUNT="test-enhanced-rag"
RECIPIENT="acct:1055757655"

echo "=== Test Scenario: Multiple transactions to same recipient ==="
echo "Account: $ACCOUNT"
echo "Recipient: $RECIPIENT"
echo ""

# Create first transaction (should be "new recipient")
echo "1. Creating first transaction (\$200 to $RECIPIENT)..."
TXN1_ID="enhanced-rag-1-$(date +%s)"
curl -s -X POST http://localhost:18081/api/transactions \
  -H "Content-Type: application/json" \
  -d "{\"transaction_id\":\"$TXN1_ID\",\"amount\":200,\"merchant\":\"$RECIPIENT\",\"user_id\":\"$ACCOUNT\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > /dev/null

echo "Waiting for risk analysis..."
sleep 10

# Create second transaction (should recognize as "known recipient")
echo "2. Creating second transaction (\$250 to $RECIPIENT)..."
TXN2_ID="enhanced-rag-2-$(date +%s)"
curl -s -X POST http://localhost:18081/api/transactions \
  -H "Content-Type: application/json" \
  -d "{\"transaction_id\":\"$TXN2_ID\",\"amount\":250,\"merchant\":\"$RECIPIENT\",\"user_id\":\"$ACCOUNT\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > /dev/null

echo "Waiting for risk analysis..."
sleep 10

# Create third transaction with significant deviation (should flag as suspicious)
echo "3. Creating third transaction (\$1000 to $RECIPIENT - 4x higher)..."
TXN3_ID="enhanced-rag-3-$(date +%s)"
curl -s -X POST http://localhost:18081/api/transactions \
  -H "Content-Type: application/json" \
  -d "{\"transaction_id\":\"$TXN3_ID\",\"amount\":1000,\"merchant\":\"$RECIPIENT\",\"user_id\":\"$ACCOUNT\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > /dev/null

echo "Waiting for risk analysis..."
sleep 10

echo "=== Checking Risk-Scorer Logs for Historical Intelligence ==="
kubectl -n fraudguard logs deploy/risk-scorer --tail=30 | grep -E "(pattern_signals|known_recipient|HISTORICAL|ACCOUNT)" | tail -10

echo ""
echo "=== Checking Recent Transactions for AI Analysis ==="
curl -s http://localhost:18081/api/recent-transactions | jq '.transactions[:3] | .[] | {transaction_id, merchant, amount, risk_score, risk_explanation}' 2>/dev/null | head -30

echo ""
echo "=== Expected Results ==="
echo "Transaction 1 ($TXN1_ID): Should show 'New recipient' or 'First transaction'"
echo "Transaction 2 ($TXN2_ID): Should show 'Known recipient' with reference to \$200 typical amount"
echo "Transaction 3 ($TXN3_ID): Should show 'Known recipient, \$1000 is 4x higher than typical \$225' or similar intelligent analysis"

# Cleanup
kill $MCP_PID 2>/dev/null || true

echo ""
echo "=== Enhanced RAG Test Complete ==="
echo "Check the AI explanations above to verify historical intelligence is working."
