# AGENTS.md

> Operating instructions for a coding assistant to implement **Market Data Fan‑Out**. If requirements conflict, prefer **ARCHITECTURE.md** in repo root.

## Ground Rules

1. **Python 3.12** with `asyncio`. Gateway: **FastAPI**. Broker: **NATS JetStream**.
2. Strict quality gates: `ruff` + `black`, `mypy --strict`, `pytest` with high coverage of core logic.
3. No secrets in repo. Use env vars and Kubernetes Secrets/ServiceAccounts; no cloud‑specific IAM assumptions.
4. Deterministic tests where reasonable. For Coinbase, record/replay small WS/REST cassettes (e.g., `pytest-recording` or lightweight stub server) for CI.
5. Performance budgets: WS send queue backpressure, batched snapshot store writes (e.g., Redis/PostgreSQL), and minimal JSON allocations.
6. A preference for readable code above all else. i.e. if a variable references a product, name it `product` as opposed to `p`

## Repository Layout

```
/ (repo root)
├─ ARCHITECTURE.md
├─ AGENTS.md
├─ Makefile
├─ docker-compose.yaml                # legacy; prefer Minikube-based local dev
├─ helm/                              # charts for each service
├─ k8s/                               # optional raw manifests
├─ services/
│  ├─ ingestor/
│  │  ├─ app.py          # Coinbase WS client + subscribe manager
│  │  ├─ cb_ws.py        # low-level ws client (permessage-deflate, reconnects)
│  │  ├─ cb_rest.py      # REST snapshot fetch for resync
│  │  └─ tests/
│  ├─ normalizer/
│  │  ├─ app.py
│  │  ├─ shard.py
│  │  └─ tests/
│  ├─ snapshotter/
│  │  ├─ app.py
│  │  ├─ ddb.py          # state store adapter (migrate to Redis/PostgreSQL)
│  │  ├─ s3.py           # object store adapter (target MinIO)
│  │  └─ tests/
│  ├─ gateway/
│  │  ├─ app.py          # FastAPI + WS endpoints
│  │  ├─ protocol.py     # schemas, validation
│  │  ├─ backfill.py
│  │  ├─ ratelimit.py
│  │  ├─ metrics.py
│  │  └─ tests/
│  └─ common/
│     ├─ models.py       # Pydantic: Tick, Snapshot, WS messages
│     ├─ stream.py       # Broker ABC; NatsBroker, RedisBroker
│     ├─ util.py
│     └─ tests/
├─ charts/ (umbrella Helm chart)
├─ .github/workflows/
│  ├─ ci.yml
│  └─ release.yml
└─ tools/
   └─ loadtest/
```

## Upstream (Coinbase) Contracts

* **WS endpoints**: `wss://ws-feed.exchange.coinbase.com` (public), optional `wss://ws-direct.exchange.coinbase.com` (auth, lower latency).
* **Channels** (configure): `ticker`, `heartbeat`, and optionally `level2` or `level2_batch`.
* **Products**: comma‑separated list like `BTC-USD,ETH-USD`.
* **Sequences**: treat Coinbase `sequence` as canonical per product. The ingestor ensures contiguous delivery to downstream or triggers resync.

## Message Schemas (Pydantic, summarized)

* `Tick`: `v:int`, `type="tick"`, `product:str`, `seq:int`, `ts_event:int`, `ts_ingest:int`, `fields: dict` (last\_trade / best\_bid / best\_ask as available from channels).
* `Snapshot`: `v:int`, `type="snapshot"`, `product:str`, `seq:int`, `ts_snapshot:int`, `state: dict`.
* WS client messages (our gateway): `Subscribe`, `Unsubscribe`, `Ping`.
* WS server messages: `SnapshotMsg`, `IncrMsg`, `RateLimit`, `Pong`, `Error`.

## Work Plan (Milestones)

**M1 – Scaffolding & Local Dev**

* Initialize repo; Makefile tasks: `lint`, `typecheck`, `test`, `compose-up`, `compose-down` (Minikube + Skaffold).
* `k8s/minikube` with NATS, Redis, MinIO, Prometheus, Grafana.
* Common models + Broker abstraction with `NatsBroker` stub; basic FastAPI gateway skeleton.

**M2 – Coinbase Ingestor**

* Implement `cb_ws.py` with reconnect/backoff, permessage-deflate, subscribe/unsubscribe handshake.
* Subscribe to `ticker` + `heartbeat` for configured products. Parse `sequence`, `price`, `best_bid/ask` when available.
* Implement gap detection per product. On gap: pause emits for product, call `cb_rest.py` to fetch book snapshot, replay queued messages where `sequence > snapshot_seq`, then resume.
* Emit canonical `Tick` to broker.
* Tests: sequence monotonicity, gap → resync path, reconnect + resubscribe.

**M3 – Normalizer & Sharder**

* Validate payloads, map to `Tick`, stamp `ts_ingest`. Stable hash(product) → shard. Publish to JetStream.
* Tests: shard determinism, schema validation.

**M4 – Snapshotter**

* Maintain per‑product state; write latest snapshot to Redis or PostgreSQL; batch snapshots to MinIO. Expose metrics: latency, write errors.
* Tests: idempotent KV/DB update; MinIO path correctness.

**M5 – Gateway (WebSockets)**

* `/ws` endpoint: handle subscribe/unsubscribe, `from_seq` backfill, initial snapshot from PostgreSQL (or Redis cache) then deltas from JetStream.
* Implement token bucket rate limit; per‑product throttle; send `rate_limit` messages rather than dropping connection.
* Tests: protocol compliance, backfill, throttling behavior.

**M6 – Observability & Limits**

* Prometheus exporters; Grafana dashboards; trace spans with `product` and `shard` attributes.
* Lag monitor per shard (`md_seq_gap_total`, `md_resync_total`).

**M7 – Kubernetes (Helm)**

* Charts for services + NATS. Values for shard counts, resources, probes, preStop drain, ingress (NGINX) annotations for WebSockets.

**M8 – CI/CD**

* GitHub Actions: lint/typecheck/tests; build multi‑arch images; push to GHCR or local registry; helm template/validate.

**Stretch – Canary & Replay**

* Argo Rollouts canary with metric checks. Replay tool that reads MinIO snapshot batches and re‑publishes to `market.raw` for deterministic reproductions.

## Configuration (environment variables)

* Shared: `LOG_LEVEL`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `BROKER_KIND=nats|redis`.
* Coinbase Ingestor:

  * `COINBASE_WS_PRIMARY=wss://ws-feed.exchange.coinbase.com`
  * `COINBASE_WS_FALLBACK=wss://ws-direct.exchange.coinbase.com` (optional)
  * `COINBASE_PRODUCTS=BTC-USD,ETH-USD`
  * `COINBASE_CHANNELS=ticker,heartbeat,level2_batch`
  * `COINBASE_API_KEY`, `COINBASE_API_SECRET`, `COINBASE_API_PASSPHRASE` (only if using `ws-direct`)
  * `RESYNC_MAX_QUEUE_MS=2000` (buffer window while fetching snapshot)
* JetStream: `NATS_URLS`, `JS_STREAM_NAME`, `JS_RETENTION_MINUTES`.
* Redis (optional): `REDIS_URL`, `STREAM_NAME`, `CONSUMER_GROUP`.
* Gateway: `WS_MAX_MSGS_PER_SEC`, `WS_BURST`, `AUTH_API_KEYS`, `BACKFILL_MAX_MINUTES`.
* Snapshotter: `SNAPSHOT_PERIOD_MS`, `OBJECT_BUCKET` (MinIO), `REDIS_URL` (or `PG_*` for PostgreSQL).

## Acceptance Criteria

* **Ingestor**: handles disconnects and resubscribes within ≤ 3s; enforces contiguous `seq` per product or triggers resync; passes health metrics.
* **Normalizer**: emits canonical `Tick` with monotonic `seq` per product; shard mapping stable across restarts.
* **Snapshotter**: updates PostgreSQL row ≤ 250ms p50 after last tick; MinIO batch ≤ 60s cadence or 5MB.
* **Gateway**: on subscribe, snapshot ≤ 150ms p50; no reordering within a product; `from_seq` backfill works.
* **System**: zero dropped connections during rolling restart (validated via preStop drain + readiness gates).

## Coding Standards

* `ruff` + `black` (line length 100); `mypy --strict`.
* Typed exceptions; no bare `except`.
* JSON only over the wire; optional gzip.
* Use `asyncio.TaskGroup` (Py3.12) and explicit cancellation handling.

## Local Dev How‑To

* `make compose-up` (Minikube + Skaffold) → boots NATS, PostgreSQL, MinIO, Prometheus, Grafana via Kubernetes.
* `make run-ingestor` with `COINBASE_PRODUCTS` set.
* `make watch-gateway` → simple CLI/web client to subscribe to products and observe snapshot+delta flow.

## Testing Strategy

* Unit tests for models and brokers.
* Integration tests bring up Minikube/Skaffold environment, run ingestor + gateway, assert end‑to‑end delivery and backfill.
* CI uses recorded Coinbase WS/REST interactions to avoid live dependency.

## Deployment Notes

* Helm values expose shard count and resource requests; use NGINX Ingress for WebSockets in‑cluster.
* PreStop ≥ 20s; use readiness gates and in‑cluster connection draining via NGINX timeouts.

## Non‑Goals (initial)

* User‑authenticated/private channels; multi‑region active‑active; full historical archive.
