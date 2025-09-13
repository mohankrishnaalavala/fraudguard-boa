# FraudGuard Makefile
# Convenience targets for development and deployment

.PHONY: help demo install-helm deploy-all deploy-service clean lint test

# Default target
help:
	@echo "FraudGuard Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  demo           - Run demo script to seed test transactions"
	@echo "  install-helm   - Install all services using Helm"
	@echo "  deploy-all     - Deploy all FraudGuard services"
	@echo "  deploy-service - Deploy a specific service (use SERVICE=name)"
	@echo "  clean          - Remove all deployments"
	@echo "  lint           - Run linting on all Python services"
	@echo "  test           - Run tests for all services"
	@echo "  build          - Build all Docker images"
	@echo ""
	@echo "Examples:"
	@echo "  make demo"
	@echo "  make deploy-service SERVICE=mcp-gateway"
	@echo "  make install-helm NAMESPACE=fraudguard"

# Configuration
NAMESPACE ?= fraudguard
HELM_CHART = ./helm/workload
SERVICES = mcp-gateway txn-watcher risk-scorer explain-agent action-orchestrator dashboard

# Run demo script
demo:
	@echo "🚀 Running FraudGuard demo..."
	./scripts/make_demo.sh

# Install all services using Helm
install-helm:
	@echo "📦 Installing all FraudGuard services..."
	@for service in $(SERVICES); do \
		echo "Installing $$service..."; \
		helm upgrade --install $$service $(HELM_CHART) \
			-n $(NAMESPACE) --create-namespace \
			-f values/$$service.yaml; \
	done
	@echo "✅ All services installed!"

# Deploy all services
deploy-all: install-helm
	@echo "🚀 All services deployed to namespace: $(NAMESPACE)"

# Deploy a specific service
deploy-service:
	@if [ -z "$(SERVICE)" ]; then \
		echo "❌ Please specify SERVICE=<service-name>"; \
		echo "Available services: $(SERVICES)"; \
		exit 1; \
	fi
	@echo "📦 Deploying $(SERVICE)..."
	helm upgrade --install $(SERVICE) $(HELM_CHART) \
		-n $(NAMESPACE) --create-namespace \
		-f values/$(SERVICE).yaml
	@echo "✅ $(SERVICE) deployed!"

# Clean up all deployments
clean:
	@echo "🧹 Cleaning up FraudGuard deployments..."
	@for service in $(SERVICES); do \
		echo "Uninstalling $$service..."; \
		helm uninstall $$service -n $(NAMESPACE) || true; \
	done
	@echo "✅ Cleanup complete!"

# Lint Python code
lint:
	@echo "🔍 Running linting..."
	@for service in mcp-gateway txn-watcher risk-scorer explain-agent action-orchestrator; do \
		echo "Linting services/$$service..."; \
		cd services/$$service && python -m ruff check . && python -m black --check .; \
		cd ../..; \
	done
	@echo "Linting web/dashboard..."
	@cd web/dashboard && python -m ruff check . && python -m black --check .
	@echo "✅ Linting complete!"

# Run tests
test:
	@echo "🧪 Running tests..."
	@for service in mcp-gateway txn-watcher risk-scorer explain-agent action-orchestrator; do \
		if [ -f "services/$$service/test_main.py" ]; then \
			echo "Testing services/$$service..."; \
			cd services/$$service && python -m pytest test_main.py -v; \
			cd ../..; \
		fi; \
	done
	@if [ -f "web/dashboard/test_app.py" ]; then \
		echo "Testing web/dashboard..."; \
		cd web/dashboard && python -m pytest test_app.py -v; \
	fi
	@echo "✅ Tests complete!"

# Build Docker images
build:
	@echo "🐳 Building Docker images..."
	@for service in $(SERVICES); do \
		if [ "$$service" = "dashboard" ]; then \
			echo "Building $$service..."; \
			docker build -t fraudguard/$$service:dev web/dashboard/; \
		else \
			echo "Building $$service..."; \
			docker build -t fraudguard/$$service:dev services/$$service/; \
		fi; \
	done
	@echo "✅ All images built!"

# Check service health
health:
	@echo "🏥 Checking service health..."
	@kubectl get pods -n $(NAMESPACE) -l app.kubernetes.io/managed-by=Helm
	@echo ""
	@for service in $(SERVICES); do \
		echo "Checking $$service health..."; \
		kubectl port-forward -n $(NAMESPACE) svc/$$service 8080:8080 & \
		sleep 2; \
		curl -s http://localhost:8080/healthz || echo "❌ $$service unhealthy"; \
		pkill -f "kubectl port-forward.*$$service" || true; \
	done

# Show service logs
logs:
	@if [ -z "$(SERVICE)" ]; then \
		echo "❌ Please specify SERVICE=<service-name>"; \
		echo "Available services: $(SERVICES)"; \
		exit 1; \
	fi
	@echo "📋 Showing logs for $(SERVICE)..."
	kubectl logs -n $(NAMESPACE) -l app.kubernetes.io/name=$(SERVICE) --tail=100 -f
