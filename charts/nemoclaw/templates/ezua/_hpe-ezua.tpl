# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

{{/* Labels for HPE ezua */}}
{{- define "hpe-ezua.labels" -}}
hpe-ezua/app: {{ .Release.Name }}
hpe-ezua/type: ai-application
{{- end }}

{{/* Common labels */}}
{{- define "nemoclaw.commonLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
