# Inference service image. Contains code and pinned libraries only: the model and tokenizer
# are downloaded from object storage (MODEL_URI) when the container starts.
# Build from the repository root:  docker build -f service/Dockerfile -t cmdparser-service:1.0 .
FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
WORKDIR /app

COPY service/requirements.txt /tmp/requirements.txt
RUN pip install --no-deps -r /tmp/requirements.txt && pip check \
 && find /usr/local/lib/python3.12 -name "__pycache__" -type d -prune -exec rm -rf {} + \
 && rm -rf /usr/local/lib/python3.12/site-packages/torch/include /root/.cache

COPY service/app.py service/model.py /app/
COPY data/schema.json /app/schema.json

RUN useradd --uid 10001 --no-create-home appuser
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "20", "--no-access-log"]
