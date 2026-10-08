#!/usr/bin/env bash
#
# Keep the chart's copy of the Grafana files in step with deploy/grafana/.
#
#   scripts/stack.sh grafana-sync            copy
#   scripts/stack.sh grafana-sync --check    fail if they differ (CI runs this)
#
# The copy is forced, not chosen. Helm's .Files.Get does not follow symlinks — it reads
# the link target as a string, so a symlinked datasources.yaml renders a ConfigMap holding
# a path and Grafana starts cleanly with NO DATASOURCES. That failure looks like a Grafana
# problem, which is the expensive kind.
#
# deploy/grafana/ is the original because docker-compose.yml mounts that directory and has
# for several batches. Moving it to make the chart tidier moves the thing that is running.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

src="$ROOT/deploy/grafana"
dst="$ROOT/deploy/helm/mycel/files"
drift=0

pairs=(
  "$src/datasources/datasources.yaml:$dst/datasources.yaml"
  "$src/dashboards/dashboards.yaml:$dst/dashboards.yaml"
  "$src/dashboards/mycel.json:$dst/mycel.json"
)

for pair in "${pairs[@]}"; do
  from="${pair%%:*}" to="${pair##*:}"
  cmp -s "$from" "$to" && continue
  drift=1
  if [[ ${1:-} == "--check" ]]; then
    echo "drifted: ${to#"$ROOT/"} is not ${from#"$ROOT/"}"
  else
    cp "$from" "$to"
    echo "copied:  ${from#"$ROOT/"} -> ${to#"$ROOT/"}"
  fi
done

if [[ ${1:-} == "--check" ]]; then
  (( drift )) && die "grafana files have drifted; run: scripts/stack.sh grafana-sync"
  echo "grafana files match"
elif (( ! drift )); then
  echo "grafana files already match"
fi
