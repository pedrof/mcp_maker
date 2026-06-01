{{- define "forge.fullname" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "forge.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{ include "forge.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "forge.selectorLabels" -}}
app.kubernetes.io/name: forge
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "forge.secretName" -}}
{{- if .Values.existingSecret -}}
{{ .Values.existingSecret }}
{{- else -}}
{{ include "forge.fullname" . }}-secrets
{{- end }}
{{- end }}
