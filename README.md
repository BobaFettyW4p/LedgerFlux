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

`minikube v1.37.0` or later (it is possible to deploy this infrastructure on any kubernetes cluster, but the quick start 

`make v4.4.1` or later (as a requirement for POSIX-compliance, any up to date linux distribution or Mac OS will have this installed by default)

`uv v0.9.21` or later

This project has been tested and works well on my desktop computer running Fedora and my laptop running Arch. I presume it would work equally well on other distributions, as well as on Mac or Windows (although I would probably recommend using WSL for ease of setup if using a Windows machine)

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

This projects leverages `make` in order to provide a way to stand up or tear down our infrastructure through a single command.

### make up 

The `up` make target will perform all of the steps to erect our infrastructure. It will:

- spin up a new k8s cluster via minikube with the following specs:
- 8 GB of RAM
- 4 CPUs
- 50 GB of disk space (this project has a cron job that automatically cleans up all data older than an hour. If you run your project with all 3 default coins, the project should be configured so it never runs out of space)
NOTE: I haven't tested this with an existing minikube cluster. Verify this with `minikube status`

It will also build all of the needed docker images and deploy pods in kubernetes via `skaffold`.

Once constructed, all pods should fully visible and functional in the `ledgerflux` namespace. To view the status:

```bash
kubectl get pods -n ledgerflux
```

### make [test|lint|typecheck]

This project leverages `pytest` in order to perform unit testing. The `make test` target will initiate our test suite and will perform full unit testing.

We use `ruff` to enforce linting. The `make lint` target will ensure our project adheres to best practices for production python code.

Finally, we leverage `make mypy` to enforce type-checking on our repository. `ty` was released while I was working on this project, so I did not use it, but I have heard good things about it, and have greatly enjoyed all releases from Astral Labs I have used up to this point (`uv` and `ruff` are both Astral Labs creations!).

I often said there were three hard problems in computer science: cache invalidation, naming things, and python package management. They're in the process of solving one of these problems, in my humble opinion. (if you're reading this and from Astral Labs, please hire me. I would love to fix the python ecosystem with you)

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

 In our infrastructure, the Ingestor connects to the Coinbase Websocket and forwards messages to NATS Jetstream, which serves as a message broker. Jetstream conveys these messages to the Normalizers, which validates each tick, calculates the shard it should reside on, and then publish that tick onto the appropriate Jetstream stream to ensure it is sent to the appropriate snapshotter. The snapshotter then writes every tick to the `tick_history` table in the postgres database. When clients subscribe to specific feeds via the gateway, they are read up to date price data directly from postgres.

### Ingestor

This component connects to the websocket data feed from Coinbase, and prepares it for transportation via Jetstream. It subscribes to the Coinbase feed, as well as the market_ticks NATS Jetstream stream to broker messages

By default, the ingestor will subscribe to the websocket feed for Bitcoin (BTC-USD), Ethereum (ETH-USD) and Cardano (ADA-USD). These are relatively popular cryptocurrencies with relatively consistent and high trading volume, making them a good demonstration of the capabilities of this system. It is possible to modify these values by modifying the source json for the configMap for the kubernetes pod, located at `k8s/services/configs/ingestor.json`. NOTE: if you modify the list of subscribed products, the market data dashboards are not set up to handle that. Do it at your own peril!

#### Why Coinbase?

When I was originally conceptualizing and planning out the project, I wanted to utilize FIX data. While this project attempts to mirror production workflows, it does not have the capital-backing of a production trading infrastructure, and so any FIX feed utilized would have to be free of cost.

When searching different market feeds, I found documentation that led me to believe Coinbase's FIX feed would be free to access, and thus perfect for the project. 

After struggling beginning architecting the system around the Coinbase FIX database, and subsequently struggling to establish a connection, after exploring the Coinbase documentation thorouhly, I was able to determine that Coinbase requires a business account in order to access the FIX feed, a requirement which includes a monthly trading volume in Coinbase.

Until relatively recently, crypto markets didn't rely on FIX the way traditional securities and markets do. Simple websocket feeds, like the one Coinbase provides free of charge and without authentication requirements, were used for many years in the early years of crypto to provide pricing data to prospective crypto traders. This has changed, but I have been led to believe that the websocket feeds are still used to track crypto prices by professional traders to this day.

Therefore, while this was not part of the original plan for this project, it is an acceptable middle ground that allows us to demonstrate the architecture

## NATS Jetstream

While Kafka is the generally accepted standard for message brokers in the current age, NATS Jetstream has certain advantages that made it a better option for this project. First, NATS Jetstream is significantly leaner and easier to set up and configure. While configuring this project to use Kafka (and the complexity it brings) would be a worthwhile exercise, selecting Jetstream let us configure a message broker quickly and focus on the more interesting components of the project. In addition, Jetstream's focus on speed and low overhead make it a natural selection for this pseudo-production trading architecture. While certain components of trading systems are more suited for Kafka (a market maker who handles thousands of transactions a second may prefer to use Kafka in order to safely record each of these transactions), I thnk Jetstream is a perfectly suitable choice for our project. It serves as a message broker with multiple streams that conveys messages between each of our components. Different components will subscribe to and publish messages on different streams in order to keep them separated.

## Normalizer

The normalizer receives incoming ticks from Jetstream and ensures they meet standards: that all appropriate fields are present, that sequence numbers are logical (i.e. the sequence number for any received tick is higher than the previous received tick), and that asks and bids make logical sense. One of the downsides of using the Coinbase websocket feed instead of a FIX-based connection is that the websocket feeds are "best-effort", it is not reasonable to expect every single tick to be received, which means there will be gaps between sequence numbers, and sometimes large gaps between sequence numbers. As such, we only check that sequence numbers continue increasing in size.

As construed, the normalizer runs as a StatefulSet with 4 replicas. Every subscribed product hashes to a specific normalizer, and all ticks for that product will be forwarded to the appropriate normalizer. This project was originally created with 3 replicas, as with ticks from 3 separate products, with 3 unique hash targets, each product should hash to a different normalizer in expectation. In practice, two products hashed to the same normalizer, and while this had no impact on functionality, it left one completely unused. I opted to bump the number to 4, still leaving one unused, but yielding the desired behavior of each product hashing to a unique normalizer.

## Snapshotter

The snapshotter receives incoming tickets from each normalizer containing verified market data. It writes every tick to the postgreSQL, which is referenced by the gateway in order to send regular updates to subscribed clients. When architecting a system like this, in most case, price data will largely be considered ephemeral, and the need for long term storage is not necessary. In this case, a NoSQL database like Redis or MongoDB would be a good choice. However, I felt very weak in my skillset regarding RDMBS's like PostgreSQL and wanted to get experience designing and implementing them. While the benefits and tradeoffs that the ACID transactions Postgres offers you may not align perfectly with the needs of the project, as an educational endeavor, I think it hit the mark

### Postgres Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SNAPSHOTS                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│ PK  product        TEXT           NOT NULL   (e.g., BTC-USD)                │
│     version        INT            NOT NULL   Schema version                 │
│     last_seq       BIGINT         NOT NULL   Last sequence number           │
│     ts_snapshot    BIGINT         NOT NULL   Snapshot timestamp (ns)        │
│     state          JSONB          NOT NULL   Complete market state          │
│     created_at     TIMESTAMP      DEFAULT CURRENT_TIMESTAMP                 │
│     updated_at     TIMESTAMP      DEFAULT CURRENT_TIMESTAMP                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ INDEX: idx_snapshots_ts ON (ts_snapshot)                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ product (implicit relationship)
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             TICK_HISTORY                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ PK  id             BIGSERIAL      AUTO       Primary key                    │
│     product        VARCHAR(20)    NOT NULL   Product identifier             │
│     timestamp      TIMESTAMPTZ    NOT NULL   DB insertion time (DEFAULT NOW)│
│     sequence       BIGINT         NOT NULL   Coinbase sequence number       │
│     price          NUMERIC(18,8)  NULLABLE   Last trade price               │
│     bid            NUMERIC(18,8)  NULLABLE   Best bid price                 │
│     ask            NUMERIC(18,8)  NULLABLE   Best ask price                 │
│     volume         NUMERIC(18,8)  NULLABLE   Trade volume/size              │
│     ts_event       BIGINT         NULLABLE   Event timestamp (ns)           │
│     ts_ingest      BIGINT         NULLABLE   Ingestion timestamp (ns)       │
├─────────────────────────────────────────────────────────────────────────────┤
│ INDEX: idx_tick_history_product_time ON (product, timestamp DESC)           │
│ INDEX: idx_tick_history_timestamp ON (timestamp DESC)                       │
│ INDEX: idx_tick_history_product_seq ON (product, sequence)                  │
│ UNIQUE: idx_tick_history_unique ON (product, sequence, timestamp)           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ source for views
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LATEST_PRICES (VIEW)                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│     product        VARCHAR(20)    Most recent price per product             │
│     price          NUMERIC(18,8)  Last trade price                          │
│     bid            NUMERIC(18,8)  Best bid price                            │
│     ask            NUMERIC(18,8)  Best ask price                            │
│     volume         NUMERIC(18,8)  Trade volume                              │
│     ts_event       BIGINT         Event timestamp                           │
│     timestamp      TIMESTAMPTZ    Record timestamp                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ QUERY: DISTINCT ON (product) ... ORDER BY timestamp DESC                    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                    PRICE_STATS_1MIN (MATERIALIZED VIEW)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│     product        VARCHAR(20)    Product identifier                        │
│     time_bucket    TIMESTAMPTZ    1-minute time bucket                      │
│     tick_count     BIGINT         Number of ticks in interval               │
│     avg_price      NUMERIC        Average price                             │
│     min_price      NUMERIC        Minimum price (Low)                       │
│     max_price      NUMERIC        Maximum price (High)                      │
│     open_price     NUMERIC        First price (Open)                        │
│     close_price    NUMERIC        Last price (Close)                        │
│     avg_volume     NUMERIC        Average volume                            │
├─────────────────────────────────────────────────────────────────────────────┤
│ INDEX: idx_price_stats_product_time ON (product, time_bucket)               │
└─────────────────────────────────────────────────────────────────────────────┘
```

While there is a logical relationship between both tables in our database (through the `product` key), they are not directly linked by a foreign key. This allows for a quicker lookup on each table, helping us compensate for the weaknesses of the RDBMS approach in our infrastructure.

## Gateway

The gateway provides clients a websocket-based method to subscribe to particular financial instruments and receive regular updates. Subscribed clients receive incremental updates from Jetstream. It leverages a token-bucket based rate limiter to better manage load, and uses `fastapi` and `uvicorn` to maintain asynchronous operation.

### Gateway quick-start

`make up` does not create a fully-active gateway as that requires forwarding a port in order to avoid clashing with any currently open ports. If port 8000 is not in use on your system, start the gatway with:

```bash
make gateway-ui
```

Once complete, there will be a simple landing page at http://localhost:8000 in your browser outlining how to connect to the gateway to subscribe for updates. You may also use the `test_client.py` present in the root of this directory to establish such connections.


## Observability

Open Grafana to view market data and system health. If port 3000 is not in use on your machine:

```bash
make grafana
```

This will automatically open Grafana in your browser at `http://localhost:3000`. Login with `admin` / `admin`.

Available dashboards:
- **LedgerFlux Market Data** - Real-time price charts, bid/ask spreads, trading volume
- **LedgerFlux System Health** - Service metrics, ingestion rates, active connections

There are also live Prometheus metrics available with the `make prometheus` target. The port exposed by this make target is 9090.


### Testing

This project has comprehensive unit test coverage for all critical business logic. All testing dependencies are automatically installed by `make install`.

#### Running Tests

```bash
# Run tests with coverage (opens HTML report in browser)
make test

# if one would prefer, the test suite can be confirmed by viewing past CI/CD runs from the Actions tab
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

