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

log "building mycel:$TAG"
docker build --target app -t "mycel:$TAG" "$ROOT"

log "loading it into minikube (this takes a minute)"
minikube image load "mycel:$TAG"
log "mycel:$TAG is on the node"
