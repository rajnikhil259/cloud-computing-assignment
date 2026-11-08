#!/usr/bin/env bash
# Install pinned k3d (and kubectl if missing) into /usr/local/bin. Used by the CI runners;
# on a laptop, install them with your package manager instead.
set -euo pipefail
K3D_VERSION="${K3D_VERSION:-v5.7.4}"
KUBECTL_VERSION="${KUBECTL_VERSION:-v1.31.4}"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO=sudo

fetch() {  # fetch URL DEST, with retries; says which URL failed
  local i
  for i in 1 2 3 4 5; do
    if curl -fsSL --connect-timeout 20 --max-time 300 -o "$2" "$1"; then return 0; fi
    echo "download failed ($i/5): $1" >&2
    sleep $((i * 4))
  done
  return 1
}

if command -v k3d >/dev/null 2>&1 && k3d version | grep -q "k3d version ${K3D_VERSION}"; then
  echo "k3d ${K3D_VERSION} already installed"
else
  if ! fetch "https://github.com/k3d-io/k3d/releases/download/${K3D_VERSION}/k3d-linux-amd64" /tmp/k3d; then
    echo "falling back to the binary inside the official k3d image ghcr.io/k3d-io/k3d:${K3D_VERSION#v}" >&2
    docker rm -f k3d-extract >/dev/null 2>&1 || true
    docker create --name k3d-extract "ghcr.io/k3d-io/k3d:${K3D_VERSION#v}" >/dev/null
    docker cp k3d-extract:/bin/k3d /tmp/k3d || docker cp k3d-extract:/usr/local/bin/k3d /tmp/k3d
    docker rm -f k3d-extract >/dev/null
  fi
  $SUDO install -m 0755 /tmp/k3d /usr/local/bin/k3d
fi

if command -v kubectl >/dev/null 2>&1; then
  echo "using the installed kubectl"
else
  fetch "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" /tmp/kubectl
  $SUDO install -m 0755 /tmp/kubectl /usr/local/bin/kubectl
fi
k3d version
kubectl version --client
