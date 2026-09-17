# Harbor — internal image registry

An on-prem cluster needs its images in-house too: no dependency on Docker Hub, no rate limits,
and images containing internal code do not go to a public registry.

## What Harbor adds beyond storing images

| | Why it is needed |
|---|---|
| Vulnerability scanning (Trivy) | blocks pushing images with critical CVEs, rescans when new CVEs land |
| Image signing (Cosign) | the cluster only runs CI-signed images — a hand-pushed one never starts |
| Proxy cache | `docker.io/postgres:16` is pulled once, then served locally |
| Retention policy | one tag per commit; without cleanup the disk fills within months |
| RBAC + audit log | who pushed which image when |

The proxy cache is the most practical reason: every third-party image in `docker-compose.yml`
(postgres, kafka, qdrant, minio, grafana, …) goes through Harbor, so the cluster can be rebuilt
even with no outbound network.

## Projects

```
mycel/           the app's images, tag = commit SHA
dockerhub/       proxy cache for docker.io
ghcr/            proxy cache for ghcr.io
```

## Tagging rule

Tag = **commit SHA**, never `latest`. `latest` lets two pods with the same manifest run
different code, and leaves rollback with no version to go back to.

## How the cluster pulls images

Harbor uses an internal TLS certificate, so every node must trust that CA — skip this and pods
land in `ImagePullBackOff` with a certificate error, not a permissions error. Credentials live in
an `imagePullSecret` (`harbor-creds` in `values.yaml`) on a read-only account: CI pushes, the
cluster only pulls.

## Deploying it

Harbor runs outside the app stack (its own compose file or chart), because it has to be alive
before the cluster can pull its first image. It is not part of the project's
`docker-compose.yml` — dev builds images locally and needs no registry.
