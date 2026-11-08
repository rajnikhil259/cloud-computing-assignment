# Reflection notes — draft text to copy by hand

> This is a **draft for the handwritten reflection**. The submission must be your own handwriting, scanned as
> `<roll_number>.pdf` (max. 3 pages). Rewrite it in your own words, keep what you actually experienced, and fill in
> the blanks. Numbers in ⟨…⟩ are filled from `results/` once the runs finish.

**Name:** ______________________  **Roll number:** ______________
**GitHub:** https://github.com/rajnikhil259/cloud-computing-assignment (tag `final`)

## 1. What I learnt
- **Knowledge distillation in practice.** Sequence-level KD needs only the teacher's outputs: phi3.5 (3.8B) labelled
  the commands once, and a 70M-parameter model learnt to reproduce its JSON format from 1,500 examples. Logit-based
  KD was impossible because the two models use different tokenizers and Ollama returns text, not logits.
- **Data pipelines.** Simple, deterministic sharding (line number mod SHARD_COUNT) gives disjoint, balanced shards
  with no coordination. Writing one object per worker, plus checkpoints, makes restarts safe. A cleaning step with a
  checksum makes the training set reproducible byte for byte.
- **Containers and Kubernetes.** Keeping weights out of the image and downloading them at start-up means probes
  matter: `/readyz` stays 503 until the model is loaded, so the Service has no endpoints and gets no traffic too
  early. I learnt how requests, limits, HPA, rolling updates (maxSurge 1 / maxUnavailable 0, preStop) and rollbacks
  fit together.
- **Networking.** VLSM allocation (largest first, aligned blocks) and why stateless NACLs need explicit return
  rules and careful rule order.
- **CI/CD and evidence.** Every claim in the report comes from a file produced by a workflow. The quality gate
  (`--min-validity 95`) blocks a bad model automatically.

## 2. Challenges and how I solved them
- **Teacher speed on CPU:** labelling 3,000 commands with a 3.8B model is slow (⟨measured s per command⟩). Solved by
  running several workers in parallel against one Ollama with matching OLLAMA_NUM_PARALLEL, and by fanning out over
  ⟨N⟩ GitHub runners, each with its own k3d cluster.
- **Teacher output format:** ⟨what the validation run showed — e.g. % valid JSON, typical mistakes⟩. The prompt
  states the four keys and the eight intents, and gives fourteen examples I wrote myself (none from validation).
- **Memory limit of 1 GiB:** fp32 Pythia-70M plus PyTorch fits (peak ⟨…⟩ MiB). I used CPU-only PyTorch wheels to
  keep the image at ⟨…⟩ GB, under the 2 GB limit.
- **Zero-downtime rollout:** readiness gating plus maxUnavailable 0 and a preStop sleep kept failures during the
  update at ⟨…⟩%.
- **Repository access / CI plumbing:** workflows commit their results as me (not as a bot). Transient download
  errors needed retries.

## 3. Findings
- Teacher vs untrained base vs student on validation (full frame): ⟨teacher⟩% / ⟨base⟩% / ⟨student v1⟩%; JSON
  validity ⟨…⟩% for the student.
- The student copies the teacher's format almost perfectly but also its slot-boundary mistakes.
- Latency p50/p95 ⟨…⟩/⟨…⟩ ms at ⟨…⟩ req/s with two replicas; cost ≈ ⟨…⟩ INR per 1,000 requests; cold start ≈ ⟨…⟩ s.
- HPA scaled 1 → 2 → 1 under load; load balancing split ⟨…⟩% / ⟨…⟩%.

## 4. What could be done better
- Use a better teacher prompt (or a few self-consistency votes) and filter well-formed but wrong replies.
- Train with more data or a larger student; try constrained decoding of the four-key schema.
- Run on a real multi-node cluster for genuine fault tolerance; use a startup probe; cache the model on a node volume
  to cut cold starts.
- Use stateful security groups per tier in addition to the NACL.
