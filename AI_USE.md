# Use of AI tools

## Tools used

| Tool | Used for |
|---|---|
| Claude Code (Anthropic), an AI coding assistant working in a cloud sandbox | Reading the handout and the kit; drafting the Python code (`worker/`, `service/`, `training/`, `scripts/`), Kubernetes manifests, Dockerfiles, the Makefile, GitHub Actions workflows and unit tests; working out the subnet table; drafting `README.md` and the report text from the measured results in `results/` |

No AI tool was used to label data. Every training target comes from the fixed teacher (`phi3.5` on Ollama,
temperature 0, seed 42), and the replies are stored exactly as generated. No AI tool produced any number in the
report: every number is read from a file in `results/` that a workflow run produced.

## How the output was checked

* **Against the handout.** Each requirement in the marking tables was mapped to a file or a piece of evidence
  (README "Repository layout" and the report sections). Examples: the four-key schema, the two environment
  variables of the worker, the `id`-order and duplicate rules of `clean.py`, the exact error body
  `{"error": "invalid_model_output"}`, port 8000, the two response headers, and requests/limits/probes/HPA values.
* **Unit tests** (`tests/`, run in CI): the five cleaning rules and the count identity, shard partitioning with no
  gaps or repeats, the service endpoints with a fake model (including `FAULT_INJECT=1` and invalid outputs never
  returned as HTTP 200), and the subnet table and NACL decisions recomputed with Python's `ipaddress` module.
* **The kit's own tools.** `tools/score.py` for every model score, `tools/nacl_sim.py --check` for the NACL, and
  `tools/locustfile.py` with the standard command for the load tests. The kit files are unchanged.
* **Local smoke tests before running in CI.** SeaweedFS in Docker with the storage seeder; two workers against a
  stub teacher, including resuming from a checkpoint; `clean.py --s3` against a local re-run (same SHA-256);
  `train.py --subset 50`; and the service downloading a model from S3, with `/readyz` returning 503 and then 200.
* **The real runs.** All results come from the GitHub Actions workflows in `.github/workflows/`, whose logs and
  outputs are committed in `results/`. Checksums (training set, model files, Release assets) are verified with
  `sha256sum -c` inside those workflows.
* **Hand-calculated values.** The subnet table, the cost per 1,000 requests and the error budget were also worked
  out by hand and compared with the script output.

## Things the AI got wrong or that needed correcting

* Dependency pins first resolved to the newest transitive versions; they were re-resolved to versions
  contemporary with the pinned PyTorch/Transformers releases and are installed with `--no-deps` plus `pip check`,
  so an incomplete pin list fails the build.
* A first version of the service accepted any JSON object; schema validation against `data/schema.json` (exact
  keys, intent enum, string-or-null slots) was added and covered by tests.
* A local test run accidentally wrote a `training/loss.csv` from stub data. It was deleted before committing, and
  the committed loss files come only from the training workflow.
