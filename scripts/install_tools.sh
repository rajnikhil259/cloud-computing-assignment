#!/usr/bin/env bash
# Install pinned k3d and kubectl binaries into /usr/local/bin (used by the CI runners;
# on a laptop, install them with your package manager instead).
set -euo pipefail
K3D_VERSION="${K3D_VERSION:-v5.7.4}"
KUBECTL_VERSION="${KUBECTL_VERSION:-v1.31.4}"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO=sudo
curl -fsSL -o /tmp/k3d "https://github.com/k3d-io/k3d/releases/download/${K3D_VERSION}/k3d-linux-amd64"
curl -fsSL -o /tmp/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
$SUDO install -m 0755 /tmp/k3d /usr/local/bin/k3d
$SUDO install -m 0755 /tmp/kubectl /usr/local/bin/kubectl
k3d version
kubectl version --client
