#!/usr/bin/env bash
# Build the two images from the repository and import them into the k3d cluster.
#   cmdparser-tools:1.0    worker / cleaner / storage seeder   (worker/Dockerfile)
#   cmdparser-service:1.0  inference service, no weights        (service/Dockerfile)
. "$(dirname "$0")/common.sh"
need docker k3d
what="${1:-all}"
cd "$ROOT"
if [ "$what" = all ] || [ "$what" = tools ]; then
  docker build -f worker/Dockerfile -t "$TOOLS_IMAGE" .
  k3d image import -c "$CLUSTER" "$TOOLS_IMAGE"
fi
if [ "$what" = all ] || [ "$what" = service ]; then
  docker build -f service/Dockerfile -t "$SERVICE_IMAGE" .
  k3d image import -c "$CLUSTER" "$SERVICE_IMAGE"
fi
