#!/usr/bin/env bash

# Build all LedgerFlux service images with a single command.
#
# Usage:
#   ./docker/build-images.sh                 # builds local images with tag :latest
#   VERSION=v0.1.0 ./docker/build-images.sh  # picks a different tag
#   REGISTRY=myrepo/ ./docker/build-images.sh     # prefix images (e.g., GHCR)
#   PUSH=true REGISTRY=... ./docker/build-images.sh  # also push built images
#
# Notes:
# - Service Dockerfiles accept BASE_IMAGE build-arg; we pass the built common.

set -euo pipefail

VERSION=${VERSION:-latest}
REGISTRY=${REGISTRY:-}
PUSH=${PUSH:-false}
DOCKER_BUILDKIT=1

# Resolve script directory for referencing Dockerfiles regardless of CWD
# this is also needed to build images, otherwise the build can't find the pyproject.toml file, so uv conks out
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

img() {
  printf "%s%s:%s" "$REGISTRY" "$1" "$VERSION"
}

say() { echo "[build] $*"; }

say "Building common base image ..."
docker build \
  -f "$SCRIPT_DIR/Dockerfile.common" \
  -t "$(img ledgerflux-common)" \
  "$ROOT_DIR"

# Also tag as :latest if VERSION is not latest to satisfy FROM defaults locally
if [[ "$VERSION" != "latest" ]]; then
  say "Tagging common as ledgerflux-common:latest for local FROM compatibility"
  docker tag "$(img ledgerflux-common)" "${REGISTRY}ledgerflux-common:latest"
fi

BASE_ARG="--build-arg BASE_IMAGE=$(img ledgerflux-common)"

say "Building ingestor ..."
docker build \
  -f "$SCRIPT_DIR/Dockerfile.ingestor" \
  $BASE_ARG \
  -t "$(img ledgerflux-ingestor)" \
  "$ROOT_DIR"
if [[ "$VERSION" != "latest" ]]; then
  say "Tagging ingestor as :latest for local deploys"
  docker tag "$(img ledgerflux-ingestor)" "${REGISTRY}ledgerflux-ingestor:latest"
fi

say "Building normalizer ..."
docker build \
  -f "$SCRIPT_DIR/Dockerfile.normalizer" \
  $BASE_ARG \
  -t "$(img ledgerflux-normalizer)" \
  "$ROOT_DIR"

# Extra tag to match existing k8s manifests expecting :simple
say "Tagging normalizer with :simple for k8s manifests"
docker tag "$(img ledgerflux-normalizer)" "${REGISTRY}ledgerflux-normalizer:simple"
if [[ "$VERSION" != "latest" ]]; then
  say "Tagging normalizer as :latest for local deploys"
  docker tag "$(img ledgerflux-normalizer)" "${REGISTRY}ledgerflux-normalizer:latest"
fi

say "Building snapshotter ..."
docker build \
  -f "$SCRIPT_DIR/Dockerfile.snapshotter" \
  $BASE_ARG \
  -t "$(img ledgerflux-snapshotter)" \
  "$ROOT_DIR"
if [[ "$VERSION" != "latest" ]]; then
  say "Tagging snapshotter as :latest for local deploys"
  docker tag "$(img ledgerflux-snapshotter)" "${REGISTRY}ledgerflux-snapshotter:latest"
fi

say "Building gateway ..."
docker build \
  -f "$SCRIPT_DIR/Dockerfile.gateway" \
  $BASE_ARG \
  -t "$(img ledgerflux-gateway)" \
  "$ROOT_DIR"
if [[ "$VERSION" != "latest" ]]; then
  say "Tagging gateway as :latest for local deploys"
  docker tag "$(img ledgerflux-gateway)" "${REGISTRY}ledgerflux-gateway:latest"
fi

if [[ "$PUSH" == "true" ]]; then
  if [[ -z "$REGISTRY" ]]; then
    echo "PUSH=true requires REGISTRY to be set (e.g., REGISTRY=ghcr.io/org/)." >&2
    exit 1
  fi
  say "Pushing images to ${REGISTRY} with tag ${VERSION} ..."
  for name in ledgerflux-common ledgerflux-ingestor ledgerflux-normalizer ledgerflux-snapshotter ledgerflux-gateway; do
    docker push "$(img "$name")"
  done
fi

say "Done. Built images:"
for name in ledgerflux-common ledgerflux-ingestor ledgerflux-normalizer ledgerflux-snapshotter ledgerflux-gateway; do
  echo " - $(img "$name")"
done
echo " - ${REGISTRY}ledgerflux-normalizer:simple"
