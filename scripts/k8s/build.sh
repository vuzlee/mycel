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
  minikube image load "$name:$TAG"
done
log "mycel:$TAG and mycel-ingest:$TAG are on the node"
