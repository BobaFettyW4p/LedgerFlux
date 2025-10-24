LedgerFlux — Market Data Fan‑Out (Coinbase Edition)

Overview
- Real‑time pipeline that ingests Coinbase markets, normalizes ticks, snapshots latest state, and serves clients over WebSockets.
- Tech: Python 3.12 + asyncio, FastAPI, NATS JetStream, DynamoDB (local), MinIO, Prometheus/Grafana.

Repository Layout
- `services/` — microservices
  - `ingestor/` — Coinbase WS client + resync
  - `normalizer/` — validation + shard routing
  - `snapshotter/` — latest state → DynamoDB, periodic snapshots → S3
  - `gateway/` — FastAPI gateway (WS): subscribe, backfill, rate limits
- `services/common/` — shared models, broker abstraction, utils
- `k8s/` — manifests for local cluster (minikube/kind)
- `docker/` — Docker assets
  - `docker-compose.yaml` — local infra only (NATS, Redis, DDB local, MinIO, Prom/Grafana)
  - `Dockerfile.*` — images (shared base: `Dockerfile.common`)
  - `build-images.sh` — builds all images
- `Makefile` — common tasks (lint, typecheck, test, build, deploy)
- `ARCHITECTURE.md` — deep dive on design and flows
- `TESTING.md` — testing strategy and notes

Prerequisites
- Docker and Docker Compose v2
- Python 3.12 and `uv` (or use Docker for everything)
- kubectl + a local cluster (minikube or kind) for k8s path

Quickstart (Infra via Docker Compose)
1) Start infra
   - `make compose-up`
   - URLs: NATS (http://localhost:8222), MinIO (http://localhost:9001), Prometheus (http://localhost:9090), Grafana (http://localhost:3000)
2) Run services locally (each in its own terminal)
   - `make run-ingestor`
   - `make run-normalizer`
   - `make run-snapshotter`
   - `make run-gateway`
3) Test end‑to‑end
   - `make test-client` (or see `test_client.py` options)

Quickstart (Build Docker images and deploy to Kubernetes)
1) Ensure your Docker daemon is the same one your cluster uses
   - minikube: `eval $(minikube docker-env)`
2) Build all images and apply manifests
   - `make deploy-local`
   - Custom tags/registry: `VERSION=v0.1.0 REGISTRY=ghcr.io/your-org/ make deploy-local`
   - Push to registry during build: add `PUSH=true`
3) Verify
   - `kubectl -n ledgerflux get pods`

Configuration
- Copy `.env.example` to `.env` and adjust as needed. Common vars:
  - `LOG_LEVEL=INFO`
  - `COINBASE_PRODUCTS=BTC-USD,ETH-USD`
  - `COINBASE_CHANNELS=ticker,heartbeat`
  - `NATS_URLS=nats://nats:4222` (k8s) or `nats://localhost:4222` (compose)
  - `WS_MAX_MSGS_PER_SEC`, `WS_BURST` (gateway)
  - `SNAPSHOT_PERIOD_MS`, `S3_BUCKET`, `DDB_TABLE` (snapshotter)
- Services also accept CLI flags; see `k8s/services/*.yaml` and `Makefile` targets for examples.

Development
- Install deps: `make install` (uses uv)
- Lint/format check: `make lint`
- Typecheck: `make typecheck`
- Tests: `make test`

Docker Images
- Build everything at once: `make docker-build-all` (or `./docker/build-images.sh`)
- Images built:
  - `ledgerflux-common:<tag>` base
  - `ledgerflux-ingestor:<tag>`
  - `ledgerflux-normalizer:<tag>` and `ledgerflux-normalizer:simple`
  - `ledgerflux-snapshotter:<tag>`
  - `ledgerflux-gateway:<tag>`

CI & Dependency Updates
- GitHub Actions CI runs lint, typecheck, and tests; Dependabot bumps actions and Docker base images.
- On Dependabot PRs touching Python deps, CI regenerates and commits `uv.lock`.

Troubleshooting
- Minikube images not found: run `eval $(minikube docker-env)` so builds land in the cluster’s daemon.
- Redis/NATS not reachable: confirm `docker-compose ps` and ports, or check `kubectl -n ledgerflux get pods`.
- Coinbase connectivity: for CI, recorded traffic is preferred; for local dev, check network/firewall.

More Details
- See `ARCHITECTURE.md` and `AGENTS.md` for deeper internals and acceptance criteria.
