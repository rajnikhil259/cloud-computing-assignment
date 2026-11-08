#!/usr/bin/env bash
# Task 4 and Task 7 experiments against the running system (after `make up`).
#   scripts/k8s_experiments.sh basics|coldstart|loadbalance|rolling|recovery|hpa|task7|all
# Evidence goes to results/task4/ and results/task7/; the standard load test writes
# results/loadtest_stats.csv and results/loadtest_headers.json exactly as the handout's command.
. "$(dirname "$0")/common.sh"
need kubectl curl locust python3
T4="$ROOT/results/task4"; T7="$ROOT/results/task7"; mkdir -p "$T4" "$T7"
NS=app
LOCUST=(locust -f "$ROOT/tools/locustfile.py" --headless --users 4 --spawn-rate 4 --host http://localhost:8080)
cd "$ROOT"   # locustfile.py reads data/validation.jsonl relative to the working directory

now() { date -u +%H:%M:%S; }
event() { echo "$(now) EVENT $*" | tee -a "$1.events"; }
ready_replicas() { kubectl -n $NS get deploy cmdparser -o jsonpath='{.status.readyReplicas}'; }
pod_names() { kubectl -n $NS get pods -l app=cmdparser -o jsonpath='{.items[*].metadata.name}'; }
parse() { curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8080/parse -H 'Content-Type: application/json' \
            -d '{"text": "what time is it in tokyo"}' --max-time 30 || true; }

# start_watch FILE INTERVAL: snapshots of pods, endpoints and HTTP status through the ingress
start_watch() {
  local file="$1" every="$2"
  ( while true; do
      eps=$(kubectl -n $NS get endpoints cmdparser -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null | wc -w)
      nre=$(kubectl -n $NS get endpoints cmdparser -o jsonpath='{.subsets[*].notReadyAddresses[*].ip}' 2>/dev/null | wc -w)
      pods=$(kubectl -n $NS get pods -l app=cmdparser --no-headers \
               -o custom-columns=N:.metadata.name,PH:.status.phase,R:.status.containerStatuses[0].ready 2>/dev/null \
               | awk '{printf "%s(%s,ready=%s) ", $1, $2, $3}')
      echo "$(now) ready_endpoints=$eps not_ready_endpoints=$nre ingress_http=$(parse) pods: $pods"
      sleep "$every"
    done ) > "$file" 2>&1 &
  WATCH_PID=$!
}
stop_watch() { kill "$WATCH_PID" 2>/dev/null || true; wait "$WATCH_PID" 2>/dev/null || true; }

hpa_min() {  # pin the HPA minimum (2 = exactly two replicas for the controlled experiments; 1 = as specified)
  kubectl -n $NS patch hpa cmdparser --type merge -p "{\"spec\":{\"minReplicas\":$1}}" >/dev/null
  if [ "$1" = 2 ]; then
    for _ in $(seq 1 120); do [ "$(ready_replicas)" = 2 ] && break; sleep 2; done
    kubectl -n $NS rollout status deploy/cmdparser --timeout=600s >/dev/null
  fi
}

basics() {
  {
    echo "# $(date -u +%FT%TZ) resources in namespace app"
    kubectl -n $NS get deploy,rs,pods,svc,endpoints,ingress,hpa -o wide
    echo; echo "# requests, limits and probes of the container"
    kubectl -n $NS get deploy cmdparser -o jsonpath='{range .spec.template.spec.containers[*]}resources={.resources}{"\n"}readinessProbe={.readinessProbe}{"\n"}livenessProbe={.livenessProbe}{"\n"}env={.env}{"\n"}{end}'
    echo; echo "# strategy"; kubectl -n $NS get deploy cmdparser -o jsonpath='{.spec.strategy}{"\n"}'
  } > "$T4/app_resources.txt" 2>&1
  {
    echo "\$ curl -i -X POST http://localhost:8080/parse   (through the Traefik Ingress)"
    curl -si -X POST http://localhost:8080/parse -H 'Content-Type: application/json' -d '{"text": "set an alarm for seven thirty am tomorrow"}'
    echo; echo
    curl -si -X POST http://localhost:8080/parse -H 'Content-Type: application/json' -d '{"text": "what is the weather in london"}'
    echo; echo; echo "\$ curl -i http://localhost:8080/healthz   (not routed: only /parse goes through the Ingress)"
    curl -si http://localhost:8080/healthz | head -1
  } > "$T4/ingress_parse.txt" 2>&1
  { echo "Secret used for the S3 credentials (key names only, values never printed):"
    kubectl get secret -n $NS s3-credentials -o go-template='{{.metadata.name}} type={{.type}} keys:{{range $k, $v := .data}} {{$k}}{{end}}{{"\n"}}'
  } > "$T4/secret_reference.txt"
  kubectl top nodes > "$T4/top_nodes.txt" 2>&1 || true
}

coldstart() {
  hpa_min 2
  for run in 1 2 3; do
    old="$T4/coldstart_run${run}_old_pods.txt"; pod_names > "$old"
    start_watch "$T4/coldstart_run${run}_watch.txt" 1
    event "$T4/coldstart_run${run}" "deleting all pods: $(cat "$old")"
    kubectl -n $NS delete pods -l app=cmdparser --wait=false
    sleep 3
    for _ in $(seq 1 300); do
      n_new=0
      for p in $(pod_names); do grep -qw "$p" "$old" || n_new=$((n_new + 1)); done
      [ "$(ready_replicas)" = 2 ] && [ "$n_new" -ge 2 ] && break
      sleep 1
    done
    sleep 2; stop_watch
    event "$T4/coldstart_run${run}" "all replicas ready again"
    kubectl -n $NS get pods -l app=cmdparser -o json > "$T4/coldstart_run${run}_podlist.json"
    python3 scripts/analyze.py coldstart "$T4/coldstart_run${run}_podlist.json" "$old" > "$T4/coldstart_run${run}_pods.json"
    for p in $(pod_names); do
      grep -qw "$p" "$old" || kubectl -n $NS logs "$p" > "$T4/coldstart_run${run}_${p}.log" 2>&1
    done
    rm -f "$T4/coldstart_run${run}_podlist.json"
    sleep 20
  done
  python3 scripts/analyze.py coldstart-summary "$T4" | tee "$T4/coldstart_summary.txt"
}

loadbalance() {   # also the Task 7 standard run: exactly the handout's command
  hpa_min 2
  sleep 10
  kubectl -n $NS get pods -l app=cmdparser -o wide > "$T4/loadbalance_pods_before.txt"
  ( while true; do echo "== $(date -u +%FT%TZ)"; kubectl top pods -n $NS --containers 2>&1; sleep 10; done ) > "$T7/top_pods.txt" &
  local top=$!
  locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m \
    --host http://localhost:8080 --csv results/loadtest 2>&1 | tee "$T7/locust_standard_run.log" || true
  kill $top 2>/dev/null || true
  kubectl -n $NS get pods -l app=cmdparser -o wide > "$T4/loadbalance_pods_after.txt"
  python3 scripts/analyze.py locust results/loadtest | tee "$T7/standard_run_summary.json"
  python3 scripts/analyze.py share results/loadtest_headers.json | tee "$T4/loadbalance_share.json"
}

rolling() {
  hpa_min 2
  local p="$T4/rolling"
  : > "$p.events"
  start_watch "$p"_timeline.txt 3
  LOADTEST_HEADERS_OUT="$p"_headers.json "${LOCUST[@]}" --run-time 7m --csv "$p" > "$p"_locust.log 2>&1 &
  local lp=$!
  sleep 40
  event "$p" "kubectl set env: MODEL_VERSION=v2 MODEL_URI=s3://models/v2/"
  kubectl -n $NS set env deploy/cmdparser MODEL_VERSION=v2 MODEL_URI=s3://models/v2/
  kubectl -n $NS rollout status deploy/cmdparser --timeout=600s | tee -a "$p.events"
  event "$p" "rollout to v2 complete"
  curl -si -X POST http://localhost:8080/parse -H 'Content-Type: application/json' -d '{"text": "what time is it in tokyo"}' > "$p"_after_update.txt
  sleep 60
  event "$p" "kubectl rollout undo"
  kubectl -n $NS rollout undo deploy/cmdparser
  kubectl -n $NS rollout status deploy/cmdparser --timeout=600s | tee -a "$p.events"
  event "$p" "rollback to v1 complete"
  wait $lp || true
  stop_watch
  kubectl -n $NS rollout history deploy/cmdparser > "$p"_history.txt
  {
    echo "after the rollback, 6 requests through the Ingress:"
    for _ in 1 2 3 4 5 6; do
      curl -si -X POST http://localhost:8080/parse -H 'Content-Type: application/json' -d '{"text": "what time is it in tokyo"}' \
        | grep -iE '^(HTTP|x-model-version|x-served-by)' | tr -d '\r' | tr '\n' ' '; echo
    done
  } > "$p"_after_rollback.txt
  python3 scripts/analyze.py locust "$p" > /dev/null
  python3 scripts/analyze.py share "$p"_headers.json > "$p"_share.json
  cat "$p"_summary.json "$p"_after_rollback.txt
}

recovery() {
  hpa_min 2
  local p="$T4/recovery"
  : > "$p.events"
  ( while true; do echo "$(now) $(kubectl -n $NS get deploy cmdparser --no-headers 2>&1)"; sleep 2; done ) > "$p"_replicas.txt &
  local rw=$!
  start_watch "$p"_timeline.txt 2
  LOADTEST_HEADERS_OUT="$p"_headers.json "${LOCUST[@]}" --run-time 3m --csv "$p" > "$p"_locust.log 2>&1 &
  local lp=$!
  sleep 40
  victim=$(kubectl -n $NS get pods -l app=cmdparser -o jsonpath='{.items[0].metadata.name}')
  event "$p" "deleting pod $victim"
  kubectl -n $NS delete pod "$victim" --wait=false
  for _ in $(seq 1 180); do
    [ "$(ready_replicas)" = 2 ] && ! pod_names | grep -qw "$victim" && break
    sleep 1
  done
  event "$p" "replica count restored: $(kubectl -n $NS get deploy cmdparser --no-headers)"
  wait $lp || true
  kill $rw 2>/dev/null || true
  stop_watch
  python3 scripts/analyze.py locust "$p" > /dev/null
  cat "$p"_summary.json
}

hpa() {
  kubectl apply -f k8s/app/hpa.yaml          # back to the specification: min 1, max 2, 70 % CPU
  local p="$T4/hpa"
  : > "$p.events"
  ( while true; do
      echo "$(now) $(kubectl -n $NS get hpa cmdparser --no-headers 2>&1 | awk '{print "targets="$4, "min="$5, "max="$6, "replicas="$7}') \
ready=$(ready_replicas) | $(kubectl top pods -n $NS --no-headers 2>/dev/null | tr '\n' ';')"
      sleep 10
    done ) > "$p"_timeline.txt &
  local w=$!
  event "$p" "phase 1: idle, waiting for the HPA to scale down to 1"
  for _ in $(seq 1 60); do [ "$(kubectl -n $NS get deploy cmdparser -o jsonpath='{.spec.replicas}')" = 1 ] && break; sleep 10; done
  event "$p" "replicas=$(kubectl -n $NS get deploy cmdparser -o jsonpath='{.spec.replicas}')"
  sleep 30
  event "$p" "phase 2: load (4 users) for 5 minutes"
  LOADTEST_HEADERS_OUT="$p"_headers.json "${LOCUST[@]}" --run-time 5m --csv "$p" > "$p"_locust.log 2>&1 &
  local lp=$!
  for _ in $(seq 1 60); do [ "$(ready_replicas)" = 2 ] && break; sleep 5; done
  event "$p" "scaled up: ready replicas=$(ready_replicas)"
  wait $lp || true
  event "$p" "phase 3: load stopped, waiting for the scale-down to 1"
  for _ in $(seq 1 60); do [ "$(kubectl -n $NS get deploy cmdparser -o jsonpath='{.spec.replicas}')" = 1 ] && break; sleep 10; done
  event "$p" "replicas=$(kubectl -n $NS get deploy cmdparser -o jsonpath='{.spec.replicas}')"
  sleep 20
  kill $w 2>/dev/null || true
  kubectl -n $NS describe hpa cmdparser > "$p"_describe.txt
  kubectl -n $NS get events --sort-by=.lastTimestamp | grep -iE "horizontalpodautoscaler|scaled|SuccessfulRescale" > "$p"_events.txt || true
  python3 scripts/analyze.py locust "$p" > /dev/null
}

task7() {
  python3 scripts/analyze.py cost results/loadtest_stats.csv data/rate_card.json 2 1 1 | tee "$T7/cost.json"
  python3 scripts/analyze.py slo results/loadtest_stats.csv 99 | tee "$T7/slo.json"
  cp "$T4/coldstart_summary.json" "$T7/coldstart_summary.json" 2>/dev/null || true
}

case "${1:-all}" in
  basics) basics ;; coldstart) coldstart ;; loadbalance) loadbalance ;; rolling) rolling ;;
  recovery) recovery ;; hpa) hpa ;; task7) task7 ;;
  all) basics; coldstart; loadbalance; rolling; recovery; hpa; task7 ;;
  *) die "unknown experiment $1" ;;
esac
