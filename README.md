# Knowledge Distillation and Deployment of a Lightweight Command-Parsing Language Model on a Local Cloud

**GitHub repository:** https://github.com/rajnikhil259/cloud-computing-assignment
**Model releases:** [model-v1](https://github.com/rajnikhil259/cloud-computing-assignment/releases/tag/model-v1) ·
[model-v2](https://github.com/rajnikhil259/cloud-computing-assignment/releases/tag/model-v2) ·
[model-base](https://github.com/rajnikhil259/cloud-computing-assignment/releases/tag/model-base) (untrained, for the CI gate demo)
**Report:** [`report/report.pdf`](report/report.pdf) · **Assessed commit:** tag [`final`](https://github.com/rajnikhil259/cloud-computing-assignment/tree/final)

A teacher model (`phi3.5`, Phi-3.5-mini-instruct 3.8B, served by Ollama with temperature 0 and seed 42) labels
3,000 voice-assistant commands with a four-key JSON frame (`intent`, `date`, `time`, `place`). The cleaned
replies are used to fine-tune `EleutherAI/pythia-70m` on the CPU (sequence-level knowledge distillation). The student
is served by a FastAPI container that downloads its weights from SeaweedFS (S3) at start-up and runs on a local
k3d (k3s) cluster behind the Traefik Ingress, with probes, an HPA, rolling updates and a NACL/subnet design.

## Repository layout

| Path | What it is |
|---|---|
| `cluster/k3d.yaml` | k3d cluster definition (1 k3s server, ports 8080 → Traefik, 8333 → S3) |
| `k8s/namespaces.yaml`, `k8s/data/` | namespaces; SeaweedFS (namespace `data`) and the `storage-seed` Job |
| `k8s/pipeline/` | Ollama teacher, teacher-worker Job template, clean Job (namespace `pipeline`) |
| `k8s/app/` | service Deployment, Service, Ingress, HPA (namespace `app`) |
| `prompts/teacher_prompt.txt` | the teacher prompt |
| `worker/` | `worker.py` (SHARD_INDEX / SHARD_COUNT labelling worker), `clean.py`, `seed_storage.py`, tools image |
| `datasets/teacher/`, `datasets/v1/` | raw teacher shards and the cleaned `train.jsonl` + `train.sha256` |
| `training/` | `config.yaml`, `train.py`, `predict.py`, `loss.csv`, `loss_v2.csv` |
| `models/v1/`, `models/v2/` | `model.sha256` and `version.json` only (weights are in object storage and the Releases) |
| `service/` | inference service (`app.py`, `model.py`), `Dockerfile`, pinned `requirements.txt` |
| `network/` | `subnets.md` (Task 5 table and working), `nacl.json`, test packets |
| `tests/` | unit tests (cleaning rules, sharding, service API, subnets/NACL) |
| `scripts/` | cluster/storage/deploy scripts, Task 3 container test, Task 4/7 experiments, analysis |
| `tools/`, `data/` | the student kit, unchanged (`score.py`, `locustfile.py`, `nacl_sim.py`, datasets) |
| `results/` | every log, score report, Locust output and command output used in the report |
| `.github/workflows/` | CI and the workflows that produced the results (see below) |
| `report/` | `report.md` → `report.pdf`, and the draft text for the handwritten reflection |
| `AI_USE.md` | which AI tools were used, for what, and how their output was checked |

## Prerequisites

Docker, [k3d](https://k3d.io) v5.7+, `kubectl`, `make`, `curl`, Python 3.12. On Linux, `scripts/install_tools.sh`
installs the pinned k3d and kubectl. The machine needs about 4 GB of free RAM for the service, and about 8 GB
more to run the teacher.

## Build and deploy (from a fresh clone: three commands)

```bash
git clone https://github.com/rajnikhil259/cloud-computing-assignment.git
```

```bash
cd cloud-computing-assignment
```

```bash
make up
```

`make up` (see `scripts/up.sh`) does the following:

1. creates the cluster from `cluster/k3d.yaml`;
2. generates random S3 credentials into `.secrets/s3.env` (git-ignored) and loads them as Kubernetes Secrets;
3. builds the `cmdparser-tools` and `cmdparser-service` images and imports them into k3d;
4. deploys SeaweedFS in namespace `data` and runs the `storage-seed` Job. The Job creates the buckets `datasets`
   and `models`, uploads `commands_pool.jsonl`, the teacher shards and `train.jsonl`, and copies model v1 and
   model v2 from the GitHub Releases into `models/v1/` and `models/v2/`, checking every SHA-256;
5. deploys the service in namespace `app` and waits until `/parse` answers through the Ingress.

Try the service:

```bash
curl -i -X POST http://localhost:8080/parse -H 'Content-Type: application/json' -d '{"text": "set an alarm for seven thirty am tomorrow"}'
```

## Test

```bash
make setup && make setup-dev
```

```bash
make lint test nacl
```

```bash
make loadtest
```

`make loadtest` runs the standard Locust command (4 users, 2 minutes, `--host http://localhost:8080`) and writes
`results/loadtest_*`. The Task 4/7 experiments (cold start, load balancing, rolling update and rollback, recovery,
HPA) are run against the deployed system with `make experiments`.

## Train and evaluate

```bash
make train SUBSET=50
```

```bash
make train
```

```bash
make train-v2
```

```bash
make evaluate
```

`make train SUBSET=50` is a quick check that training runs; its output goes to `artifacts/models/subset-50/`.
`make train` reads only `training/config.yaml` and writes `artifacts/models/v1/` (git-ignored) and `training/loss.csv`.
To check a released model:

```bash
gh release download model-v1 --dir model-v1 && (cd model-v1 && sha256sum -c model.sha256)
```

## Data pipeline (Task 1)

To run the teacher and two workers in namespace `pipeline` on your own cluster (this takes hours on a CPU):

```bash
make teacher SHARDS=2
```

```bash
make clean-data
```

`make clean-data` re-runs `worker/clean.py` on `datasets/teacher/shard-*.jsonl` and reproduces
`datasets/v1/train.jsonl` and `datasets/v1/train.sha256` byte for byte.

## Shut down

```bash
make down
```

This deletes the k3d cluster, which removes SeaweedFS, the data and every deployment in it.

## GitHub Actions workflows

| Workflow | What it runs |
|---|---|
| `ci.yml` | lint + gitleaks secret scan → unit tests → model evaluation from the GitHub Release → quality gate (`score.py --min-validity 95`). Dispatch it with `model_tag=model-base` to see the gate fail |
| `teacher.yml` | Task 1 on k3d: SeaweedFS + Ollama + parallel workers (`mode=validation` or `pool`), then the clean Job |
| `train.yml` | Task 2: `make train`, `make train-v2`, the Releases, SeaweedFS `models/v1/` and `models/v2/`, evaluation |
| `service.yml` | Task 3: image build and size, no weights in the image, 50 sequential requests at 1 CPU / 1 GiB, `FAULT_INJECT=1` |
| `deploy.yml` | Tasks 4, 6 and 7: `make up` on a fresh runner, the experiments, cost and SLO, `make down` |
| `report.yml` | builds `report/report.pdf` |
| `package.yml` | builds `<roll_number>.zip` (report, handwritten reflection, source, README) and tags `final` |

All commits, including the ones the workflows push with results, are authored by the repository owner.
No credentials are stored in the repository: S3 keys are generated at deploy time and live only in Kubernetes Secrets.
