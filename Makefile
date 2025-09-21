# LedgerFlux Market Data Fan-Out System

# Defaults
NAMESPACE ?= ledgerflux
K8S_DIR ?= k8s

.PHONY: help install lint typecheck test compose-up compose-down clean

# Default target
help:
	@echo "LedgerFlux Market Data Fan-Out System"
	@echo "====================================="
	@echo ""
	@echo "Available targets:"
	@echo "  install       - Install dependencies"
	@echo "  lint          - Run linting"
	@echo "  typecheck     - Run type checking"
	@echo "  test          - Run tests"
	@echo "  compose-up    - Start infrastructure services"
	@echo "  compose-down  - Stop infrastructure services"
	@echo "  clean         - Clean up temporary files"
	@echo ""
	@echo "Service targets:"
	@echo "  run-ingestor     - Run the ingester service"
	@echo "  run-normalizer   - Run a normalizer instance"
	@echo "  run-snapshotter  - Run a snapshotter instance"
	@echo "  run-gateway      - Run the gateway service"
	@echo "  test-client      - Run the test client"
	@echo ""
	@echo "Docker images:"
	@echo "  docker-build-all - Build all service images (uses build-images.sh)"
	@echo ""
	@echo "Kubernetes:"
	@echo "  deploy-local    - Build images and apply k8s manifests"
	@echo "  undeploy-local  - Delete namespace and all resources"
	@echo ""

# Install dependencies
install:
	uv sync

# Linting
lint:
	uv run ruff check .
	uv run ruff format --check .

# Type checking
typecheck:
	uv run mypy --strict services/

# Tests
test:
	uv run pytest tests/ -v

# Infrastructure
compose-up:
	docker-compose -f docker/docker-compose.yaml up -d
	@echo "✅ Infrastructure started!"
	@echo "🌐 NATS: http://localhost:8222"
	@echo "🔴 Redis: localhost:6379"
	@echo "💾 DynamoDB: http://localhost:8000"
	@echo "🪣 MinIO: http://localhost:9001 (admin/minioadmin)"
	@echo "📊 Prometheus: http://localhost:9090"
	@echo "📈 Grafana: http://localhost:3000 (admin/admin)"

compose-down:
	docker-compose -f docker/docker-compose.yaml down

# Clean up
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete

# Service runners
run-ingestor:
	uv run python -m services.ingestor.app --products BTC-USD,ETH-USD --broker-urls nats://localhost:4222

run-normalizer:
	uv run python -m services.normalizer.app --shard-id 0 --broker-urls nats://localhost:4222

run-snapshotter:
	uv run python -m services.snapshotter.app --shard-id 0 --broker-urls nats://localhost:4222

run-gateway:
	uv run python -m services.gateway.app --broker-urls nats://localhost:4222

test-client:
	uv run python test_client.py

# Kubernetes testing
k8s-setup:
	@echo "🚀 Setting up Kubernetes test environment..."
	./scripts/test-k8s.sh setup

k8s-test:
	@echo "🧪 Running Kubernetes integration tests..."
	./scripts/test-k8s.sh test

k8s-load:
	@echo "🚀 Running Kubernetes load tests..."
	./scripts/test-k8s.sh load

k8s-metrics:
	@echo "📊 Checking Kubernetes metrics..."
	./scripts/test-k8s.sh metrics

k8s-status:
	@echo "📋 Showing Kubernetes system status..."
	./scripts/test-k8s.sh status

k8s-cleanup:
	@echo "🧹 Cleaning up Kubernetes test environment..."
	./scripts/test-k8s.sh cleanup

k8s-all: k8s-setup k8s-test k8s-metrics
	@echo "✅ Complete Kubernetes test suite completed!"

# Development helpers
dev-setup: install compose-up
	@echo "🚀 Development environment ready!"
	@echo "Run 'make run-ingestor' in one terminal"
	@echo "Run 'make run-normalizer' in another terminal"
	@echo "Run 'make run-snapshotter' in another terminal"
	@echo "Run 'make run-gateway' in another terminal"
	@echo "Run 'make test-client' to test the system"

# Test client with different options
test-client-basic:
	uv run python test_client.py --products BTC-USD,ETH-USD --duration 30

test-client-load:
	uv run python test_client.py --products BTC-USD,ETH-USD --load-test --num-clients 10 --duration 60

# Docker images
.PHONY: docker-build-all
docker-build-all:
	./docker/build-images.sh

.PHONY: deploy-local
deploy-local:
	@echo "🚢 Building images and deploying to Kubernetes namespace '$(NAMESPACE)'..."
	VERSION=$(VERSION) REGISTRY=$(REGISTRY) PUSH=$(PUSH) ./docker/build-images.sh
	kubectl apply -f $(K8S_DIR)/namespace.yaml
	kubectl -n $(NAMESPACE) apply -f $(K8S_DIR)/infrastructure/
	# Apply config first to ensure env/urls exist
	kubectl -n $(NAMESPACE) apply -f $(K8S_DIR)/services/config.yaml
	# Apply all services (idempotent)
	kubectl -n $(NAMESPACE) apply -f $(K8S_DIR)/services/
	@echo "✅ Deploy complete. Check status with: kubectl -n $(NAMESPACE) get pods"

.PHONY: undeploy-local
undeploy-local:
	@echo "🧹 Deleting Kubernetes namespace '$(NAMESPACE)' (if exists)..."
	kubectl delete namespace $(NAMESPACE) --ignore-not-found
	@echo "✅ Removed. To remove local images: docker rmi -f $$(docker images 'ledgerflux-*' -q) || true"

# Pre-commit hooks
.PHONY: pre-commit-install
pre-commit-install:
	uvx pre-commit install --install-hooks
	@echo "✅ pre-commit installed. Hooks: ruff, black, mypy(strict), eof-fixer, trailing-whitespace"
