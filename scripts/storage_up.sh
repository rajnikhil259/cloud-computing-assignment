#!/usr/bin/env bash
# Deploy SeaweedFS in namespace "data", then run the storage-seed Job, which creates the
# buckets "datasets" and "models", uploads the datasets and (SEED_MODELS=auto|1|0) copies the
# released models into models/v1/ and models/v2/.
. "$(dirname "$0")/common.sh"
need kubectl
SEED_MODELS="${SEED_MODELS:-auto}"
kubectl apply -f "$ROOT/k8s/data/seaweedfs.yaml"
kubectl -n data rollout status deploy/seaweedfs --timeout=300s
# the S3 gateway needs a moment after the port opens before bucket calls succeed
sleep 5
kubectl -n data delete job storage-seed --ignore-not-found >/dev/null
render "$ROOT/k8s/data/storage-seed-job.yaml" SEED_MODELS="$SEED_MODELS" MODEL_RELEASE_REPO="$MODEL_RELEASE_REPO" \
  | kubectl apply -f -
if ! kubectl -n data wait --for=condition=complete job/storage-seed --timeout=900s; then
  kubectl -n data logs job/storage-seed --tail=100 || true
  die "storage-seed job did not complete"
fi
kubectl -n data logs job/storage-seed
