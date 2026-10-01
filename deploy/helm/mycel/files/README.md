# Copies, and that is a decision

Three files copied from `deploy/grafana/`, which is where compose provisions them from.

**Why a copy and not a symlink:** Helm's `.Files.Get` does not follow symlinks — it reads
them as the link target string and the ConfigMap comes out holding `../../../grafana/...`
rather than a datasource. The symlink was tried first; it renders a one-line ConfigMap and
a Grafana with no datasources, which looks like a Grafana problem.

**Why not point compose at these instead** and have one copy: compose mounts a whole
directory, and that directory is `deploy/grafana/` by the same path in both
`docker-compose.yml` and this chart's README. Moving it to make the chart tidier moves it
out from under the thing that has been running for several batches.

**So they can drift**, and the drift is invisible until somebody opens a dashboard. The
one guard is `dashboards.yaml` setting `allowUiUpdates: false`: a panel dragged about in
the browser is gone on restart, so the file stays the original in both places.

If a dashboard changes, change `deploy/grafana/` and copy here. Two copies of three small
files is the cheapest of the available wrong answers.
