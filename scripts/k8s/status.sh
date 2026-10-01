#!/usr/bin/env bash
#
# The pods, and the addresses they answer on.
#
# Both hostnames resolve through /etc/hosts, not DNS. Without the entries, curl with an
# explicit Host header still works — which is how to tell an Ingress problem apart from a
# hosts-file one.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

need kubectl

if ! minikube status --format '{{.Host}}' 2>/dev/null | grep -q Running; then
  echo "minikube is not running — scripts/stack.sh k8s up"
  exit 0
fi

kubectl get pods -l "app.kubernetes.io/instance=mycel" \
  -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,STATUS:.status.phase \
  2>/dev/null || true

ip=$(minikube ip 2>/dev/null || true)
[[ -n $ip ]] || exit 0

echo
echo "minikube   $ip"
echo "app        http://mycel.local/app/"
if kubectl get deploy mycel-mycel-grafana >/dev/null 2>&1; then
  echo "grafana    http://grafana.mycel.local"
fi
echo
echo "both need an /etc/hosts line:"
echo "  $ip  mycel.local grafana.mycel.local"
