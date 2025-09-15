# 🧪 FraudGuard Manual Testing Guide

## 🎯 **Current Status**
- ✅ **Bank of Anthos**: Fully working at `http://localhost:8081`
- ✅ **FraudGuard Services**: All 6 microservices running in Kubernetes
- ⚠️ **Dashboard**: Template issue (being fixed)

## 🏦 **Bank of Anthos Testing (Working)**

### **Access**: `http://localhost:8081`

### **Test Scenarios**:

#### 1. **Create User Account**
- Click "Sign Up" 
- Create username: `testuser`
- Password: `password123`
- Email: `test@example.com`

#### 2. **Login & Explore**
- Login with created credentials
- View account balance
- Check transaction history

#### 3. **Make Transactions**
- Transfer money between accounts
- Try different amounts:
  - Small: $25 (Normal)
  - Medium: $500 (Medium Risk)
  - Large: $5000 (High Risk)

#### 4. **Test Different Patterns**
- Multiple rapid transactions
- Late night transactions
- Cross-account transfers

## 🛡️ **FraudGuard API Testing**

### **MCP Gateway**: `http://localhost:8082`

#### Test Health Check:
```bash
curl http://localhost:8082/healthz
```

#### Test Transaction Analysis:
```bash
curl -X POST http://localhost:8082/api/transactions \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "test_001",
    "amount": 1000,
    "merchant": "Test Store",
    "user_id": "test_user",
    "timestamp": "2025-09-14T18:00:00Z"
  }'
```

### **Individual Services**:

#### Risk Scorer:
```bash
kubectl port-forward -n fraudguard svc/risk-scorer 8083:8080
curl http://localhost:8083/healthz
```

#### Explain Agent:
```bash
kubectl port-forward -n fraudguard svc/explain-agent 8084:8080
curl http://localhost:8084/healthz
```

## 🎭 **Demo Workflow**

### **Step 1: Show Bank of Anthos**
1. Open `http://localhost:8081`
2. Create account and login
3. Show normal banking features

### **Step 2: Create Transactions**
1. Make a normal transaction ($50)
2. Make a suspicious transaction ($5000)
3. Make rapid multiple transactions

### **Step 3: Show FraudGuard Analysis**
1. Check MCP Gateway logs:
   ```bash
   kubectl logs -n fraudguard -l app=mcp-gateway --tail=20
   ```

2. Check Risk Scorer analysis:
   ```bash
   kubectl logs -n fraudguard -l app=risk-scorer --tail=20
   ```

3. Show explain-agent records:
   ```bash
   kubectl logs -n fraudguard -l app=explain-agent --tail=20
   ```

## 🔧 **Service Architecture**

```
Bank of Anthos → MCP Gateway → Transaction Watcher
                      ↓
                 Risk Scorer (Gemini AI)
                      ↓
                 Explain Agent → Action Orchestrator
                      ↓
                 Dashboard (UI)
```

## 📊 **Key Features Demonstrated**

1. **Real-time Monitoring**: Services detect transactions immediately
2. **AI Risk Scoring**: Gemini-powered analysis (mock implementation)
3. **Audit Trail**: Complete transaction history with explanations
4. **Action Orchestration**: Automated responses based on risk levels
5. **Microservices**: Scalable, secure Kubernetes deployment

## 🌐 **Production URLs**
Once DNS propagates (24-48 hours):
- **FraudGuard**: `https://fraudguard.mohankrishna.site`
- **Bank of Anthos**: `https://boa.mohankrishna.site`

## 🚀 **Next Steps**
1. Fix dashboard template caching issue
2. Add real Gemini AI integration
3. Implement real-time WebSocket updates
4. Add more sophisticated fraud patterns
