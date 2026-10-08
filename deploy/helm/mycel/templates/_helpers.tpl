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
Store hosts and METRICS_HOST as container `env:`, which outranks the Secret. Fails to render
without externalStores.host. Usage: include "mycel.env" (dict "ctx" . "metrics" true)
*/}}
{{- define "mycel.env" -}}
{{- $host := required "externalStores.host must name where the stores run" .ctx.Values.externalStores.host -}}
env:
  - {name: QDRANT_URL, value: {{ printf "http://%s:6333" $host | quote }}}
  - {name: S3_ENDPOINT_URL, value: {{ printf "http://%s:9000" $host | quote }}}
  - {name: LITELLM_BASE_URL, value: {{ printf "http://%s:4000" $host | quote }}}
  {{- if .metrics }}
  - {name: METRICS_HOST, value: "0.0.0.0"}
  {{- end }}
{{ include "mycel.envFrom" .ctx }}
{{- end -}}
