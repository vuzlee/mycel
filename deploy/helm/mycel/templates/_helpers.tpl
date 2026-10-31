{{/*
Names and labels, defined once.

A chart that writes `app: mycel` by hand in nine files has nine chances to disagree with
itself, and a Service whose selector disagrees with its Deployment matches no pods while
looking entirely correct.
*/}}

{{- define "mycel.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "mycel.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Everything a pod carries. Kubernetes reads none of these; people and Prometheus do. */}}
{{- define "mycel.labels" -}}
app.kubernetes.io/name: {{ include "mycel.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/*
The selector, and ONLY the selector. A Deployment's selector is immutable after creation,
so anything that changes between releases — the version, the chart revision — must stay
out of it or the next `helm upgrade` fails with a field that cannot be patched.
Call as: include "mycel.selectorLabels" (dict "ctx" . "component" "api")
*/}}
{{- define "mycel.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mycel.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* The image. An empty tag falls back to appVersion, which is what CI bumps. */}}
{{- define "mycel.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
{{- end -}}

{{/*
ConfigMap, then Secret. The Secret holds all of .env and wins collisions, so a value that
must hold in the cluster goes in the container's own `env:` (mycel.env).
*/}}
{{- define "mycel.envFrom" -}}
envFrom:
  - configMapRef:
      name: {{ include "mycel.fullname" . }}-config
  - secretRef:
      name: {{ .Values.secret.name }}
{{- end -}}

{{/*
Store hosts, METRICS_HOST and a per-component pool as container `env:`, which outranks the
Secret. Each store has its own host, defaulting to externalStores.host: one machine on
minikube, one Service per store in a cluster. Fails to render with neither.
Usage: include "mycel.env" (dict "ctx" . "metrics" true "pool" .Values.api.dbPool)
*/}}
{{- define "mycel.storeHost" -}}
{{- $s := .ctx.Values.externalStores -}}
{{- required (printf "externalStores.%s or externalStores.host must name where it runs" .store) (index $s .store | default $s.host) -}}
{{- end -}}

{{- define "mycel.env" -}}
{{- $s := .ctx.Values.externalStores -}}
env:
  - {name: POSTGRES_HOST, value: {{ include "mycel.storeHost" (dict "ctx" .ctx "store" "postgres") | quote }}}
  - {name: POSTGRES_PORT, value: {{ $s.postgresPort | quote }}}
  - {name: RABBITMQ_HOST, value: {{ include "mycel.storeHost" (dict "ctx" .ctx "store" "rabbitmq") | quote }}}
  - {name: QDRANT_URL, value: {{ printf "http://%s:6333" (include "mycel.storeHost" (dict "ctx" .ctx "store" "qdrant")) | quote }}}
  - {name: S3_ENDPOINT_URL, value: {{ printf "http://%s:9000" (include "mycel.storeHost" (dict "ctx" .ctx "store" "minio")) | quote }}}
  - {name: LITELLM_BASE_URL, value: {{ printf "http://%s:4000" (include "mycel.storeHost" (dict "ctx" .ctx "store" "litellm")) | quote }}}
  {{- if .metrics }}
  - {name: METRICS_HOST, value: "0.0.0.0"}
  {{- end }}
  {{- with .pool }}
  - {name: DB_POOL_SIZE, value: {{ .size | quote }}}
  - {name: DB_MAX_OVERFLOW, value: {{ .overflow | quote }}}
  {{- end }}
{{ include "mycel.envFrom" .ctx }}
{{- end -}}

{{/* The pull secret, when one is set. Every pod uses it, so all pulls share one login. */}}
{{- define "mycel.pullSecrets" -}}
{{- with .Values.image.pullSecret }}
imagePullSecrets:
  - name: {{ . }}
{{- end }}
{{- end -}}
