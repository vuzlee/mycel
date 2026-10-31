{{/*
One store = one Deployment + one Service, the same shape seven times.
Service name = the store's name, so the app reaches `postgres:5432` with no prefix.
*/}}

{{- define "stores.labels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/part-of: mycel
app.kubernetes.io/managed-by: {{ .ctx.Release.Service }}
{{- end -}}

{{- define "stores.selector" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
{{- end -}}

{{/* Call as: include "stores.service" (dict "ctx" . "name" "postgres" "ports" (list (list "pg" 5432))) */}}
{{- define "stores.service" -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ .name }}
  labels:
    {{- include "stores.labels" . | nindent 4 }}
spec:
  selector:
    {{- include "stores.selector" . | nindent 4 }}
  ports:
    {{- range .ports }}
    - {name: {{ index . 0 }}, port: {{ index . 1 }}, targetPort: {{ index . 1 }}}
    {{- end }}
{{- end -}}

{{/* Deployment head up to the container list. Recreate: two pods on one emptyDir store make two stores. */}}
{{- define "stores.deploymentHead" -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .name }}
  labels:
    {{- include "stores.labels" . | nindent 4 }}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector:
    matchLabels:
      {{- include "stores.selector" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "stores.labels" . | nindent 8 }}
    spec:
      # Off: every Service would land in every pod as FOO_PORT=tcp://..., which some
      # images read as their own setting.
      enableServiceLinks: false
      {{- include "stores.pullSecrets" .ctx | nindent 6 }}
{{- end -}}

{{/* The pull secret, when one is set: every store pulls with the same login. */}}
{{- define "stores.pullSecrets" -}}
{{- with .Values.pullSecret }}
imagePullSecrets:
  - name: {{ . }}
{{- end }}
{{- end -}}
