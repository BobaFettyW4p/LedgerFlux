# LedgerFlux

A high-performance, distributed market data processing system built with Python, Kubernetes, and NATS JetStream.

## Overview

LedgerFlux demonstrates a production-ready microservices architecture for ingesting, processing, and serving real-time cryptocurrency market data. The system showcases:

- **Event-driven architecture** using NATS JetStream for reliable message streaming
- **Horizontal scalability** via Kubernetes primitives.
- **Easy Deployment** on Kubernetes via `make`, `skaffold` and `minikube`
- **Observability** with Prometheus metrics and Grafana dashboards tracking both historical market data and system health
- **Stateful snapshots** with PostgreSQL for point-in-time recovery

## Pre-requisites

`minikube v1.37.0` or later
`make v4.4.1` or later
`python v3.12` or later
`uv v0.9.21` or later

This project has been tested and works well on my desktop computer running Fedora and my laptop running Arch. I presume it would work well on different linux distributions, or on Mac or Windows, but I am not able to test on these systems.

## Quick-Start Guide

This projects leverages `make` in order to provide a way to stand up or tear down our infrastructure through a single command.

### make up 

The `up` make target will perform all of the steps to erect our infrastructure. It will:

- spin up a new k8s cluster via minikube with the following specs:
- 8 GB of RAM
- 4 CPUs
- 50 GB of disk space (this project has a cron job that automatically cleans up all data older than an hour. If you run your project with all 3 default coins, the project should be configured so it never runs out of space)
NOTE: I haven't tested this with an existing minikube cluster. Make sure there is not an active 

It will also build all of the needed docker images and deploy pods in kubernetes via `skaffold`.

Once constructed, all pods should fully visible and functional in the `ledgerflux` namespace. To view the status:

```kubectl get pods -n ledgerflux```
```
```

### make [test|lint|typecheck]

This project leverages `pytest` in order to perform unit testing. The `make test` target will initiate our test suite and will perform full unit testing.

We use `ruff` to enforce linting. The `make lint` target will ensure our project adheres to best practices for production python code.

Finally, we leverage `make mypy` to enforce type-checking on our repository. When the project was architected, `ty` was not yet released, but I have heard good things about it, and have greatly enjoyed all releases from Astral Labs I have used up to this point.
I often said there were three hard problems in computer science: cache invalidation, naming things, and python package management. They're in the process of solving one of these problems, in my humble opinion.

While you can test them yourself, this project has a CI/CD pipeline that runs all of these checks on PR, so you can instead opt to view past runs [here](https://github.com/BobaFettyW4p/LedgerFlux/actions)

### make down

Finally, make down will delete the minikube instance and all of the pods in it.

## Architecture

```
Coinbase WebSocket → Ingestor → NATS JetStream → [Normalizers] → [Snapshotters] → PostgreSQL
                                                         ↓
                                                      Gateway
```

#### Data flow 

 In our infrastructure, the Ingestor connects to the Coinbase Websocket and forwards messages to NATS Jetstream, which serves as a message broker. Jetstream conveys these messages to the Normalizers, which validates each tick, calculates the shard it should reside on, and then publish that tick onto the appropriate Jetstream stream to ensure it is sent to the appropriate snapshotter.

### Ingestor

This component connects to the websocket data feed from Coinbase, and prepares it for transportation via Jetstream. It subscribes to the Coinbase feed, as well as the market_ticks NATS Jetstream stream to broker messages

By default, the ingestor will subscribe to the websocket feed for Bitcoin (BTC-USD), Ethereum (ETH-USD) and Cardano (ADA-USD). These are relatively popular cryptocurrencies with relatively consistent and high trading volume, making them a good demonstration of the capabilities of this system. It is possible to modify these values by modifying the source json for the configMap for the kubernetes pod, located at `k8s/services/configs/ingestor.json`. NOTE: if you modify the list of subscribed products, the market data dashboards are not set up to handle that. Do it at your own peril!

#### Why Coinbase?

When I was originally conceptualizing and planning out the project, I wanted to utilize a FIX API. While this project attempts to mirror production workflows, it does not have the capital-backing of a production trading infrastructure, and so any FIX feed we utilized would have to be free.

When searching different market feeds, I found documentation that led me to believe Coinbase's FIX feed would be free to access, and thus perfect for the project. 

After struggling to establish a connection and exploring the Coinbase documentation thorouhly, I was able to determine that Coinbase requires a business account in order to access the FIX feed, a requirement which not only requires an account which would not have been a dealbreaker, but a minimum monthly fee/investment, which was.

Until relatively recently, crypto markets didn't rely on FIX the way traditional securities do. Simple websocket feeds, like the one Coinbase provides free of charge and without authentication requirements, were used for many years in the early years of crypto to provide pricing data to prospective crypto traders. This has changed, but I have been led to believe that the websocket feeds are still used to track crypto prices by professional traders to this day.

Therefore, while this was not part of the original plan for this project, it is an acceptable middle ground that 

### Getting Started (First Time Setup)

```bash
# 1. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone the repository
git clone https://github.com/BobaFettyW4p/LedgerFlux.git
cd LedgerFlux

# 3. Install Python 3.12 + dependencies
make install

# 4. Build the project
make up

# 5. Run tests to verify everything works
make test

# 6. Once finished, tear everything down
make down
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
1. Start Minikube with appropriate resources (4 CPUs, 8GB RAM, sufficient disk space to store data before data retention policies clean it up)
2. Build all Docker images
3. Deploy infrastructure (NATS, PostgreSQL, MinIO, Prometheus, Grafana)
4. Deploy all microservices

### Verify Deployment

```bash
You should see all pods running in the `ledgerflux` namespace. To view:
```
```
```

```
```
kubectl get pods -n ledgerflux
```

```
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
make down
```


This starts Skaffold in development mode - any code changes will automatically rebuild and redeploy the affected services.

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
This project leverages `black` `ruff` and `mypy` to enforce linting and type standards. 

There is a CI/CD pipeline located at `.github/workflows/ci.yml` that runs these tools on the codebase prior to merge.
```

## Makefile Commands

Run `make help` to see all available commands:

```
Available Makefile targets:
  up       - Start infrastructure via Minikube + Skaffold
  down     - Remove deployments and stop Minikube
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
