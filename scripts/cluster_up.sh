#!/usr/bin/env bash
# Create the k3d cluster from cluster/k3d.yaml (idempotent).
. "$(dirname "$0")/common.sh"
need docker k3d kubectl
if k3d cluster list -o json 2>/dev/null | grep -q "\"name\":\"$CLUSTER\""; then
  log "cluster $CLUSTER already exists"
  k3d kubeconfig merge "$CLUSTER" --kubeconfig-merge-default --kubeconfig-switch-context >/dev/null
else
  log "creating cluster $CLUSTER from cluster/k3d.yaml"
  k3d cluster create --config "$ROOT/cluster/k3d.yaml"
fi
kubectl wait --for=condition=Ready nodes --all --timeout=180s
kubectl apply -f "$ROOT/k8s/namespaces.yaml"
