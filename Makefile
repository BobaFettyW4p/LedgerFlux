# LedgerFlux Market Data Fan-Out System

# Defaults
NAMESPACE ?= ledgerflux
K8S_DIR ?= k8s

.PHONY: help install lint typecheck test up down clean \
	kind-up kind-load kind-deploy kind-down \
	minikube-up minikube-load minikube-deploy minikube-down \
	skaffold-prep skaffold-run skaffold-dev grafana prometheus gateway-ui

# Default target
help:
	@echo "LedgerFlux Market Data Fan-Out System"
	@echo "====================================="
	@echo ""
	@echo "Available targets:"
	@echo "  install       - Install dependencies"
	@echo "  lint          - Run linting"
	@echo "  typecheck     - Run type checking"
	@echo "  test          - Run tests with coverage (opens HTML report in browser)"
	@echo "  up            - Start local Kubernetes stack (Minikube + Skaffold)"
	@echo "  down          - Teardown Minikube cluster and all deployments"
	@echo "  clean         - Clean up temporary files"
	@echo ""
	@echo "Access UI (opens in browser):"
	@echo "  grafana       - Open Grafana dashboard (monitoring & market data)"
	@echo "  prometheus    - Open Prometheus metrics"
	@echo "  gateway-ui    - Open Gateway WebSocket UI"
	@echo ""

# Install dependencies
install:
	@if ! command -v uv > /dev/null; then \
		echo "Error: uv is not installed."; \
		echo ""; \
		echo "Install uv with one of the following:"; \
		echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		echo "  pip install uv"; \
		echo "  pipx install uv"; \
		echo ""; \
		echo "Then run 'make install' again."; \
		exit 1; \
	fi
	@echo "Ensuring Python 3.12+ is available..."
	@uv python install 3.12
	@uv python pin 3.12
	@echo "Installing project dependencies..."
	@uv sync --all-extras
	@echo ""
	@echo "✓ Installation complete! Python 3.12 and all dependencies installed."
	@echo "  Run 'make test' to run tests with coverage"

# Linting
lint:
	uv run ruff check .
	uv run ruff format --check .

# Type checking
typecheck:
	uv run mypy --strict services/

# Tests
test:
	@echo "Running tests with coverage..."
	@uv run pytest tests/unit -v --cov=services --cov-report=html --cov-report=term-missing
	@echo ""
	@echo "Opening coverage report in browser..."
	@if command -v xdg-open > /dev/null; then \
		xdg-open htmlcov/index.html; \
	elif command -v open > /dev/null; then \
		open htmlcov/index.html; \
	else \
		echo "Coverage report generated at htmlcov/index.html"; \
	fi

# Infrastructure
minikube-up:
	@echo "Starting Minikube cluster (8GB RAM, 4 CPUs, 50GB disk)..."
	minikube start --memory=8192 --cpus=4 --disk-size=50g --driver=docker
	@echo "Creating namespace $(NAMESPACE)..."
	-kubectl create namespace $(NAMESPACE)
	@echo "Minikube cluster ready"

minikube-down:
	@echo "Deleting Minikube cluster and all data..."
	minikube delete
	@echo "Minikube cluster deleted"

up:
	@echo "Starting local Kubernetes stack (Minikube + Skaffold)..."
	$(MAKE) minikube-up
	skaffold run -p minikube --status-check --cache-artifacts=false
	@echo "Kubernetes stack ready on Minikube (namespace: ledgerflux)"

down:
	@echo "Tearing down Minikube cluster and all deployments..."
	- skaffold delete -p minikube
	$(MAKE) minikube-down
	@echo "Minikube cluster stopped and deleted"

# Clean up
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -rf htmlcov/
	rm -f .coverage coverage.xml
	rm -rf .pytest_cache/

.PHONY: grafana prometheus gateway-ui
grafana:
	@echo "Opening Grafana (monitoring & market data dashboards)..."
	@echo "Login: admin / admin"
	@echo "Access at: http://localhost:3000"
	@kubectl port-forward -n ledgerflux svc/grafana 3000:3000

prometheus:
	@echo "Opening Prometheus (metrics explorer)..."
	@echo "Access at: http://localhost:9090"
	@kubectl port-forward -n ledgerflux svc/prometheus 9090:9090

gateway-ui:
	@echo "Opening Gateway WebSocket UI..."
	@echo "Access at: http://localhost:8000"
	@kubectl port-forward -n ledgerflux svc/gateway 8000:8000
