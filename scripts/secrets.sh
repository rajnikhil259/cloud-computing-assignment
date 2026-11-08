#!/usr/bin/env bash
# Generate random S3 credentials once (stored only in .secrets/, which Git ignores) and
# load them into Kubernetes Secrets:
#   data/seaweedfs-s3-config  the SeaweedFS identities file (s3.json)
#   <ns>/s3-credentials       AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY for data, pipeline and app
. "$(dirname "$0")/common.sh"
need kubectl
mkdir -p "$SECRETS_DIR"; chmod 700 "$SECRETS_DIR"
if [ ! -f "$S3_ENV" ]; then
  umask 077
  printf 'AWS_ACCESS_KEY_ID=%s\nAWS_SECRET_ACCESS_KEY=%s\n' "$(randhex 10)" "$(randhex 20)" > "$S3_ENV"
  log "generated new S3 credentials in .secrets/s3.env"
fi
load_s3_env
kubectl apply -f "$ROOT/k8s/namespaces.yaml" >/dev/null
s3json=$(printf '{"identities":[{"name":"cmdparser","credentials":[{"accessKey":"%s","secretKey":"%s"}],"actions":["Admin","Read","List","Tagging","Write"]}]}' \
  "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY")
kubectl -n data create secret generic seaweedfs-s3-config --from-literal=s3.json="$s3json" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
for ns in data pipeline app; do
  kubectl -n "$ns" create secret generic s3-credentials \
    --from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
done
log "secrets ready: data/seaweedfs-s3-config, {data,pipeline,app}/s3-credentials"
