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

- [Minikube](https://minikube.sigs.k8s.io/docs/start/) (v1.30+)
- [Skaffold](https://skaffold.dev/docs/install/) (v2.0+)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [Make](https://www.gnu.org/software/make/)

### One-Command Setup

```bash
make compose-up
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

```bash
# Run unit tests
make test

# Run linting
make lint

# Run type checking
make typecheck
```

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
