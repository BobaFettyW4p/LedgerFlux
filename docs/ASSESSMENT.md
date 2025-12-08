# LedgerFlux Project Assessment (current snapshot)

Date: 2024-XX-XX  
Scope: high-level inventory of current state, gaps, and placeholders to flesh out for production readiness.

## What’s Working / Present
- Basic service scaffolding exists for ingestor, normalizer, snapshotter, and gateway; FastAPI gateway skeleton runs with simple WS fan-out; docker-compose and k8s manifests bootstrap infra components (NATS, Redis, Postgres, MinIO, Prometheus, Grafana).
- Shared Pydantic models for Tick/Snapshot and client messages; JetStream wrapper (`NATSStreamManager`) with publish/subscribe helpers; hashing utility for shard selection; Dockerfiles and Makefile targets for build/run/test/deploy (Kind/Minikube).

## Critical Breakages
- Missing shared modules: `NATSConfig`, `load_nats_config`, `services.common.pg_store` (Postgres adapter) are imported but not implemented, so services cannot start. Ingestor `main()` references undefined `config`; gateway uses `_load_service_config` that does not exist.
- Protocol mismatch: models expect `operation`, test client and HTML doc use `op`; field names diverge from ARCHITECTURE.md; schema validation is loose and inconsistent.
- Runtime endpoints absent: ingestor lacks /health and /ready despite k8s probes; snapshotter/gateway readiness is superficial; docker-compose runs infra only (no services).
- Python/tooling gaps: `pyproject.toml` targets Python >=3.11 (should be 3.12), missing dev/test deps (pytest, mypy, black, ruff), and tests directory referenced by Makefile does not exist.

## Major Missing Implementation (vs ARCHITECTURE/AGENTS)
- Ingestor resilience: reconnect/backoff, resubscribe with prior products/channels, per-product sequence tracking, gap detection, REST book resync, and WS backpressure handling; heartbeat handling is TODO.
- Normalization: strict schema validation, `ts_ingest` stamping, monotonic per-product seq enforcement, deterministic shard mapping aligned to `hash(product) % N`, and metrics.
- Snapshotting: durable latest-state store (Redis/Postgres) with idempotent upsert, periodic/batched MinIO writes, snapshot latency metrics, and clear snapshot versioning/state shape.
- Gateway correctness: implement outward `op` protocol with subscribe/unsubscribe/ping; initial snapshot load from store; JetStream backfill starting at `from_seq`; per-client token bucket and per-product throttling; graceful drain/readiness gates.
- Backfill/replay: no JetStream retained replay in gateway, no replay tool from MinIO batches.
- Observability: Prometheus metrics, structured logging, tracing, counters for gaps/resyncs/snapshot latency; no alerts/dashboards wired to real metrics.

## Placeholder / Needs Flesh-Out
- Config handling: central NATS config dataclass + loader, env-driven service config, and secrets via env/Secret mounts (no hardcoded secrets).
- Broker layer: JetStream stream/consumer setup with retention/ack wait, durable pull subs, and backpressure; replace print-debug with structured logging.
- Persistence: implement Postgres/Redis snapshot store (connect/ensure_schema/upsert/get_latest/close) used by snapshotter/gateway.
- Protocol alignment: unify on `op` naming, update models/client/gateway accordingly, enforce validation with clear error codes.
- Health/readiness: HTTP endpoints per service matching k8s probes; graceful shutdown with `asyncio.TaskGroup` and cancellation handling.
- CI/CD: add ruff/black/mypy --strict/pytest wiring; recorded Coinbase fixtures for deterministic tests; GitHub Actions pipeline; coverage for core paths (ingest gaps, normalization, backfill, rate limit).
- Docker/k8s: add service containers to docker-compose; ensure manifests match image tags/entrypoints; resource requests/limits and PDBs; ingress/connection draining aligned to gateway drain logic.

## Suggested Next Steps
1) Implement shared config and Postgres snapshot store, fix import/runtime blockers (NATSConfig, load_nats_config, shard utility names, missing `_load_service_config`, ingestor `config` wiring). Align Python version to 3.12 and add dev/test deps. Wire lint/typecheck/test scripts to pass.
2) Normalize protocol: standardize `op` field across models, gateway, and test client; add validation and error codes; update gateway to fetch snapshot/backfill from JetStream and enforce rate limits.
3) Harden ingest/normalize/snapshot pipeline: add reconnect/resubscribe, sequence tracking + gap/resync path, normalization with `ts_ingest` and shard mapping, snapshot store upsert + MinIO batch writer, and Prometheus metrics.
