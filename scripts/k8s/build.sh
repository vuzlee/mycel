#!/usr/bin/env bash
#
# Build the image and put it where the cluster can see it.
#
# `minikube image load`, not a registry: the cluster's docker daemon is not the host's, so
# an image built here is invisible there until it is loaded. That is also why
# values-minikube.yaml sets `pullPolicy: Never` — IfNotPresent would still try to pull on
# a cache miss, and the error names a registry nobody set up.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

need docker
need minikube

TAG=${1:-dev}

# Two images from one Dockerfile: the app, and ingest with docling and its models baked in.
for pair in "app:mycel" "ingest:mycel-ingest"; do
  target=${pair%%:*} name=${pair#*:}
  log "building $name:$TAG"
  docker build --target "$target" -t "$name:$TAG" "$ROOT"
  log "loading $name:$TAG into minikube"
  # Removed first: a load onto an existing tag can keep the old image, and the pods then
  # run stale code while everything reports success.
  minikube image rm "$name:$TAG" >/dev/null 2>&1 || true
  minikube image load "$name:$TAG"
  want=$(docker image inspect --format '{{.Id}}' "$name:$TAG")
  minikube image ls --format json 2>/dev/null | grep -q "\"$want\"" \
    || die "$name:$TAG on the node is not the image just built (${want:7:12})"
done
log "mycel:$TAG and mycel-ingest:$TAG are on the node"
