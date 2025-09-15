#!/bin/bash

# 🚀 FraudGuard Demo Startup Script
# This script sets up reliable port forwards and tests the complete system

set -e

echo "🚀 Starting FraudGuard Demo Environment..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE_FRAUDGUARD="fraudguard"
NAMESPACE_BOA="boa"
DASHBOARD_PORT=8080
BOA_PORT=8081
MCP_GATEWAY_PORT=8082

# Function to check if port is in use
check_port() {
    local port=$1
    if lsof -i :$port > /dev/null 2>&1; then
        echo -e "${YELLOW}Port $port is already in use. Killing existing process...${NC}"
        lsof -ti :$port | xargs kill -9 2>/dev/null || true
        sleep 2
    fi
}

# Function to wait for port forward to be ready
wait_for_port() {
    local port=$1
    local service_name=$2
    local max_attempts=30
    local attempt=1
    
    echo -e "${BLUE}Waiting for $service_name on port $port...${NC}"
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s http://localhost:$port/healthz > /dev/null 2>&1; then
            echo -e "${GREEN}✅ $service_name is ready on port $port${NC}"
            return 0
        fi
        
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo -e "${RED}❌ $service_name failed to start on port $port${NC}"
    return 1
}

# Function to setup port forward
setup_port_forward() {
    local namespace=$1
    local service=$2
    local local_port=$3
    local remote_port=$4
    local service_name=$5
    
    echo -e "${BLUE}Setting up port forward for $service_name...${NC}"
    
    # Kill any existing port forward on this port
    check_port $local_port
    
    # Start port forward in background
    kubectl port-forward -n $namespace svc/$service $local_port:$remote_port > /dev/null 2>&1 &
    local pf_pid=$!
    
    # Store PID for cleanup
    echo $pf_pid >> /tmp/fraudguard_pids.txt
    
    # Wait for port forward to be ready
    sleep 3
    
    return 0
}

# Cleanup function
cleanup() {
    echo -e "${YELLOW}🧹 Cleaning up port forwards...${NC}"
    if [ -f /tmp/fraudguard_pids.txt ]; then
        while read pid; do
            kill $pid 2>/dev/null || true
        done < /tmp/fraudguard_pids.txt
        rm -f /tmp/fraudguard_pids.txt
    fi
    
    # Kill any kubectl port-forward processes
    pkill -f "kubectl port-forward" 2>/dev/null || true
}

# Set up cleanup on script exit
trap cleanup EXIT

# Check prerequisites
echo -e "${BLUE}🔍 Checking prerequisites...${NC}"

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}❌ kubectl is not installed${NC}"
    exit 1
fi

if ! command -v curl &> /dev/null; then
    echo -e "${RED}❌ curl is not installed${NC}"
    exit 1
fi

# Check cluster connection
if ! kubectl cluster-info > /dev/null 2>&1; then
    echo -e "${RED}❌ Cannot connect to Kubernetes cluster${NC}"
    echo -e "${YELLOW}Please run: gcloud container clusters get-credentials fraudguard-auto --region us-central1${NC}"
    exit 1
fi

# Check if namespaces exist
if ! kubectl get namespace $NAMESPACE_FRAUDGUARD > /dev/null 2>&1; then
    echo -e "${RED}❌ Namespace $NAMESPACE_FRAUDGUARD does not exist${NC}"
    exit 1
fi

if ! kubectl get namespace $NAMESPACE_BOA > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Namespace $NAMESPACE_BOA does not exist. Bank of Anthos may not be deployed.${NC}"
fi

# Check if pods are running
echo -e "${BLUE}📊 Checking pod status...${NC}"
kubectl get pods -n $NAMESPACE_FRAUDGUARD

# Initialize PID tracking file
rm -f /tmp/fraudguard_pids.txt
touch /tmp/fraudguard_pids.txt

# Setup port forwards
echo -e "${BLUE}🔗 Setting up port forwards...${NC}"

setup_port_forward $NAMESPACE_FRAUDGUARD dashboard $DASHBOARD_PORT 8080 "FraudGuard Dashboard"
setup_port_forward $NAMESPACE_FRAUDGUARD mcp-gateway $MCP_GATEWAY_PORT 8080 "MCP Gateway"

if kubectl get namespace $NAMESPACE_BOA > /dev/null 2>&1; then
    setup_port_forward $NAMESPACE_BOA frontend $BOA_PORT 80 "Bank of Anthos"
fi

# Wait for services to be ready
echo -e "${BLUE}⏳ Waiting for services to be ready...${NC}"

wait_for_port $DASHBOARD_PORT "FraudGuard Dashboard"
wait_for_port $MCP_GATEWAY_PORT "MCP Gateway"

if kubectl get namespace $NAMESPACE_BOA > /dev/null 2>&1; then
    if curl -s http://localhost:$BOA_PORT/ | grep -q "Bank of Anthos" 2>/dev/null; then
        echo -e "${GREEN}✅ Bank of Anthos is ready on port $BOA_PORT${NC}"
    else
        echo -e "${YELLOW}⚠️  Bank of Anthos may not be fully ready${NC}"
    fi
fi

# Test the complete system
echo -e "${BLUE}🧪 Testing AI-powered fraud detection...${NC}"

# Create test transactions
echo -e "${BLUE}Creating test transactions...${NC}"

# High-risk transaction
curl -X POST http://localhost:$MCP_GATEWAY_PORT/api/transactions \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "demo_high_risk_'$(date +%s)'",
    "amount": 4500,
    "merchant": "Suspicious Cash ATM",
    "user_id": "demo_user",
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }' > /dev/null 2>&1

# Low-risk transaction
curl -X POST http://localhost:$MCP_GATEWAY_PORT/api/transactions \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "demo_low_risk_'$(date +%s)'",
    "amount": 12.50,
    "merchant": "Local Coffee Shop",
    "user_id": "demo_user",
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }' > /dev/null 2>&1

sleep 3

# Check if transactions were processed
if curl -s "http://localhost:$MCP_GATEWAY_PORT/api/recent-transactions?limit=5" | grep -q "demo_" 2>/dev/null; then
    echo -e "${GREEN}✅ AI transaction processing is working${NC}"
else
    echo -e "${YELLOW}⚠️  Transaction processing may need verification${NC}"
fi

# Display final status
echo ""
echo -e "${GREEN}🎉 FraudGuard Demo Environment is Ready!${NC}"
echo ""
echo -e "${BLUE}📱 Access URLs:${NC}"
echo -e "  🛡️  FraudGuard Dashboard: ${GREEN}http://localhost:$DASHBOARD_PORT${NC}"
echo -e "  🏦 Bank of Anthos:       ${GREEN}http://localhost:$BOA_PORT${NC}"
echo -e "  🔌 MCP Gateway API:      ${GREEN}http://localhost:$MCP_GATEWAY_PORT${NC}"
echo ""
echo -e "${BLUE}🧪 Test Commands:${NC}"
echo -e "  Health Check: ${YELLOW}curl http://localhost:$DASHBOARD_PORT/healthz${NC}"
echo -e "  Create Transaction: ${YELLOW}curl -X POST http://localhost:$MCP_GATEWAY_PORT/api/transactions -H 'Content-Type: application/json' -d '{\"transaction_id\":\"test_001\",\"amount\":1000,\"merchant\":\"Test Store\",\"user_id\":\"test_user\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}' ${NC}"
echo ""
echo -e "${YELLOW}💡 Tip: Keep this terminal open to maintain port forwards${NC}"
echo -e "${YELLOW}💡 Press Ctrl+C to stop all port forwards and exit${NC}"
echo ""

# Keep the script running to maintain port forwards
echo -e "${BLUE}🔄 Port forwards are active. Press Ctrl+C to stop...${NC}"
while true; do
    sleep 30
    # Check if port forwards are still alive
    if ! curl -s http://localhost:$DASHBOARD_PORT/healthz > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Dashboard port forward may have died. Restarting...${NC}"
        setup_port_forward $NAMESPACE_FRAUDGUARD dashboard $DASHBOARD_PORT 8080 "FraudGuard Dashboard"
    fi
done
