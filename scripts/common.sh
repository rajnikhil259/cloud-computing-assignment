#!/usr/bin/env bash
# Shared settings and helpers for the scripts in this directory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER="${CLUSTER:-cmdparser}"
TOOLS_IMAGE="${TOOLS_IMAGE:-cmdparser-tools:1.0}"
SERVICE_IMAGE="${SERVICE_IMAGE:-cmdparser-service:1.0}"
SECRETS_DIR="$ROOT/.secrets"
S3_ENV="$SECRETS_DIR/s3.env"
# GitHub repository whose Releases hold the trained models (model-v1, model-v2)
MODEL_RELEASE_REPO="${MODEL_RELEASE_REPO:-rajnikhil259/cloud-computing-assignment}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }
need() { for c in "$@"; do command -v "$c" >/dev/null 2>&1 || die "'$c' is required but not installed"; done; }

# render FILE KEY=VALUE ... : replace __KEY__ placeholders in a manifest template
render() {
  local f="$1"; shift
  local s; s="$(cat "$f")"
  local kv k v
  for kv in "$@"; do k="${kv%%=*}"; v="${kv#*=}"; s="${s//__${k}__/$v}"; done
  printf '%s\n' "$s"
}

# random hex string without depending on openssl
randhex() { head -c "${1:-20}" /dev/urandom | od -An -tx1 | tr -d ' \n'; }

load_s3_env() {
  [ -f "$S3_ENV" ] || die "$S3_ENV not found; run 'make secrets' (part of 'make up') first"
  set -a; . "$S3_ENV"; set +a
}
