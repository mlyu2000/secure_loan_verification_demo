{{- define "slvd.labels" -}}
app.kubernetes.io/part-of: slvd
app.kubernetes.io/managed-by: Helm
{{- end -}}

{{- define "slvd.fullname" -}}
slvd
{{- end -}}
