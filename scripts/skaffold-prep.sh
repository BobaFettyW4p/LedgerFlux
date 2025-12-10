#!/usr/bin/env bash

# Build all LedgerFlux images into the Docker daemon used by Skaffold.
# Defaults to Minikube's Docker environment so Skaffold does not try to pull
# nonexistent images like ledgerflux-common:latest from Docker Hub.

set -euo pipefail

PROFILE=${PROFILE:-minikube}
VERSION=${VERSION:-latest}
REGISTRY=${REGISTRY:-}
PUSH=${PUSH:-false}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "[prep] Using minikube docker-env for profile '${PROFILE}' ..."
eval "$(minikube -p "$PROFILE" docker-env)"

echo "[prep] Building images (VERSION=${VERSION} REGISTRY=${REGISTRY:-<none>} PUSH=${PUSH}) ..."
(
  cd "$REPO_ROOT"
  VERSION="$VERSION" REGISTRY="$REGISTRY" PUSH="$PUSH" ./docker/build-images.sh
)

echo "[prep] Images built into Docker daemon for profile '${PROFILE}'."
echo "[prep] Next: skaffold run -p ${PROFILE} --status-check"
