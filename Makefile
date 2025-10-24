# LedgerFlux Market Data Fan-Out System

# Defaults
NAMESPACE ?= ledgerflux
K8S_DIR ?= k8s
VERSION ?= $(shell git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)

.PHONY: help install lint typecheck test compose-up compose-down clean \
	kind-up kind-load kind-deploy kind-down \
	minikube-up minikube-load minikube-deploy minikube-redeploy minikube-down

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
	@echo "  kind-up         - Create a Kind cluster and enable ingress"
	@echo "  kind-load       - Load local images into Kind"
	@echo "  kind-deploy     - Apply infra + services to Kind and wait"
	@echo "  kind-down       - Delete the Kind cluster"
	@echo "  minikube-up     - Start Minikube and enable ingress"
	@echo "  minikube-load   - Load local images into Minikube"
	@echo "  minikube-deploy - Apply infra + services to Minikube and wait"
	@echo "  minikube-down   - Stop and delete Minikube"
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
	@echo "🗄️ PostgreSQL: localhost:5432 (db=ledgerflux, user=postgres)"
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

# Kind helpers
KIND_CLUSTER ?= ledgerflux
IMAGES := ledgerflux-common ledgerflux-ingestor ledgerflux-normalizer ledgerflux-snapshotter ledgerflux-gateway
KIND_IMAGES := $(addsuffix :latest,$(IMAGES))
# Some manifests pin special tags (e.g., normalizer:simple). Ensure those are loaded too.
EXTRA_IMAGE_TAGS := ledgerflux-normalizer:simple
VERSIONED_IMAGES := $(addsuffix :$(VERSION),$(IMAGES))

kind-up:
	@echo "🧱 Creating Kind cluster '$(KIND_CLUSTER)'..."
	kind create cluster --name $(KIND_CLUSTER) || true
	@echo "🌐 Installing ingress-nginx in Kind..."
	kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
	@echo "⏳ Waiting for ingress-nginx controller..."
	kubectl wait --namespace ingress-nginx \
	  --for=condition=ready pod \
	  --selector=app.kubernetes.io/component=controller \
	  --timeout=180s
	@echo "✅ Kind is ready. Add to /etc/hosts: 127.0.0.1 ledgerflux.local nats.local minio.local"

kind-load:
	@echo "📦 Building images ..."
	VERSION=$(VERSION) DOCKER_BUILDKIT=1 ./docker/build-images.sh
	@echo "📤 Loading images into Kind ..."
	@for img in $(KIND_IMAGES); do \
	  echo " - $$img"; \
	  kind load docker-image $$img --name $(KIND_CLUSTER); \
	done
	@for img in $(VERSIONED_IMAGES); do \
	  echo " - $$img"; \
	  kind load docker-image $$img --name $(KIND_CLUSTER); \
	done
	@for img in $(EXTRA_IMAGE_TAGS); do \
	  echo " - $$img"; \
	  kind load docker-image $$img --name $(KIND_CLUSTER); \
	done

kind-deploy:
	@echo "🚀 Deploying to Kind ..."
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/infrastructure/
	kubectl apply -f k8s/services/
	kubectl apply -f k8s/ingress/
	@echo "⏳ Waiting for deployments ..."
	kubectl rollout status statefulset/nats -n ledgerflux --timeout=300s
	kubectl wait --for=condition=available --timeout=300s deploy/postgres -n ledgerflux
	kubectl wait --for=condition=available --timeout=300s deploy/minio -n ledgerflux
	# Wait for ingestor (Deployment)
	(if kubectl -n ledgerflux get deploy/ingestor >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status deploy/ingestor --timeout=300s; \
	fi)
	# Wait for normalizer (StatefulSet)
	(if kubectl -n ledgerflux get statefulset/normalizer >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status statefulset/normalizer --timeout=300s; \
	fi)
	# Wait for snapshotter (StatefulSet or Deployment)
	(if kubectl -n ledgerflux get statefulset/snapshotter >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status statefulset/snapshotter --timeout=300s; \
	elif kubectl -n ledgerflux get deploy/snapshotter >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status deploy/snapshotter --timeout=300s; \
	fi)
	# Wait for gateway (StatefulSet or Deployment)
	(if kubectl -n ledgerflux get statefulset/gateway >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status statefulset/gateway --timeout=300s; \
	elif kubectl -n ledgerflux get deploy/gateway >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status deploy/gateway --timeout=300s; \
	fi)
	@echo "✅ Deployed. Visit http://ledgerflux.local/"

kind-down:
	@echo "🗑️ Deleting Kind cluster '$(KIND_CLUSTER)'..."
	kind delete cluster --name $(KIND_CLUSTER) || true

# Minikube helpers
MINIKUBE_CPUS ?= 2
MINIKUBE_MEM ?= 4096

minikube-up:
	@echo "🚜 Starting Minikube ..."
	minikube start --cpus=$(MINIKUBE_CPUS) --memory=$(MINIKUBE_MEM)
	@echo "🌐 Enabling ingress ..."
	minikube addons enable ingress
	@echo "ℹ️  Add to /etc/hosts: $$(minikube ip) ledgerflux.local nats.local minio.local"

minikube-load:
	@echo "📦 Building images ..."
	VERSION=$(VERSION) DOCKER_BUILDKIT=1 ./docker/build-images.sh
	@echo "📤 Loading images into Minikube ..."
	@for img in $(KIND_IMAGES); do \
	  echo " - $$img"; \
	  minikube image load $$img; \
	done
	@for img in $(VERSIONED_IMAGES); do \
	  echo " - $$img"; \
	  minikube image load $$img; \
	done
	@for img in $(EXTRA_IMAGE_TAGS); do \
	  echo " - $$img"; \
	  minikube image load $$img; \
	done

minikube-deploy:
	@echo "🚀 Deploying to Minikube ..."
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/infrastructure/
	kubectl apply -f k8s/services/
	kubectl apply -f k8s/ingress/
	@echo "⏳ Waiting for deployments ..."
	kubectl rollout status statefulset/nats -n ledgerflux --timeout=300s
	kubectl wait --for=condition=available --timeout=300s deploy/postgres -n ledgerflux
	kubectl wait --for=condition=available --timeout=300s deploy/minio -n ledgerflux
	# Wait for ingestor (Deployment)
	(if kubectl -n ledgerflux get deploy/ingestor >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status deploy/ingestor --timeout=300s; \
	fi)
	# Wait for normalizer (StatefulSet)
	(if kubectl -n ledgerflux get statefulset/normalizer >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status statefulset/normalizer --timeout=300s; \
	fi)
	# Wait for snapshotter (StatefulSet or Deployment)
	(if kubectl -n ledgerflux get statefulset/snapshotter >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status statefulset/snapshotter --timeout=300s; \
	elif kubectl -n ledgerflux get deploy/snapshotter >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status deploy/snapshotter --timeout=300s; \
	fi)
	# Wait for gateway (StatefulSet or Deployment)
	(if kubectl -n ledgerflux get statefulset/gateway >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status statefulset/gateway --timeout=300s; \
	elif kubectl -n ledgerflux get deploy/gateway >/dev/null 2>&1; then \
	  kubectl -n ledgerflux rollout status deploy/gateway --timeout=300s; \
	fi)
	@echo "✅ Deployed. Visit http://$$(minikube ip)/ (or hosts entry for ledgerflux.local)."

# Convenience: build+load images, apply manifests, then restart pods so :latest changes take effect
minikube-redeploy: minikube-load minikube-deploy minikube-set-images
	@echo "✅ Minikube redeploy complete."

.PHONY: minikube-set-images
minikube-set-images:
	@echo "🖼️  Updating workload images to tag $(VERSION) ..."
	# Ingestor Deployment
	(if kubectl -n $(NAMESPACE) get deploy/ingestor >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) set image deploy/ingestor ingestor=ledgerflux-ingestor:$(VERSION); \
	fi)
	# Gateway Deployment
	(if kubectl -n $(NAMESPACE) get deploy/gateway >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) set image deploy/gateway gateway=ledgerflux-gateway:$(VERSION); \
	fi)
	# Snapshotter StatefulSet
	(if kubectl -n $(NAMESPACE) get statefulset/snapshotter >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) set image statefulset/snapshotter snapshotter=ledgerflux-snapshotter:$(VERSION); \
	fi)
	# Normalizer StatefulSet
	(if kubectl -n $(NAMESPACE) get statefulset/normalizer >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) set image statefulset/normalizer normalizer=ledgerflux-normalizer:$(VERSION); \
	fi)
	@echo "⏳ Waiting for image rollouts ..."
	(if kubectl -n $(NAMESPACE) get deploy/ingestor >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout status deploy/ingestor --timeout=300s; \
	fi)
	(if kubectl -n $(NAMESPACE) get deploy/gateway >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout status deploy/gateway --timeout=300s; \
	fi)
	(if kubectl -n $(NAMESPACE) get statefulset/snapshotter >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout status statefulset/snapshotter --timeout=300s; \
	fi)
	(if kubectl -n $(NAMESPACE) get statefulset/normalizer >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout status statefulset/normalizer --timeout=300s; \
	fi)

minikube-down:
	@echo "🛑 Stopping Minikube ..."
	minikube delete || true

# Rollout restarts for services after deploy (useful for :latest images)
.PHONY: k8s-restart
k8s-restart:
	@echo "🔄 Rolling out restarts in namespace '$(NAMESPACE)' ..."
	# Ingestor (Deployment)
	(if kubectl -n $(NAMESPACE) get deploy/ingestor >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout restart deploy/ingestor; \
	fi)
	# Gateway (prefer StatefulSet; fallback to Deployment)
	(if kubectl -n $(NAMESPACE) get statefulset/gateway >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout restart statefulset/gateway; \
	elif kubectl -n $(NAMESPACE) get deploy/gateway >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout restart deploy/gateway; \
	fi)
	# Snapshotter (prefer StatefulSet; fallback to Deployment)
	(if kubectl -n $(NAMESPACE) get statefulset/snapshotter >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout restart statefulset/snapshotter; \
	elif kubectl -n $(NAMESPACE) get deploy/snapshotter >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout restart deploy/snapshotter; \
	fi)
	# Normalizer (StatefulSet)
	(if kubectl -n $(NAMESPACE) get statefulset/normalizer >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout restart statefulset/normalizer; \
	fi)
	@echo "⏳ Waiting for rollouts to complete ..."
	# Ingestor
	(if kubectl -n $(NAMESPACE) get deploy/ingestor >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout status deploy/ingestor --timeout=300s; \
	fi)
	# Gateway
	(if kubectl -n $(NAMESPACE) get statefulset/gateway >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout status statefulset/gateway --timeout=300s; \
	elif kubectl -n $(NAMESPACE) get deploy/gateway >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout status deploy/gateway --timeout=300s; \
	fi)
	# Snapshotter
	(if kubectl -n $(NAMESPACE) get statefulset/snapshotter >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout status statefulset/snapshotter --timeout=300s; \
	elif kubectl -n $(NAMESPACE) get deploy/snapshotter >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout status deploy/snapshotter --timeout=300s; \
	fi)
	# Normalizer
	(if kubectl -n $(NAMESPACE) get statefulset/normalizer >/dev/null 2>&1; then \
	  kubectl -n $(NAMESPACE) rollout status statefulset/normalizer --timeout=300s; \
	fi)
	@echo "✅ Restarts complete."
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
