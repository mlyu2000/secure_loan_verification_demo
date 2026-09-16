# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

{{- define "nemoclaw.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nemoclaw.fullname" -}}
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

{{- define "nemoclaw.labels" -}}
{{- include "nemoclaw.selectorLabels" . }}
{{- end }}

{{- define "nemoclaw.selectorLabels" -}}
hpe-ezua/app: {{ include "nemoclaw.fullname" . }}
app.kubernetes.io/name: {{ include "nemoclaw.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "nemoclaw.startScript" }}
#!/bin/sh
set -x
echo "Starting OpenClaw with automatic device approval..."

# Run openclaw onboard with auto-approval for device creation
echo "Running openclaw onboard with auto-approval..."
openclaw onboard --non-interactive --accept-third-party-software || echo "Onboarding may have already completed"

# Create device with auto-approval mode
echo "Creating device with auto-approval..."
openclaw devices create nemoclaw-device --role operator --approval-mode auto --json 2>/dev/null || echo "Device may already exist"

# Wait for device to be created and approved
sleep 3

# Verify device was created
echo "Verifying device status..."
openclaw devices list 2>/dev/null || echo "Device listing not available"

# Start gateway
echo "Starting gateway..."
openclaw gateway run 2>&1 &

echo "Gateway started with automatic pairing"
tail -f /dev/null
{{- end }}
