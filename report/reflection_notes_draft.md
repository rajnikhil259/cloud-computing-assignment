# Reflection notes — draft text to copy by hand

> This is a **draft for the handwritten reflection**. The submission must be in your own handwriting, scanned as
> `<roll_number>.pdf` (at most 3 pages), and committed at the repository root before running the
> `package-submission` workflow. Rewrite it in your own words and keep only what you actually experienced.

**Name:** ______________________  **Roll number:** ______________
**GitHub:** https://github.com/rajnikhil259/cloud-computing-assignment (tag `final`)

## 1. What I learnt
- **Knowledge distillation in practice.** Sequence-level KD needs only the teacher's outputs. phi3.5 (3.8B) labelled
  3,000 commands once, and a 70M-parameter Pythia learnt to reproduce its JSON from 1,500 of them: 100 % valid JSON
  and 50 % full-frame accuracy, against the teacher's 58 %. The untrained Pythia got 0 %. Logit-based KD was
  impossible because the tokenizers differ and Ollama returns text, not logits.
- **Reproducible data pipelines.** Sharding by line number mod SHARD_COUNT gives disjoint, balanced shards without any
  coordination. One object per worker plus checkpoints makes restarts safe. A deterministic cleaning step with a
  SHA-256 lets anyone rebuild exactly the same training set (`f536dfca…`).
- **Containers and Kubernetes.** Weights stay out of the image (0.95 GB) and are downloaded from object storage at
  start-up, so the readiness probe matters: the Service had no ready endpoints for the ~12 s a Pod was loading. I saw
  how requests and limits, the HPA (1 → 2 → 1), the rolling-update settings, preStop and rollback work together.
- **Networking.** VLSM allocation (largest block first, aligned) and why a stateless NACL needs explicit rules for reply
  traffic, with the deny for 198.51.100.0/24 numbered before the allows.
- **CI/CD and evidence.** Every number in the report comes from a file written by a workflow run. The quality gate
  automatically rejected the untrained model (0 % validity < 95 %).

## 2. Challenges and how I solved them
- **The teacher is slow on a CPU** (~8–10 s per command per worker): one machine would have needed ~3.4 h. I ran 6
  clusters × 2 parallel workers (12 shards), and the whole pool took ~49 min.
- **The teacher sometimes added notes after the JSON.** The first validation run had only 90 % valid JSON: 9 of the
  10 bad replies were a correct line followed by "(Note: …)". Adding a stop at the first newline made it 100 %.
- **Fitting into 1 CPU / 1 GiB.** I used the CPU-only PyTorch wheel, fp32 Pythia-70M and one generation at a time.
  Peak memory was 651 MiB, with no OOM kill.
- **Zero-downtime rollout.** maxSurge 1 / maxUnavailable 0, the readiness gate and a preStop sleep. The rolling update
  lost only 4 of 1,790 requests (0.22 %), and those were v2's own invalid outputs on one command, not dropped
  connections.
- **Infrastructure hiccups.** Downloads from GitHub sometimes returned HTTP 504, so I added retries and fallbacks.
  Workflows only show up once a push changes their file on the default branch.

## 3. Findings
- Validation, full frame: teacher 58 %, untrained Pythia 0 %, student v1 50 %, student v2 51 %. v2 (+1 epoch) had a
  lower training loss but one invalid output, so I kept v1.
- Cleaning: 3,000 in → 4 not JSON, 42 wrong keys, 0 bad intent, 152 bad slots, 45 duplicates → 2,757 kept.
- Standard load test, 2 replicas: p50 850 ms, p95 1,000 ms, 4.68 req/s, 0 errors. Each Pod sat at its 1-CPU limit
  using ~400 MiB. Cold start median 14 s. Load balancing 49.9 % / 50.1 %.
- Cost ≈ ₹0.469 per 1,000 requests (₹7.90 per hour for two replicas). SLO 99 % met, with 0 of 5.57 budget requests
  used.

## 4. What could be done better
- A better teacher prompt or several votes, and filtering of well-formed but wrong replies, since the student copies
  the teacher's mistakes.
- More training data or a larger student, and schema-constrained decoding.
- A real multi-node cluster (a single node cannot show fault tolerance), a node-local model cache to cut cold starts,
  int8 weights and batching for throughput.
- Stateful security groups per tier in addition to the NACL, and a read-only S3 identity for the service.
