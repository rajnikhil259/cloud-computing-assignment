#!/usr/bin/env bash
# Run the teacher (Ollama phi3.5) and several labelling workers at the same time in namespace
# "pipeline". Usage:
#   scripts/run_teacher.sh SHARD_COUNT "INDEX INDEX ..." [INPUT_KEY] [OUTPUT_PREFIX] [RUN]
# e.g. scripts/run_teacher.sh 2 "0 1"   -> two workers, shards 0 and 1 of commands_pool.jsonl
# Worker logs and the pod listings are written to results/task1/.
. "$(dirname "$0")/common.sh"
need kubectl
SHARD_COUNT="$1"; INDICES="$2"
INPUT_KEY="${3:-commands_pool.jsonl}"; OUTPUT_PREFIX="${4:-teacher/}"; RUN="${5:-pool}"
OUT="${RESULTS_DIR:-$ROOT/results/task1}"; mkdir -p "$OUT"
n_workers=$(wc -w <<<"$INDICES" | tr -d ' ')

log "deploying Ollama (OLLAMA_NUM_PARALLEL=$n_workers) and pulling phi3.5 (first time: a few minutes)"
render "$ROOT/k8s/pipeline/ollama.yaml" OLLAMA_NUM_PARALLEL="$n_workers" | kubectl apply -f -
kubectl -n pipeline rollout status deploy/ollama --timeout=1800s
kubectl -n pipeline logs deploy/ollama -c pull-teacher --tail=5 > "$OUT/ollama_pull_${RUN}.log" 2>&1 || true
kubectl -n pipeline exec deploy/ollama -c ollama -- ollama show phi3.5 > "$OUT/teacher_model_${RUN}.txt" 2>&1 || true
kubectl -n pipeline exec deploy/ollama -c ollama -- ollama --version >> "$OUT/teacher_model_${RUN}.txt" 2>&1 || true
kubectl -n pipeline create configmap teacher-prompt --from-file=teacher_prompt.txt="$ROOT/prompts/teacher_prompt.txt" \
  --dry-run=client -o yaml | kubectl apply -f -

for i in $INDICES; do
  kubectl -n pipeline delete job "teacher-worker-$RUN-$i" --ignore-not-found >/dev/null
  render "$ROOT/k8s/pipeline/worker-job.yaml" SHARD_INDEX="$i" SHARD_COUNT="$SHARD_COUNT" \
    INPUT_KEY="$INPUT_KEY" OUTPUT_PREFIX="$OUTPUT_PREFIX" RUN="$RUN" | kubectl apply -f -
done
sleep 20
{
  echo "# $(date -u +%FT%TZ)  workers running at the same time in namespace pipeline"
  kubectl -n pipeline get pods -o wide
  echo
  kubectl -n pipeline get pods -l "app=teacher-worker,run=$RUN" \
    -o custom-columns='POD:.metadata.name,SHARD_INDEX:.spec.containers[0].env[0].value,SHARD_COUNT:.spec.containers[0].env[1].value,PHASE:.status.phase,START:.status.startTime'
} | tee "$OUT/workers_running_${RUN}.txt"

start=$(date +%s)
while true; do
  done_n=0; failed=0
  for i in $INDICES; do
    ok=$(kubectl -n pipeline get job "teacher-worker-$RUN-$i" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}')
    bad=$(kubectl -n pipeline get job "teacher-worker-$RUN-$i" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}')
    [ "$ok" = "True" ] && done_n=$((done_n + 1))
    [ "$bad" = "True" ] && failed=1
  done
  [ "$done_n" -eq "$n_workers" ] && break
  [ "$failed" -eq 1 ] && die "a worker job failed"
  for i in $INDICES; do
    printf '  [%5ss] shard %s: %s\n' "$(( $(date +%s) - start ))" "$i" \
      "$(kubectl -n pipeline logs "job/teacher-worker-$RUN-$i" --tail=200 2>/dev/null | grep checkpoint | tail -1)"
  done
  sleep 60
done
log "all $n_workers workers finished in $(( $(date +%s) - start ))s"
for i in $INDICES; do
  kubectl -n pipeline logs "job/teacher-worker-$RUN-$i" > "$OUT/worker_${RUN}_shard-$i.log"
done
kubectl -n pipeline get jobs,pods -o wide | tee "$OUT/jobs_${RUN}.txt"
