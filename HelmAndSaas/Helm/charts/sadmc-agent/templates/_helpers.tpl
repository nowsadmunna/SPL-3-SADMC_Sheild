{{/*
Expand the name of the chart.
*/}}
{{- define "sadmc-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "sadmc-agent.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "sadmc-agent.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "sadmc-agent.labels" -}}
helm.sh/chart: {{ include "sadmc-agent.chart" . }}
{{ include "sadmc-agent.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "sadmc-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sadmc-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
────────────────────────────────────────────────────────────────────────────────
PROMETHEUS AUTO-DETECTION (Helm lookup)
Helm's lookup function queries the live Kubernetes API at helm install/upgrade
time. It returns an empty dict during `helm template` dry-runs (no cluster).
────────────────────────────────────────────────────────────────────────────────
*/}}

{{/*
Scan the cluster for an existing Prometheus Service.
Returns JSON: {"exists": bool, "url": string}
*/}}
{{- define "sadmc-agent.prometheus.detect" -}}
{{- $result := dict "exists" false "url" "" -}}
{{- $locations := list
    (list "monitoring"    "kube-prometheus-stack-prometheus")
    (list "monitoring"    "prometheus-server")
    (list "monitoring"    "prometheus-operated")
    (list "prometheus"    "prometheus-server")
    (list "default"       "prometheus")
    (list "kube-system"   "prometheus")
    (list "observability" "prometheus-server")
-}}
{{- range $locations -}}
  {{- if not (get $result "exists") -}}
    {{- $ns  := index . 0 -}}
    {{- $svc := index . 1 -}}
    {{- if (lookup "v1" "Service" $ns $svc) -}}
      {{- $_ := set $result "exists" true -}}
      {{- $_ := set $result "url" (printf "http://%s.%s.svc.cluster.local:9090" $svc $ns) -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- $result | toJson -}}
{{- end -}}

{{/*
Should the chart install its own Prometheus?
  mode=existing → never  (user provides URL)
  mode=install  → always
  mode=auto     → only when lookup finds nothing in the live cluster
Outputs "true" or empty string (falsy).
*/}}
{{- define "sadmc-agent.prometheus.shouldInstall" -}}
{{- if eq .Values.prometheus.mode "existing" -}}
{{- else if eq .Values.prometheus.mode "install" -}}
  true
{{- else -}}
  {{- $d := include "sadmc-agent.prometheus.detect" . | fromJson -}}
  {{- if not $d.exists -}}
    true
  {{- end -}}
{{- end -}}
{{- end -}}

{{/*
Effective Prometheus URL the agent should connect to.
*/}}
{{- define "sadmc-agent.prometheus.effectiveUrl" -}}
{{- if eq .Values.prometheus.mode "existing" -}}
  {{- .Values.prometheus.existingUrl -}}
{{- else if eq .Values.prometheus.mode "install" -}}
  {{- printf "http://%s-prometheus.%s.svc.cluster.local:9090" (include "sadmc-agent.fullname" .) .Release.Namespace -}}
{{- else -}}
  {{- $d := include "sadmc-agent.prometheus.detect" . | fromJson -}}
  {{- if $d.exists -}}
    {{- $d.url -}}
  {{- else -}}
    {{- printf "http://%s-prometheus.%s.svc.cluster.local:9090" (include "sadmc-agent.fullname" .) .Release.Namespace -}}
  {{- end -}}
{{- end -}}
{{- end -}}

{{/*
Effective PROMETHEUS_MODE string injected into the agent container:
  "existing" → Helm confirmed an existing Prometheus; agent skips scanning.
  "install"  → Helm installed Prometheus; agent uses INSTALLED_PROMETHEUS_URL.
  "auto"     → dry-run or unknown; agent does its own runtime scan as fallback.
*/}}
{{- define "sadmc-agent.prometheus.effectiveMode" -}}
{{- if eq .Values.prometheus.mode "existing" -}}
  existing
{{- else if eq .Values.prometheus.mode "install" -}}
  install
{{- else -}}
  {{- $d := include "sadmc-agent.prometheus.detect" . | fromJson -}}
  {{- if $d.exists -}}
    existing
  {{- else if include "sadmc-agent.prometheus.shouldInstall" . -}}
    install
  {{- else -}}
    auto
  {{- end -}}
{{- end -}}
{{- end -}}
