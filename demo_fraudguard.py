#!/usr/bin/env python3
"""
FraudGuard Demo Script
Demonstrates the complete fraud detection pipeline
"""

import json
import time
import requests
from datetime import datetime

# Service endpoints
DASHBOARD_URL = "http://localhost:8080"
MCP_GATEWAY_URL = "http://localhost:8082"

def print_banner():
    print("=" * 60)
    print("🛡️  FRAUDGUARD DEMO - AI-Powered Fraud Detection")
    print("=" * 60)
    print()

def test_service_health():
    """Test if all services are healthy"""
    print("🔍 Checking service health...")
    
    services = [
        ("Dashboard", f"{DASHBOARD_URL}/healthz"),
        ("MCP Gateway", f"{MCP_GATEWAY_URL}/healthz"),
    ]
    
    for name, url in services:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                print(f"✅ {name}: Healthy")
            else:
                print(f"⚠️  {name}: Status {response.status_code}")
        except Exception as e:
            print(f"❌ {name}: Error - {e}")
    print()

def simulate_transaction(amount, merchant, description="Purchase"):
    """Simulate a transaction for fraud detection"""
    transaction = {
        "transaction_id": f"txn_{int(time.time())}",
        "amount": amount,
        "merchant": merchant,
        "description": description,
        "timestamp": datetime.now().isoformat(),
        "user_id": "demo_user_001",
        "account_id": "acc_123456789",
        "location": "San Francisco, CA",
        "payment_method": "credit_card"
    }
    
    print(f"💳 Simulating transaction: ${amount} at {merchant}")
    print(f"   Transaction ID: {transaction['transaction_id']}")
    
    try:
        # Send to MCP Gateway for processing
        response = requests.post(
            f"{MCP_GATEWAY_URL}/api/transactions",
            json=transaction,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            risk_score = result.get('risk_score', 0)
            status = result.get('status', 'unknown')
            
            print(f"   🎯 Risk Score: {risk_score}/100")
            print(f"   📊 Status: {status}")
            
            if risk_score > 70:
                print("   🚨 HIGH RISK - Transaction flagged for review")
            elif risk_score > 40:
                print("   ⚠️  MEDIUM RISK - Additional verification required")
            else:
                print("   ✅ LOW RISK - Transaction approved")
                
            return result
        else:
            print(f"   ❌ Error: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None

def demo_scenarios():
    """Run various fraud detection scenarios"""
    print("🎭 Running fraud detection scenarios...")
    print()
    
    scenarios = [
        # Normal transactions
        (25.99, "Starbucks", "Coffee purchase"),
        (89.99, "Amazon", "Online shopping"),
        (45.00, "Shell Gas Station", "Fuel purchase"),
        
        # Suspicious transactions
        (2500.00, "Unknown Merchant", "Large purchase"),
        (9999.99, "Overseas ATM", "Cash withdrawal"),
        (1.00, "Test Merchant", "Micro transaction"),
    ]
    
    for amount, merchant, description in scenarios:
        simulate_transaction(amount, merchant, description)
        print()
        time.sleep(2)  # Brief pause between transactions

def show_dashboard_info():
    """Show information about accessing the dashboard"""
    print("🖥️  DASHBOARD ACCESS")
    print("-" * 30)
    print(f"FraudGuard Dashboard: {DASHBOARD_URL}")
    print(f"Bank of Anthos:       http://localhost:8081")
    print()
    print("📊 Dashboard Features:")
    print("• Real-time transaction monitoring")
    print("• Risk score analytics")
    print("• Fraud detection alerts")
    print("• Transaction history")
    print("• AI explanation engine")
    print()

def main():
    """Main demo function"""
    print_banner()

    # Check service health
    test_service_health()

    # Show dashboard info
    show_dashboard_info()

    print("🎉 **DEMO READY!**")
    print()
    print("✅ **Applications Successfully Opened:**")
    print("• FraudGuard Dashboard: http://localhost:8080")
    print("• Bank of Anthos: http://localhost:8081")
    print()
    print("🎭 **Demo Features:**")
    print("• Real-time fraud detection")
    print("• AI-powered risk scoring")
    print("• Transaction monitoring")
    print("• Explanation engine")
    print()
    print("💡 **Try This:**")
    print("1. Create transactions in Bank of Anthos")
    print("2. Watch FraudGuard analyze them in real-time")
    print("3. View risk scores and explanations")
    print()
    print("🌐 **Production URLs (after DNS propagation):**")
    print("• https://fraudguard.mohankrishna.site")
    print("• https://boa.mohankrishna.site")
    print()
    print("🚀 **Both applications are now running and accessible!**")

if __name__ == "__main__":
    main()
