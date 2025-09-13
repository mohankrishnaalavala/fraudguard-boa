#!/bin/bash

# FraudGuard Demo Script
# Seeds demo transactions for testing the fraud detection pipeline

set -euo pipefail

# Configuration
MCP_GATEWAY_URL="${MCP_GATEWAY_URL:-http://mcp-gateway.fraudguard.svc.cluster.local:8080}"
RISK_SCORER_URL="${RISK_SCORER_URL:-http://risk-scorer.fraudguard.svc.cluster.local:8080}"
DASHBOARD_URL="${DASHBOARD_URL:-http://dashboard.fraudguard.svc.cluster.local:8080}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}✅ $1${NC}"
}

warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check if services are available
check_service() {
    local service_name=$1
    local service_url=$2
    
    log "Checking $service_name at $service_url"
    
    if curl -s -f "$service_url/healthz" > /dev/null; then
        success "$service_name is healthy"
        return 0
    else
        error "$service_name is not available at $service_url"
        return 1
    fi
}

# Create a demo transaction
create_demo_transaction() {
    local transaction_data=$1
    local description=$2
    
    log "Creating demo transaction: $description"
    
    # Send transaction directly to risk scorer for analysis
    response=$(curl -s -X POST "$RISK_SCORER_URL/analyze" \
        -H "Content-Type: application/json" \
        -d "$transaction_data" || echo "ERROR")
    
    if [[ "$response" == "ERROR" ]]; then
        error "Failed to create transaction: $description"
        return 1
    else
        success "Created transaction: $description"
        echo "Response: $response"
        return 0
    fi
}

# Main demo function
run_demo() {
    log "🚀 Starting FraudGuard Demo"
    
    # Check service health
    log "Checking service health..."
    
    if ! check_service "Risk Scorer" "$RISK_SCORER_URL"; then
        error "Risk Scorer service is not available. Please ensure all services are deployed."
        exit 1
    fi
    
    if ! check_service "Dashboard" "$DASHBOARD_URL"; then
        warning "Dashboard service is not available, but continuing with demo"
    fi
    
    log "All required services are healthy!"
    
    # Create normal transaction
    log "Creating normal transaction..."
    normal_transaction='{
        "transaction_id": "demo_normal_001",
        "account_id": "acc_demo_001",
        "amount": 25.50,
        "merchant": "grocery_store",
        "category": "grocery",
        "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)'",
        "location": "San Francisco"
    }'
    
    create_demo_transaction "$normal_transaction" "Normal grocery purchase"
    
    sleep 2
    
    # Create suspicious transaction
    log "Creating suspicious transaction..."
    suspicious_transaction='{
        "transaction_id": "demo_suspicious_001",
        "account_id": "acc_demo_002",
        "amount": 1500.00,
        "merchant": "online_electronics",
        "category": "online",
        "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)'",
        "location": "Unknown"
    }'
    
    create_demo_transaction "$suspicious_transaction" "High-value online purchase"
    
    sleep 2
    
    # Create late-night transaction
    log "Creating late-night transaction..."
    late_night_transaction='{
        "transaction_id": "demo_latenight_001",
        "account_id": "acc_demo_003",
        "amount": 75.00,
        "merchant": "restaurant_bar",
        "category": "restaurant",
        "timestamp": "'$(date -u -d '22:30' +%Y-%m-%dT%H:%M:%S.%3NZ)'",
        "location": "Las Vegas"
    }'
    
    create_demo_transaction "$late_night_transaction" "Late-night restaurant transaction"
    
    success "Demo transactions created successfully!"
    
    log "🎯 Demo Summary:"
    echo "  • Normal transaction: Low risk grocery purchase"
    echo "  • Suspicious transaction: High-value online purchase"
    echo "  • Late-night transaction: Restaurant purchase at unusual hour"
    
    if curl -s -f "$DASHBOARD_URL/healthz" > /dev/null; then
        log "🌐 View results in the dashboard:"
        echo "  Dashboard URL: $DASHBOARD_URL"
        echo "  The dashboard will auto-refresh every 10 seconds"
    else
        warning "Dashboard is not available. Check service logs for transaction processing results."
    fi
    
    log "✨ Demo completed! Check the dashboard or service logs to see the fraud detection in action."
}

# Help function
show_help() {
    echo "FraudGuard Demo Script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  --mcp-gateway URL       Override MCP Gateway URL"
    echo "  --risk-scorer URL       Override Risk Scorer URL"
    echo "  --dashboard URL         Override Dashboard URL"
    echo ""
    echo "Environment Variables:"
    echo "  MCP_GATEWAY_URL         MCP Gateway service URL"
    echo "  RISK_SCORER_URL         Risk Scorer service URL"
    echo "  DASHBOARD_URL           Dashboard service URL"
    echo ""
    echo "Examples:"
    echo "  $0                      Run demo with default URLs"
    echo "  $0 --dashboard http://localhost:8080"
    echo "  MCP_GATEWAY_URL=http://localhost:8081 $0"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        --mcp-gateway)
            MCP_GATEWAY_URL="$2"
            shift 2
            ;;
        --risk-scorer)
            RISK_SCORER_URL="$2"
            shift 2
            ;;
        --dashboard)
            DASHBOARD_URL="$2"
            shift 2
            ;;
        *)
            error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Run the demo
run_demo
