#!/usr/bin/env bash
# `make up`: build and deploy the whole system from a fresh clone.
#   1. k3d cluster from cluster/k3d.yaml           4. images built and imported into k3d
#   2. random S3 credentials -> Kubernetes Secrets  5. buckets + datasets + models (from the GitHub Release)
#   3. SeaweedFS in namespace data                  6. the service in namespace app (Deployment/Service/Ingress/HPA)
. "$(dirname "$0")/common.sh"
need docker k3d kubectl curl
"$ROOT/scripts/cluster_up.sh"
"$ROOT/scripts/secrets.sh"
"$ROOT/scripts/build_images.sh" all
SEED_MODELS="${SEED_MODELS:-1}" "$ROOT/scripts/storage_up.sh"
"$ROOT/scripts/deploy_app.sh"
log "done. Try: curl -s -X POST http://localhost:8080/parse -H 'Content-Type: application/json' -d '{\"text\": \"what time is it in tokyo\"}'"
