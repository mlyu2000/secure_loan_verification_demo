#!/usr/bin/env bash
# Monitor SLVD deploy on CS1: polls helm release + EzAppConfig + pods,
# exits 0 on HEALTHY (deployed + all pods fully ready), 1 on FAILED, 2 on timeout.
export KUBECONFIG=/home/ml/projects/kubeconfig-cs1.conf
DEADLINE=$(( $(date +%s) + 5400 ))   # 90 min
last=""
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  rel=$(helm -n project-user-aieadmin ls -a -o json 2>/dev/null | python3 -c "
import json,sys
for r in json.load(sys.stdin):
    if r['name']=='slvd': print(r['status']); break
")
  ez=$(kubectl -n ui get ezappconfig -o json 2>/dev/null | python3 -c "
import json,sys
for i in json.load(sys.stdin).get('items',[]):
    if i['spec'].get('name')=='slvd':
        st=i.get('status',{})
        print(st.get('status',''), st.get('healthState',''), st.get('retryCnt',''), sep='|')
        break
")
  ezstatus=$(echo "$ez" | cut -d'|' -f1); ezhealth=$(echo "$ez" | cut -d'|' -f2); ezretry=$(echo "$ez" | cut -d'|' -f3)
  pods=$(kubectl -n slvd get pods --no-headers 2>/dev/null | awk '{print $1,$2,$3}' | sort | tr '\n' ';')
  cur="release=$rel ezapp=$ezstatus/$ezhealth retry=$ezretry pods=$pods"
  [ "$cur" != "$last" ] && { echo "$(date +%H:%M:%S) $cur"; last="$cur"; }
  if [ "$rel" = "deployed" ] && echo "$pods" | grep -q 'engine-[^ ]* 2/2' && echo "$pods" | grep -q 'credit-memo-mcp[^ ]* 2/2' && echo "$pods" | grep -q 'mailpit-[^ ]* 1/1' && echo "$pods" | grep -q 'portal-[^ ]* 2/2'; then
    echo "RESULT=HEALTHY release=$rel ezapp=$ezstatus/$ezhealth"
    exit 0
  fi
  if [ "$rel" = "failed" ] || [ "$ezstatus" = "failed" ]; then
    echo "RESULT=FAILED release=$rel ezapp=$ezstatus/$ezhealth retry=$ezretry pods=$pods"
    exit 1
  fi
  sleep 30
done
echo "RESULT=TIMEOUT last: $last"
exit 2
