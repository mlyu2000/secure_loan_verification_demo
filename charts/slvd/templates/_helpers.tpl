{{- define "slvd.labels" -}}
app.kubernetes.io/part-of: slvd
app.kubernetes.io/managed-by: Helm
{{- end -}}

{{- define "slvd.fullname" -}}
slvd
{{- end -}}

{{/*
HPE EZUA labels — required on workload pods so the EzAppConfig controller can
query pod health and register the app on the PCAI UI.
hpe-ezua/app must equal the EzAppConfig spec.name ("slvd").
*/}}
{{- define "hpe-ezua.labels" -}}
hpe-ezua/app: {{ .Values.ezua.appName }}
hpe-ezua/type: {{ .Values.ezua.type }}
hpe-ezua/component: app
{{- end -}}
