# Kyverno ClusterPolicy: scope the ezua vendor-label auto-injectors

## Problem (CS1, seen 2026-09-21)

The PCAI framework tiles for the SLVD and NemoClaw apps showed
`HEALTH = unknown`. Root cause chain:

1. The ezua/ezapp controllers compute pod health by querying pods labeled
   `hpe-ezua/app=<EzAppConfig spec.name>`.
2. Several cluster-wide Kyverno **mutate** policies on the platform overwrite
   `hpe-ezua/app` on EVERY pod that carries `hpe-ezua/type` (vendor pods):
   - `auto-ezua-labels` — stamps ALL vendor-service/app-service-user pods with
     `hpe-ezua/app=ai-vulnerability-scanner` (created 2026-08-24 to fix an MLIS
     GPU-pod label race, but unscoped: it also hijacks SLVD + NemoClaw pods).
   - `add-vendor-app-labels-litellm-helm-litellm-helm` and
     `add-vendor-app-labels-litedemo-litellm-helm` — stamp every Pod/Service/
     Deployment in `project-user-aieadmin` with `hpe-ezua/app=litellm-helm`,
     clobbering the NemoClaw gateway's identity in the same namespace.
3. Result: healthy `2/2` pods are invisible to their own app's health query →
   tile health `unknown`.

## Fix

Keep the race-fix behavior ONLY for pods that arrive without an identity —
i.e. add `hpe-ezua/app DoesNotExist` to each policy's selector. Properly
labeled apps (charts set `hpe-ezua/app` themselves) keep their identity.

```bash
# 1) auto-ezua-labels (cluster-wide inference injector)
kubectl patch clusterpolicy auto-ezua-labels --type=merge -p '{
  "spec": {"rules": [{
    "name": "inject-ezua-labels",
    "match": {"any": [{"resources": {"kinds": ["Pod"], "selector": {
      "matchExpressions": [
        {"key": "hpe-ezua/type", "operator": "In",
         "values": ["app-service-user", "vendor-service"]},
        {"key": "hpe-ezua/app", "operator": "DoesNotExist"}
      ]}}}]},
    "mutate": {"patchStrategicMerge": {"metadata": {"labels": {
      "hpe-ezua/app": "ai-vulnerability-scanner",
      "hpe-ezua/component": "inference-service"}}}}
  }]}
}'

# 2) the two litellm-helm namespace stampers (apply to Pod+Deployment+Service
#    in project-user-aieadmin / litellm-selftest) — inject only when absent
for p in add-vendor-app-labels-litellm-helm-litellm-helm \
         add-vendor-app-labels-litedemo-litellm-helm; do
  kubectl patch clusterpolicy "$p" --type=json -p '[{
    "op": "replace",
    "path": "/spec/rules/0/match/any/0/resources/selector",
    "value": {"matchExpressions": [
      {"key": "hpe-ezua/app", "operator": "DoesNotExist"}]}
  }]'
done
```

Then recreate (or roll) the affected app pods so they admit with their own
labels, and force the ezapp controller to re-probe — it recomputes
`healthState` only when the app's install/upgrade action runs again, so the
clean path is a re-import of the app at a new chart version through the PCAI
UI.

## Chart-side companion (this repo)

- SLVD chart: pod templates already carry `hpe-ezua/app: slvd`
  (`templates/_helpers.tpl` `hpe-ezua.labels`).
- NemoClaw chart >= 0.2.8: pod templates carry `hpe-ezua/app/type/component`
  via the `ezua.appName` value (default `nemoclaw` = the EzAppConfig name).
