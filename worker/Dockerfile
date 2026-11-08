# Tools image for the data pipeline: teacher-labelling worker, cleaner and storage seeder.
# Build from the repository root:  docker build -f worker/Dockerfile -t cmdparser-tools:1.0 .
FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/worker

COPY worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-deps -r /tmp/requirements.txt && pip check

# Code plus the small text datasets kept in Git (no model weights: those live in object storage).
COPY worker/*.py /app/worker/
COPY data/commands_pool.jsonl data/validation.jsonl data/schema.json /app/data/
COPY datasets/ /app/datasets/
COPY models/ /app/models/

RUN useradd --uid 10001 --no-create-home appuser
USER 10001
CMD ["python", "-u", "worker.py"]
