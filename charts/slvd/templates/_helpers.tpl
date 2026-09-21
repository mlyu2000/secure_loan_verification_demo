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

{{/*
=============================================================================
Zero-input deploy: secret + endpoint auto-resolution
=============================================================================
The PCAI UI form may be left COMPLETELY EMPTY for the `secrets:` block and the
engine endpoints. Resolution order per key:
  1. explicit .Values value (non-empty = operator override, always wins)
  2. cluster lookup of the credential already owned by its source app:
       litellmApiKey  -> Secret litellm-helm-masterkey (litellm chart)
       openclawToken  -> NemoClaw's openclaw.json ConfigMap (the gateway was
                         started with exactly this baked static token)
  3. deterministic derivation from release coordinates (jwtSecret, hmacSecret):
     identical across every template AND stable across upgrades (a fresh
     random per upgrade would invalidate live JWTs + approval links).
     Demo-scoped; form input still overrides.
CRITICAL (verified on CS1, helm 3.16): cluster-wide lookup (namespace "")
returns NIL for Service/Secret/ConfigMap under the import identity while
NAMESPACE-scoped lookup works. Every lookup below therefore iterates
candidate namespaces explicitly — NEVER "". Also: `lookup` returns nothing
during `helm template`/lint and during CLIENT dry-run — verify with a real
`helm install`.
=============================================================================
*/}}

{{- define "slvd.secretLookup" -}}
{{- /* args: (dict "root" $ "name" $secretName "key" $dataKey). Namespace-
       iterated Secret lookup; returns the decoded value or "". */ -}}
{{- $root := index . "root" -}}
{{- $name := index . "name" -}}
{{- $key := index . "key" -}}
{{- $found := "" -}}
{{- range $ns := list $root.Release.Namespace "project-user-aieadmin" "nemoclaw" "default" -}}
  {{- if not $found -}}
    {{- $ss := lookup "v1" "Secret" $ns $name -}}
    {{- if $ss -}}
      {{- /* explicit-name lookup returns the object itself, NOT a List */ -}}
      {{- $data := default (dict) $ss.data -}}
      {{- if hasKey $data $key -}}
        {{- $found = b64dec (get $data $key) -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- $found -}}
{{- end -}}

{{- define "slvd.configmapRegexLookup" -}}
{{- /* args: (dict "root" $ "name" $cmName "key" $dataKey "re" $regex). First
       full regex match inside data[key] of a namespace-iterated ConfigMap. */ -}}
{{- $root := index . "root" -}}
{{- $name := index . "name" -}}
{{- $key := index . "key" -}}
{{- $re := index . "re" -}}
{{- $found := "" -}}
{{- range $ns := list $root.Release.Namespace "project-user-aieadmin" "nemoclaw" "default" -}}
  {{- if not $found -}}
    {{- $cms := lookup "v1" "ConfigMap" $ns $name -}}
    {{- if $cms -}}
      {{- $data := default (dict) $cms.data -}}
      {{- if hasKey $data $key -}}
        {{- $ms := regexFindAll $re (get $data $key) -1 -}}
        {{- if $ms -}}{{- $found = index $ms 0 -}}{{- end -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- $found -}}
{{- end -}}

{{- define "slvd.detectSvc" -}}
{{- /* args: (dict "root" $ "name" $svcName) -> "<name>.<ns>.svc.cluster.local"
       or "" — namespace-iterated Service lookup. */ -}}
{{- $root := index . "root" -}}
{{- $name := index . "name" -}}
{{- $found := "" -}}
{{- range $ns := list $root.Release.Namespace "project-user-aieadmin" "nemoclaw" "default" -}}
  {{- if not $found -}}
    {{- $svcs := lookup "v1" "Service" $ns $name -}}
    {{- if $svcs -}}
      {{- $found = printf "%s.%s.svc.cluster.local" $svcs.metadata.name $svcs.metadata.namespace -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- $found -}}
{{- end -}}

{{/*
Endpoint auto-detection: when the owning service exists in-cluster, resolve
its FQDN instead of trusting a possibly-stale form value. "" => keep values.yaml.
*/}}
{{- define "slvd.openclawUrl" -}}
{{- $host := include "slvd.detectSvc" (dict "root" . "name" "nemoclaw-openclaw") -}}
{{- if $host -}}{{- printf "ws://%s:80" $host -}}{{- end -}}
{{- end -}}

{{- define "slvd.llmBaseUrl" -}}
{{- $host := include "slvd.detectSvc" (dict "root" . "name" "litellm-helm") -}}
{{- if $host -}}{{- printf "http://%s:4000/v1" $host -}}{{- end -}}
{{- end -}}

{{- define "slvd.secret.litellmApiKey" -}}
{{- if .Values.secrets.litellmApiKey -}}
  {{- .Values.secrets.litellmApiKey -}}
{{- else -}}
  {{- include "slvd.secretLookup" (dict "root" . "name" "litellm-helm-masterkey" "key" "masterkey") -}}
{{- end -}}
{{- end -}}

{{- define "slvd.secret.openclawToken" -}}
{{- if .Values.secrets.openclawToken -}}
  {{- .Values.secrets.openclawToken -}}
{{- else -}}
  {{- /* 0.2.x bakes the static gateway token into openclaw.json
         ("token": "<hex>") — regexFindAll returns the full match; trim it. */ -}}
  {{- $m := include "slvd.configmapRegexLookup" (dict "root" . "name" "nemoclaw-openclaw-openclaw-config" "key" "openclaw.json" "re" "\"token\": \"[a-f0-9]{16,}\"") -}}
  {{- if $m -}}
    {{- $m | trimPrefix "\"token\": \"" | trimSuffix "\"" -}}
  {{- else -}}
    {{- include "slvd.secretLookup" (dict "root" . "name" "nemoclaw-openclaw-gateway-token" "key" "token") -}}
  {{- end -}}
{{- end -}}
{{- end -}}

{{- define "slvd.secret.jwtSecret" -}}
{{- if .Values.secrets.jwtSecret -}}
  {{- .Values.secrets.jwtSecret -}}
{{- else -}}
  {{- sha256sum (printf "slvd-jwt|%s|%s" .Release.Namespace .Release.Name) -}}
{{- end -}}
{{- end -}}

{{- define "slvd.secret.hmacSecret" -}}
{{- if .Values.secrets.hmacSecret -}}
  {{- .Values.secrets.hmacSecret -}}
{{- else -}}
  {{- sha256sum (printf "slvd-hmac|%s|%s" .Release.Namespace .Release.Name) -}}
{{- end -}}
{{- end -}}
