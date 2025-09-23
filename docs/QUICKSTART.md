# Quick Start

Spin up LedgerFlux locally in minutes. These paths deploy NATS, PostgreSQL, MinIO, and all services, exposing the gateway via NGINX Ingress.

Prerequisites
- Docker (latest) and `kubectl`
- Either Kind (recommended for speed) or Minikube (parity with dev)

What you get
- Gateway (FastAPI WebSockets) at `http://ledgerflux.local/`
- NATS JetStream console at `http://nats.local:8222`
- MinIO Console at `http://minio.local:9001`

Estimated time
- Kind: ~2–3 minutes
- Minikube: ~3–5 minutes

## Option A: Kind (fastest)

1) Create cluster and install ingress
- `make kind-up`

2) Build and load images into the cluster
- `make kind-load`

3) Deploy and wait for readiness
- `make kind-deploy`

4) Map hostnames (once)
- Add to `/etc/hosts`: `127.0.0.1 ledgerflux.local nats.local minio.local`

5) Verify
- Open `http://ledgerflux.local/` in a browser
- Or: `curl -s http://ledgerflux.local/health`

Tear down
- `make kind-down`

## Option B: Minikube (parity)

1) Start Minikube and enable ingress
- `make minikube-up`

2) Build and load images into the cluster
- `make minikube-load`

3) Deploy and wait for readiness
- `make minikube-deploy`

4) Map hostnames (once)
- Get IP: `minikube ip`
- Add to `/etc/hosts`: `<MINIKUBE_IP> ledgerflux.local nats.local minio.local`

5) Verify
- Open `http://ledgerflux.local/` in a browser
- Or: `curl -s http://ledgerflux.local/health`

Tear down
- `make minikube-down`

## Troubleshooting

- Ingress not reachable
  - Ensure the hosts entry is set correctly (Kind uses `127.0.0.1`; Minikube uses the output of `minikube ip`).
  - Wait for the ingress controller: `kubectl get pods -n ingress-nginx` (Kind) or `minikube addons enable ingress` (Minikube).

- Images not found / ImagePullBackOff
  - Re-run the load step (`make kind-load` or `make minikube-load`).
  - Manifests use `imagePullPolicy: Never` for local images tagged `:latest`.

- Database connectivity
  - Postgres Service is `postgres:5432`. Default creds: user `postgres`, password from the `ledgerflux-postgres` Secret, database `ledgerflux`.

- Quick local check without hosts file changes
  - Port-forward gateway: `kubectl port-forward -n ledgerflux svc/gateway 8000:8000`
  - Then open `http://localhost:8000/`

