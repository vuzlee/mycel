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
Every container's environment, identical across the three. Both sources are mounted whole
rather than key by key: a new setting then reaches the pods by changing one ConfigMap, not
by editing three Deployments and remembering all of them.

ORDER MATTERS, and it cost a debugging round. The Secret is created with
`--from-env-file=.env`, so it carries ALL of that file — the settings as well as the keys —
and `secretRef` listed second wins every collision. A value the ConfigMap sets for cluster
conditions is therefore silently replaced by whatever the developer's own .env said.

Anything that MUST hold regardless goes in the container's own `env:`, which outranks both.
METRICS_HOST is the case that found this.
*/}}
{{- define "mycel.envFrom" -}}
envFrom:
  - configMapRef:
      name: {{ include "mycel.fullname" . }}-config
  - secretRef:
      name: {{ .Values.secret.name }}
{{- end -}}
