#!/usr/bin/env bash
# Task 3 evidence, with plain Docker (no Kubernetes):
#   * build the service image with one command and report its size (must be <= 2 GB)
#   * show that the image contains no model weights and that every package is pinned
#   * start SeaweedFS + seed the models (released model-v1) into it
#   * run the service with --cpus 1 --memory 1g, show /healthz, /readyz (503 -> 200), /parse headers
#   * send 50 requests one after another and record the peak memory (cgroup memory.peak + docker stats)
#   * run a second container with FAULT_INJECT=1 and show HTTP 500 {"error": "invalid_model_output"}
. "$(dirname "$0")/common.sh"
need docker curl python3
OUT="$ROOT/results/task3"; mkdir -p "$OUT"
NET=cmdparser-t3
KEY=$(randhex 10); SECRET=$(randhex 20)    # throw-away credentials for this test only
cleanup() { docker rm -f t3-seaweedfs t3-svc t3-svc-fault >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

# ---- 1. build ----------------------------------------------------------------------------
log "building $SERVICE_IMAGE"
start=$(date +%s)
docker build -f "$ROOT/service/Dockerfile" -t "$SERVICE_IMAGE" "$ROOT" 2>&1 | tail -n 15 > "$OUT/build.log"
build_s=$(( $(date +%s) - start ))
size=$(docker image inspect "$SERVICE_IMAGE" --format '{{.Size}}')
{
  echo "command: docker build -f service/Dockerfile -t $SERVICE_IMAGE .   (make image)"
  echo "build time: ${build_s}s"
  echo "image size: $size bytes = $(python3 -c "print(round($size/1e9, 3))") GB (limit 2 GB)"
  docker image ls "$SERVICE_IMAGE"
  echo; echo "layers:"; docker history --format '{{.Size}}\t{{.CreatedBy}}' "$SERVICE_IMAGE" | cut -c1-160
} | tee "$OUT/image_size.txt"
[ "$size" -le 2000000000 ] || die "image is larger than 2 GB"

docker run --rm --entrypoint sh "$SERVICE_IMAGE" -c \
  'echo "files under /app:"; ls -la /app; echo; echo "model weight files anywhere in the image (outside Python packages):";
   find / -xdev \( -name "*.safetensors" -o -name "pytorch_model*.bin" -o -name "*.gguf" -o -name "*.pt" \) \
     -not -path "*/site-packages/*" 2>/dev/null | sed "s/^/  /"; echo "  (end of list)"' \
  | tee "$OUT/image_no_weights.txt"
docker run --rm --entrypoint pip "$SERVICE_IMAGE" freeze > "$OUT/image_pip_freeze.txt"

# ---- 2. object storage with the model ----------------------------------------------------
docker network create "$NET" >/dev/null
mkdir -p /tmp/t3-s3
printf '{"identities":[{"name":"t3","credentials":[{"accessKey":"%s","secretKey":"%s"}],"actions":["Admin","Read","List","Write"]}]}' \
  "$KEY" "$SECRET" > /tmp/t3-s3/s3.json
docker run -d --name t3-seaweedfs --network "$NET" -v /tmp/t3-s3:/etc/seaweedfs:ro chrislusf/seaweedfs:3.80 \
  server -dir=/data -ip.bind=0.0.0.0 -master.volumeSizeLimitMB=1024 -volume.max=0 -filer -s3 -s3.port=8333 \
  -s3.config=/etc/seaweedfs/s3.json >/dev/null
sleep 10
docker build -q -f "$ROOT/worker/Dockerfile" -t "$TOOLS_IMAGE" "$ROOT" >/dev/null
docker run --rm --network "$NET" -e S3_ENDPOINT=http://t3-seaweedfs:8333 -e AWS_ACCESS_KEY_ID="$KEY" \
  -e AWS_SECRET_ACCESS_KEY="$SECRET" -e SEED_MODELS=1 -e MODEL_RELEASE_REPO="$MODEL_RELEASE_REPO" \
  -e MODEL_VERSIONS=v1 "$TOOLS_IMAGE" python -u seed_storage.py > "$OUT/seed_models.log" 2>&1

run_service() { # name fault host_port
  docker run -d --name "$1" --network "$NET" --cpus 1 --memory 1g --memory-swap 1g -p "$3:8000" \
    -e MODEL_URI=s3://models/v1/ -e MODEL_VERSION=v1 -e S3_ENDPOINT=http://t3-seaweedfs:8333 \
    -e MAX_NEW_TOKENS=64 -e FAULT_INJECT="$2" -e AWS_ACCESS_KEY_ID="$KEY" -e AWS_SECRET_ACCESS_KEY="$SECRET" \
    "$SERVICE_IMAGE" >/dev/null
}

# ---- 3. start-up: healthz immediately, readyz 503 until the model is loaded ----------------
run_service t3-svc 0 8000
{
  echo "time_s  /healthz  /readyz   (container started with --cpus 1 --memory 1g)"
  t0=$(date +%s.%N)
  for _ in $(seq 1 240); do
    h=$(curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz || true)
    r=$(curl -s -o /dev/null -w '%{http_code}' localhost:8000/readyz || true)
    printf '%6.1f  %s       %s\n' "$(awk "BEGIN{print $(date +%s.%N) - $t0}")" "$h" "$r"
    [ "$r" = 200 ] && break
    sleep 0.5
  done
} | tee "$OUT/startup_probes.txt"
docker logs t3-svc > "$OUT/service_startup.log" 2>&1

{
  for path in healthz readyz; do echo "\$ curl -i http://localhost:8000/$path"; curl -si "localhost:8000/$path"; echo; echo; done
  echo "\$ curl -i -X POST http://localhost:8000/parse -d '{\"text\": \"set an alarm for seven thirty am tomorrow\"}'"
  curl -si -X POST localhost:8000/parse -H 'Content-Type: application/json' -d '{"text": "set an alarm for seven thirty am tomorrow"}'
  echo; echo
  echo "\$ curl -i -X POST http://localhost:8000/parse -d '{\"text\": \"what is the weather in london\"}'"
  curl -si -X POST localhost:8000/parse -H 'Content-Type: application/json' -d '{"text": "what is the weather in london"}'
  echo
} | tee "$OUT/endpoints.txt"

# ---- 4. 50 sequential requests at 1 CPU / 1 GiB, peak memory ------------------------------
( while docker inspect t3-svc >/dev/null 2>&1; do
    docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' t3-svc 2>/dev/null | sed "s/^/$(date -u +%T) /"
    sleep 1
  done ) > "$OUT/docker_stats_during_50.txt" &
sampler=$!
python3 - "$ROOT/data/validation.jsonl" <<'EOF' | tee "$OUT/sequential_50.txt"
import json, sys, time, urllib.request, statistics
texts = [json.loads(l)["text"] for l in open(sys.argv[1]) if l.strip()][:50]
lat, codes = [], {}
for i, t in enumerate(texts, 1):
    req = urllib.request.Request("http://localhost:8000/parse", data=json.dumps({"text": t}).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            code, body = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, body = e.code, e.read().decode()
    lat.append((time.time() - t0) * 1000)
    codes[code] = codes.get(code, 0) + 1
    print(f"{i:2d} {code} {lat[-1]:7.1f} ms  {t!r} -> {body}")
lat.sort()
print(f"\n50 sequential requests: status counts {codes}; latency median {statistics.median(lat):.1f} ms, "
      f"p95 {lat[int(0.95 * len(lat)) - 1]:.1f} ms, max {lat[-1]:.1f} ms")
EOF
kill "$sampler" 2>/dev/null || true
{
  echo "container limits: $(docker inspect t3-svc --format 'NanoCpus={{.HostConfig.NanoCpus}} Memory={{.HostConfig.Memory}} MemorySwap={{.HostConfig.MemorySwap}}')"
  echo "state after the test: $(docker inspect t3-svc --format 'Status={{.State.Status}} OOMKilled={{.State.OOMKilled}} RestartCount={{.RestartCount}} ExitCode={{.State.ExitCode}}')"
  echo "cgroup memory.peak (bytes, highest usage since the container started):"
  docker exec t3-svc cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo "  (memory.peak not available on this kernel)"
  echo "cgroup memory.current (bytes): $(docker exec t3-svc cat /sys/fs/cgroup/memory.current 2>/dev/null)"
  echo "cgroup memory.events: $(docker exec t3-svc cat /sys/fs/cgroup/memory.events 2>/dev/null | tr '\n' ' ')"
  echo "highest 'docker stats' sample during the 50 requests:"
  python3 - "$OUT/docker_stats_during_50.txt" <<'EOF'
import re, sys
best = None
for line in open(sys.argv[1]):
    m = re.search(r"([\d.]+)(KiB|MiB|GiB) /", line)
    if m:
        v = float(m.group(1)) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[m.group(2)]
        best = max(best or (0, ""), (v, line.strip()))
print(f"  {best[1]}  -> {best[0]:.1f} MiB" if best else "  no samples")
EOF
} | tee "$OUT/peak_memory.txt"
docker logs t3-svc > "$OUT/service_full.log" 2>&1

# ---- 5. FAULT_INJECT=1 ---------------------------------------------------------------------
run_service t3-svc-fault 1 8001
for _ in $(seq 1 240); do [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8001/readyz)" = 200 ] && break; sleep 0.5; done
{
  echo "container started with FAULT_INJECT=1"
  echo "\$ curl -i -X POST http://localhost:8001/parse -d '{\"text\": \"what is the weather in london\"}'"
  curl -si -X POST localhost:8001/parse -H 'Content-Type: application/json' -d '{"text": "what is the weather in london"}'
  echo
} | tee "$OUT/fault_inject.txt"
docker logs t3-svc-fault 2>&1 | grep -i "invalid model output" | head -3 >> "$OUT/fault_inject.txt" || true
log "Task 3 evidence written to results/task3/"
