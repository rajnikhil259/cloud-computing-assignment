#!/usr/bin/env bash
# Deploy the inference service (namespace app): Deployment, Service, Ingress, HPA.
. "$(dirname "$0")/common.sh"
need kubectl curl
kubectl apply -f "$ROOT/k8s/app/"
kubectl -n app rollout status deploy/cmdparser --timeout=900s
log "waiting for /parse through the Traefik ingress at http://localhost:8080"
for _ in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8080/parse \
    -H 'Content-Type: application/json' -d '{"text": "what is the weather in london"}' || true)
  [ "$code" = "200" ] && break
  sleep 2
done
curl -si -X POST http://localhost:8080/parse -H 'Content-Type: application/json' \
  -d '{"text": "set an alarm for seven thirty am tomorrow"}'
echo
kubectl -n app get deploy,rs,pods,svc,ingress,hpa -o wide
