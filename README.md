# LedgerFlux

A high-performance, distributed market data processing system built with Python, Kubernetes, and NATS JetStream.

## Overview

LedgerFlux demonstrates a production-ready microservices architecture for ingesting, processing, and serving real-time cryptocurrency market data. The system showcases:

- **Event-driven architecture** using NATS JetStream for reliable message streaming
- **Horizontal scalability** with sharded processing and StatefulSets
- **Cloud-native deployment** on Kubernetes with Skaffold for development
- **Observability** with Prometheus metrics and Grafana dashboards
- **Stateful snapshots** with PostgreSQL for point-in-time recovery

## Architecture

```
Coinbase WebSocket → Ingestor → NATS JetStream → [Normalizers] → [Snapshotters] → PostgreSQL
                                                         ↓
                                                   Gateway (WebSocket API)
```

## Quick Start

### Prerequisites

**Required:**
- **[uv](https://docs.astral.sh/uv/)** - Fast Python package manager
  ```bash
  # Install uv (choose one):
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # or
  pip install uv
  # or
  pipx install uv
  ```

**For Kubernetes deployment (optional):**
- [Minikube](https://minikube.sigs.k8s.io/docs/start/) (v1.30+)
- [Skaffold](https://skaffold.dev/docs/install/) (v2.0+)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)

**Note:** You don't need Python 3.12 pre-installed - `make install` will automatically install it via `uv`.

### Getting Started (First Time Setup)

```bash
# 1. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone the repository
git clone <repo-url>
cd LedgerFlux

# 3. Install Python 3.12 + dependencies
make install

# 4. Run tests to verify everything works
make test
```

That's it! `make install` handles everything - Python 3.12 installation and all dependencies.

<details>
<summary>What gets installed?</summary>

**Production dependencies:**
- `fastapi` - Web framework
- `websockets` - WebSocket support
- `pydantic` - Data validation
- `nats-py` - NATS JetStream messaging
- `uvicorn` - ASGI server
- `psycopg` - PostgreSQL adapter
- `prometheus-client` - Metrics

**Development/testing dependencies:**
- `pytest` + `pytest-asyncio` - Testing framework with async support
- `pytest-cov` - Coverage reporting
- `pytest-mock` - Advanced mocking
- `pytest-timeout` - Prevent hanging tests
- `freezegun` - Time manipulation for tests
- `httpx` - FastAPI testing support
- `ruff` - Fast linter
- `black` - Code formatter
- `mypy` - Type checker

</details>

### Deploying to Kubernetes

```bash
make up
```

This will:
1. Start Minikube with appropriate resources (4 CPUs, 8GB RAM)
2. Build all Docker images
3. Deploy infrastructure (NATS, PostgreSQL, MinIO, Prometheus, Grafana)
4. Deploy all microservices

### Verify Deployment

```bash
make status
```

You should see all pods running in the `ledgerflux` namespace.

### Access Dashboards

Open Grafana to view market data and system health:

```bash
make grafana
```

This will automatically open Grafana in your browser. Login with `admin` / `admin`.

Available dashboards:
- **LedgerFlux Market Data** - Real-time price charts, bid/ask spreads, trading volume
- **LedgerFlux System Health** - Service metrics, ingestion rates, active connections

Other UIs:

```bash
make prometheus    # Metrics explorer
make gateway-ui    # WebSocket gateway
```

### Stop Everything

```bash
make compose-down
```

## Development

### Hot-Reload Development Mode

```bash
make skaffold-dev
```

This starts Skaffold in development mode - any code changes will automatically rebuild and redeploy the affected services.

### Run Individual Services Locally

```bash
# Terminal 1: Start infrastructure
make compose-up

# Terminal 2: Run ingestor locally
make run-ingestor

# Terminal 3: Run normalizer locally  
make run-normalizer

# Terminal 4: Run snapshotter locally
make run-snapshotter

# Terminal 5: Run gateway locally
make run-gateway
```

### Testing

LedgerFlux has comprehensive unit test coverage for all critical business logic. All testing dependencies are automatically installed by `make install`.

#### Running Tests

```bash
# Run tests with coverage (opens HTML report in browser)
make test
```

This will:
1. Run all unit tests with coverage
2. Generate an HTML coverage report
3. Automatically open the report in your default browser
4. Display coverage summary in the terminal

#### Test Coverage

The test suite covers:
- **Common utilities** (85%+): Sharding, hashing, product validation, quantity formatting
- **Rate limiting** (85%+): Token bucket algorithm, burst handling, time-based refills
- **Data transformation** (85%+): Coinbase ticker parsing, timestamp conversion
- **Data validation** (85%+): Price validation, spread checking, sequence ordering
- **Pydantic models** (75%+): All data models and message protocols
- **Configuration** (70%+): Config loading with env var precedence

**Overall target: 70%+ coverage** (enforced in CI)

#### Test Structure

```
tests/
├── conftest.py              # Root fixtures (NATS, PostgreSQL, WebSocket mocks)
└── unit/
    ├── conftest.py          # Sample data fixtures
    ├── common/              # Tests for shared modules
    │   ├── test_util.py     # Sharding, validation, formatting
    │   ├── test_models.py   # Pydantic models
    │   └── test_config.py   # Configuration loading
    ├── gateway/             # Gateway service tests
    │   ├── test_rate_limiter.py
    │   └── test_client_conn.py
    ├── ingestor/            # Ingestor service tests
    │   └── test_transform.py
    └── normalizer/          # Normalizer service tests
        └── test_validation.py
```

#### Code Quality

```bash
# Run linting
make lint

# Run type checking (strict mode)
make typecheck

# Run all checks (lint + typecheck + test with coverage)
make lint && make typecheck && make test
```

The test command will open an interactive HTML coverage report showing exactly which lines are covered and which need attention.

## Makefile Commands

Run `make help` to see all available commands:

```
Available Makefile targets:
  compose-up       - Start infrastructure via Minikube + Skaffold
  compose-down     - Remove deployments and stop Minikube
  skaffold-run     - Build and deploy with Skaffold
  skaffold-dev     - Live-reload with Skaffold dev loop
  status           - Show status of all pods
  test             - Run tests
  lint             - Run linting
  clean            - Clean up temporary files
```

## Technical Stack

- **Language**: Python 3.12 with type hints
- **Orchestration**: Kubernetes + Skaffold
- **Messaging**: NATS JetStream
- **Database**: PostgreSQL
- **Storage**: MinIO (S3-compatible)
- **Monitoring**: Prometheus + Grafana
- **Packaging**: UV for dependency management

## Project Structure

```
.
├── services/
│   ├── common/          # Shared utilities and models
│   ├── ingestor/        # WebSocket ingestion service
│   ├── normalizer/      # Stateful message processing
│   ├── snapshotter/     # Snapshot persistence
│   └── gateway/         # WebSocket API gateway
├── k8s/                 # Kubernetes manifests
├── docker/              # Dockerfiles
├── Makefile             # Development commands
└── skaffold.yaml        # Skaffold configuration
```

## Troubleshooting

### Pods Not Starting

If pods are in `CrashLoopBackOff`:

```bash
# Check logs
kubectl logs -n ledgerflux <pod-name>

# Or use Skaffold's log streaming
make logs
```

### Minikube Resources

If you see "Insufficient CPU/Memory" errors:

```bash
minikube delete
minikube start --cpus=4 --memory=8192
make compose-up
```

### Clean Slate

To completely reset:

```bash
make clean
minikube delete
make compose-up
```

## License

MIT
