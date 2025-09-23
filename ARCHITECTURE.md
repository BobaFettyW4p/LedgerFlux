# ARCHITECTURE.md

## Goal

A production‑style, cloud‑native market‑data fan‑out that ingests **real Coinbase Exchange** WebSocket data, normalizes it, shards by symbol, and broadcasts **snapshots + incremental updates** over WebSockets with backfill, per‑client rate limits, and observability. Target stack: **Python, Docker, Kubernetes/Minikube, GitHub Actions**.

> Terminology: Coinbase "product" ≙ symbol pair (e.g., `BTC-USD`). We treat each product as an ordering domain.

## High‑Level Diagram (text)

```
[Coinbase Exchange WS]
  channels: ticker, heartbeat, (level2 or level2_batch)
        |
 [Ingestor/Adapter]
  - resilient WS client (primary + optional direct)
  - per-product sequence tracking + gap detection
  - re-sync path via REST book snapshot on gap
        |
      emits canonical Tick/Snapshot to broker
        v
[NATS JetStream] subjects: market.raw, market.ticks.{shard}
        |\
        | \→ [Snapshotter] → Redis or PostgreSQL (latest per product)
        |                     \
        |                      → MinIO (batched snapshots for replay)
        |
   [Gateway (WS)]
    - per-product subscribe
    - send SNAPSHOT then INCR
    - backfill from JetStream starting at last_seq+1
    - per-client token bucket; connection draining
        v
     Clients (browser/CLI/services)

Infra: Prometheus/Grafana, OpenTelemetry; Helm on Minikube; Ingress (NGINX) with graceful drain.
```

## Core Components

* **Ingestor (Coinbase Adapter)**

  * Connects to `wss://ws-feed.exchange.coinbase.com` (public). Optional failover to `wss://ws-direct.exchange.coinbase.com` (authenticated, lower latency).
  * Subscribes to configurable channels per product: minimally `ticker` + `heartbeat`; optionally `level2` or `level2_batch` for stronger BBO correctness.
  * Tracks `sequence` (per product). If a gap is detected, enqueue incoming messages for that product, fetch a REST **order‑book snapshot**, fast‑forward replay, then resume.
  * Emits **canonical `Tick`** events (see Data Models) to `market.ticks.{shard}` and occasional **`Snapshot`** when beneficial (e.g., post‑resync).
* **Normalizer & Sharder**

  * Validates raw messages, maps to canonical schema, stamps `ts_ingest`, and asserts monotonic `seq` per product.
  * Shards by `hash(product) % N` to preserve per‑product ordering.
  * Publishes to `market.ticks.{shard}` via **JetStream** (preferred) or **Redis Streams** (alt). An adapter layer allows swapping brokers.
* **Snapshotter**

  * Maintains rolling per‑product state (last trade, best bid/ask, last\_seq, etc.).
  * Writes **latest snapshot** to **Redis** (hash per product) or **PostgreSQL** (table keyed by `product`), with `version`, `last_seq`, `ts_snapshot`.
  * Periodically batches snapshots to **MinIO** for historical replay (`minio://md-snapshots/YYYY/MM/DD/...`).
* **Gateway (FastAPI WebSockets)**

  * Client protocol: subscribe/unsubscribe; optional `from_seq` for backfill; heartbeats.
  * On subscribe: fetch snapshot from Redis/PostgreSQL, then stream deltas from JetStream starting at `snapshot.last_seq + 1`.
  * Implements per‑client rate limits (token bucket) and per‑symbol throttle.
  * Graceful rollout: preStop drain, readiness gates, and NGINX ingress connection draining/timeouts.
* **Backfill/Replayer**

  * On reconnect, clients pass `from_seq` per product; server streams retained deltas from JetStream. If retention exceeded, send a fresh snapshot and resume live.
* **Observability**

  * Metrics: ingest lag, dropped msgs, resync count, snapshot latency, connected clients, msgs/sec per product.
  * Tracing across ingest → normalize → gateway; logs as JSON with correlation ids.

## Data Models (canonical)

```json
// Tick (incremental)
{
  "v": 1,
  "type": "tick",
  "product": "BTC-USD",
  "seq": 1234567,              // Coinbase per-product sequence (canonical)
  "ts_event": 1735942854123456,
  "ts_ingest": 1735942854126789,
  "fields": {
    "last_trade": {"px": 65123.45, "qty": 0.01},
    "best_bid":   {"px": 65123.40, "qty": 0.5},
    "best_ask":   {"px": 65123.50, "qty": 0.6}
  }
}
```

```json
// Snapshot (point-in-time)
{
  "v": 1,
  "type": "snapshot",
  "product": "BTC-USD",
  "seq": 1234500,
  "ts_snapshot": 1735942853000000,
  "state": { /* same shape as Tick.fields, can include aggregates */ }
}
```

## Gateway WebSocket Protocol (our server → clients)

Client→Server:

* `subscribe`: `{ "op": "subscribe", "products": ["BTC-USD"], "from_seq": {"BTC-USD": 1234500}, "want_snapshot": true }`
* `unsubscribe`: `{ "op": "unsubscribe", "products": ["BTC-USD"] }`
* `ping`: `{ "op": "ping", "t": 1735942854 }`

Server→Client:

* `snapshot`: `{ "op": "snapshot", "data": Snapshot }`
* `incr`: `{ "op": "incr", "data": Tick }`
* `rate_limit": { "op": "rate_limit", "retry_ms": 1000 }`
* `pong`: `{ "op": "pong", "t": 1735942854 }`
* `error`: `{ "op": "error", "code": "BAD_REQUEST", "msg": "..." }`

> Note: This is **our** outward protocol; upstream Coinbase messages are normalized before they reach clients.

## Streams & Retention

* **JetStream** subjects: `market.raw` (optional), `market.ticks.*` (sharded). Retention window should cover expected client reconnects (e.g., 10–30 minutes). Include per‑product `seq` in payload; broker sequence is not relied on for ordering.
* **Redis Streams** (optional): one stream per shard; use consumer groups for gateway.

## Ordering & Sharding

* Guarantee ordering **per product**.
* Achieved via stable hash(product) → shard, single consumer per shard (replica count = shard count). Inside a shard, updates for the same product are serialized.

## Rate Limiting & Quotas

* **Upstream**: one ingestor controls Coinbase subscriptions. Backoff on 429 or policy errors. Limit the number of products and channels to plan limits.
* **Downstream**: token bucket per client (default 100 msgs/sec, burst 200). Enforce per‑product throttle.

## Failure, Recovery, and Resync

* **WS disconnect**: immediate exponential backoff reconnect, resubscribe with prior product set; continue sequence checks.
* **Gap detection**: if `seq` is not contiguous per product, pause emits, obtain REST book snapshot, apply queued messages with `sequence > snapshot_seq`, then resume.
* **Gateway restart**: drain, clients reconnect with `from_seq`; if outside retention, send a fresh snapshot and continue.

## Kubernetes Topology

* Namespace: `mdf`.
* Deployments:

  * `ingestor` (1–3 replicas; only one active consumer per shard via leader election or partitioning)
  * `normalizer` (HPA on msgs/sec)
  * `snapshotter` (replicas = shard count)
  * `gateway` (HPA on connections/RPS)
  * `nats` (StatefulSet) or managed Redis (optional)
* Ingress: NGINX Ingress configured for WebSockets; idle timeout ≥ 120s; connection draining ≥ gateway preStop.
* PDBs, liveness/readiness probes; gateway readiness true only after broker attach + warm cache.

## Cluster Resources

* Container registry: GitHub Container Registry (GHCR) or local Minikube registry add‑on.
* Object storage: MinIO (single‑node or distributed) for snapshot batches.
* State store for latest snapshots: Redis (AOF persistence) or PostgreSQL (via a Helm chart).

## CI/CD (GitHub Actions)

* Lint, typecheck, tests; build/push images (GHCR); helm template/validate; optional deploy to Minikube via `kubectl`/`helm`.
* Versioning: SemVer + image tag = git SHA.

## Observability

* Metrics (examples): `md_ingest_ticks_total{product}`, `md_gateway_clients{state}`, `md_resync_total{product}`, `md_snapshot_latency_ms`, `md_seq_gap_total{product}`.
* Grafana dashboards per component/shard/product; OTLP traces.

## Security & Legal

* No secrets in code; `.env.example` only. Respect Coinbase ToS/rate limits. Public market data only (no user auth flows).

## Non‑Goals (initial)

* Full depth book management for all products; cross‑region replication; archival beyond periodic object storage batches.
