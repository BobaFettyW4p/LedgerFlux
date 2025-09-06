# AGENTS.md

> Operating instructions for a coding assistant to implement **Market Data Fan‑Out (Coinbase Edition)**. If requirements conflict, prefer **ARCHITECTURE.md** in repo root.

## Ground Rules

1. **Python 3.12** with `asyncio`. Gateway: **FastAPI**. Broker: **NATS JetStream** (default) with an abstract Broker interface and a **Redis Streams** fallback.
2. Strict quality gates: `ruff` + `black`, `mypy --strict`, `pytest` with high coverage of core logic.
3. No secrets in repo. Use env vars; support IRSA on EKS.
4. Deterministic tests where reasonable. For Coinbase, record/replay small WS/REST cassettes (e.g., `pytest-recording` or lightweight stub server) for CI.
5. Performance budgets: WS send queue backpressure, batched DDB writes, and minimal JSON allocations.

## Repository Layout

```
/ (repo root)
├─ ARCHITECTURE.md
├─ AGENTS.md
├─ Makefile
├─ docker-compose.yaml                # local dev: nats, dynamodb-local, minio, services
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
│  │  ├─ ddb.py
│  │  ├─ s3.py
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

* Initialize repo; Makefile tasks: `lint`, `typecheck`, `test`, `compose-up`, `compose-down`.
* `docker-compose` with NATS, DynamoDB Local, MinIO, Prometheus, Grafana.
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

* Maintain per‑product state; write DDB latest; batch snapshots to MinIO. Expose metrics: latency, write errors.
* Tests: idempotent DDB update; S3 path correctness.

**M5 – Gateway (WebSockets)**

* `/ws` endpoint: handle subscribe/unsubscribe, `from_seq` backfill, initial snapshot from DDB then deltas from JetStream.
* Implement token bucket rate limit; per‑product throttle; send `rate_limit` messages rather than dropping connection.
* Tests: protocol compliance, backfill, throttling behavior.

**M6 – Observability & Limits**

* Prometheus exporters; Grafana dashboards; trace spans with `product` and `shard` attributes.
* Lag monitor per shard (`md_seq_gap_total`, `md_resync_total`).

**M7 – Kubernetes (Helm)**

* Charts for services + NATS. Values for shard counts, resources, probes, preStop drain, ingress annotations for WebSockets.

**M8 – CI/CD**

* GitHub Actions: lint/typecheck/tests; build multi‑arch images; push to ECR; helm template/validate.

**Stretch – Canary & Replay**

* Argo Rollouts canary with metric checks. Replay tool that reads S3 snapshot batches and re‑publishes to `market.raw` for deterministic reproductions.

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
* Snapshotter: `SNAPSHOT_PERIOD_MS`, `S3_BUCKET`, `DDB_TABLE`.

## Acceptance Criteria

* **Ingestor**: handles disconnects and resubscribes within ≤ 3s; enforces contiguous `seq` per product or triggers resync; passes health metrics.
* **Normalizer**: emits canonical `Tick` with monotonic `seq` per product; shard mapping stable across restarts.
* **Snapshotter**: updates DDB row ≤ 250ms p50 after last tick; S3 batch ≤ 60s cadence or 5MB.
* **Gateway**: on subscribe, snapshot ≤ 150ms p50; no reordering within a product; `from_seq` backfill works.
* **System**: zero dropped connections during rolling restart (validated via preStop drain + readiness gates).

## Coding Standards

* `ruff` + `black` (line length 100); `mypy --strict`.
* Typed exceptions; no bare `except`.
* JSON only over the wire; optional gzip.
* Use `asyncio.TaskGroup` (Py3.12) and explicit cancellation handling.

## Local Dev How‑To

* `make compose-up` → boots NATS, DDB Local, MinIO, Prometheus, Grafana.
* `make run-ingestor` with `COINBASE_PRODUCTS` set.
* `make watch-gateway` → simple CLI/web client to subscribe to products and observe snapshot+delta flow.

## Testing Strategy

* Unit tests for models and brokers.
* Integration tests bring up docker‑compose services, run ingestor + gateway, assert end‑to‑end delivery and backfill.
* CI uses recorded Coinbase WS/REST interactions to avoid live dependency.

## Deployment Notes

* Helm values expose shard count and resource requests; ALB/NLB configured for WS.
* PreStop ≥ 20s; target deregistration delay ≥ PreStop.

## Non‑Goals (initial)

* User‑authenticated/private channels; multi‑region active‑active; full historical archive.