#!/bin/bash

# Setup External Access for FraudGuard and Bank of Anthos
# This script creates LoadBalancer services to expose applications via external IPs

set -e

echo "🌐 Setting up External Access for FraudGuard..."

# Set up environment
export PATH="/usr/local/share/google-cloud-sdk/bin:$PATH"
export USE_GKE_GCLOUD_AUTH_PLUGIN=True

# Deploy external LoadBalancer services
echo "📦 Deploying LoadBalancer services..."
kubectl apply -f k8s/external-services.yaml

echo "⏳ Waiting for LoadBalancer IPs to be assigned..."
echo "This may take 2-3 minutes..."

# Wait for external IPs to be assigned
echo "🔍 Checking FraudGuard Dashboard external IP..."
kubectl wait --for=jsonpath='{.status.loadBalancer.ingress}' service/fraudguard-dashboard-external -n fraudguard --timeout=300s

echo "🔍 Checking FraudGuard API external IP..."
kubectl wait --for=jsonpath='{.status.loadBalancer.ingress}' service/fraudguard-api-external -n fraudguard --timeout=300s

echo "🔍 Checking Bank of Anthos external IP..."
kubectl wait --for=jsonpath='{.status.loadBalancer.ingress}' service/bank-of-anthos-external -n boa --timeout=300s

echo ""
echo "✅ External IPs assigned! Here are your access URLs:"
echo ""

# Get and display external IPs
DASHBOARD_IP=$(kubectl get svc fraudguard-dashboard-external -n fraudguard -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
API_IP=$(kubectl get svc fraudguard-api-external -n fraudguard -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
BOA_IP=$(kubectl get svc bank-of-anthos-external -n boa -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

echo "🛡️  FraudGuard Dashboard: http://$DASHBOARD_IP/"
echo "🔌 FraudGuard API:       http://$API_IP/api/"
echo "🏦 Bank of Anthos:       http://$BOA_IP/"
echo ""

# Test the endpoints
echo "🧪 Testing endpoints..."

if curl -s -f "http://$DASHBOARD_IP/healthz" > /dev/null; then
    echo "✅ FraudGuard Dashboard is accessible"
else
    echo "⚠️  FraudGuard Dashboard health check failed"
fi

if curl -s -f "http://$API_IP/healthz" > /dev/null; then
    echo "✅ FraudGuard API is accessible"
else
    echo "⚠️  FraudGuard API health check failed"
fi

if curl -s -f "http://$BOA_IP/" > /dev/null; then
    echo "✅ Bank of Anthos is accessible"
else
    echo "⚠️  Bank of Anthos health check failed"
fi

echo ""
echo "🎉 External access setup complete!"
echo ""
echo "📝 Save these URLs for easy access:"
echo "   FraudGuard: http://$DASHBOARD_IP/"
echo "   Bank of Anthos: http://$BOA_IP/"
echo ""
echo "🔧 To remove external access later:"
echo "   kubectl delete -f k8s/external-services.yaml"
