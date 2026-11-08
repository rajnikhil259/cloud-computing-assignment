# Command-parser project: knowledge distillation (phi3.5 -> pythia-70m) deployed on k3d.
SHELL := /bin/bash
# Use the project virtualenv if `make setup` created one.
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
SUBSET ?=
SHARDS ?= 2

.PHONY: help up down cluster secrets storage images deploy status setup setup-dev train train-v2 \
        evaluate teacher clean-data test lint loadtest nacl

help:            ## list the targets
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

# ---- whole system ------------------------------------------------------------------------
up:              ## build and deploy everything from a fresh clone (needs docker, k3d, kubectl, curl)
	scripts/up.sh

down:            ## delete the k3d cluster (and everything in it)
	k3d cluster delete cmdparser

# ---- individual steps --------------------------------------------------------------------
cluster:         ## create the k3d cluster from cluster/k3d.yaml
	scripts/cluster_up.sh
secrets:         ## generate S3 credentials (.secrets/, git-ignored) and load them as Secrets
	scripts/secrets.sh
images:          ## build cmdparser-tools and cmdparser-service and import them into k3d
	scripts/build_images.sh all
storage:         ## SeaweedFS in namespace data + buckets, datasets and models
	scripts/storage_up.sh
deploy:          ## deploy the service in namespace app
	scripts/deploy_app.sh
status:          ## show what is running
	kubectl get pods,svc,ingress,hpa -A -o wide

teacher:         ## label commands_pool.jsonl with phi3.5 using $(SHARDS) parallel workers (hours on a CPU)
	scripts/run_teacher.sh $(SHARDS) "$$(seq -s ' ' 0 $$(($(SHARDS)-1)))"
clean-data:      ## rebuild datasets/v1/train.jsonl + train.sha256 from datasets/teacher/shard-*.jsonl
	$(PY) worker/clean.py --input-dir datasets/teacher --output-dir datasets/v1 --report results/task1/clean_report.json

# ---- training and evaluation --------------------------------------------------------------
setup:           ## create .venv with the pinned training/evaluation dependencies (CPU PyTorch)
	python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -r training/requirements.txt
setup-dev:       ## add the lint/test tools to .venv
	.venv/bin/pip install -r tests/requirements.txt

train:           ## fine-tune pythia-70m (v1) from training/config.yaml; `make train SUBSET=50` for a quick check
	$(PY) training/train.py --config training/config.yaml $(if $(SUBSET),--subset $(SUBSET),)

train-v2:        ## train the second version (variants.v2 in training/config.yaml)
	$(PY) training/train.py --config training/config.yaml --version v2

evaluate:        ## score artifacts/models/v1 on data/validation.jsonl
	$(PY) training/predict.py --model artifacts/models/v1 --input data/validation.jsonl \
	  --output results/student_v1_validation_predictions.jsonl
	$(PY) tools/score.py results/student_v1_validation_predictions.jsonl data/validation.jsonl \
	  --out results/student_v1_validation.json

# ---- checks -------------------------------------------------------------------------------
lint:            ## ruff
	$(PY) -m ruff check .
test:            ## unit tests
	$(PY) -m pytest
nacl:            ## check the NACL with the kit's simulator
	python3 tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check
loadtest:        ## the standard load test through the ingress (results/loadtest_*)
	locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m \
	  --host http://localhost:8080 --csv results/loadtest
