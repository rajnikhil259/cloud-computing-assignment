"""Inference service for the command parser (Task 3).

Endpoints (port 8000):
  POST /parse    {"text": "..."} -> 200 and the four-key JSON object, nothing else.
                 Headers: X-Model-Version (MODEL_VERSION) and X-Served-By (the Pod name).
                 If the model output does not match schema.json: 500 {"error": "invalid_model_output"}.
  GET  /healthz  200 while the process is alive.
  GET  /readyz   503 until the model is loaded, 200 after that.

Configuration comes only from these environment variables:
  MODEL_URI       s3:// prefix holding the model and tokenizer, e.g. s3://models/v1/
  MODEL_VERSION   reported in X-Model-Version, e.g. v1
  S3_ENDPOINT     the object storage endpoint, e.g. http://seaweedfs.data.svc.cluster.local:8333
  MAX_NEW_TOKENS  generation limit, e.g. 64
  FAULT_INJECT    "1" replaces the model output with "not json" before validation (testing only)
S3 credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) come from a Kubernetes Secret.
"""
import hashlib
import json
import logging
import os
import socket
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cmdparser")

HERE = os.path.dirname(os.path.abspath(__file__))
# schema.json sits next to app.py in the image; in the repository it is data/schema.json
SCHEMA_PATH = next(p for p in (os.path.join(HERE, "schema.json"), os.path.join(HERE, "..", "data", "schema.json"))
                   if os.path.exists(p))
CACHE_DIR = "/tmp/model"


def settings():
    return {
        "MODEL_URI": os.environ.get("MODEL_URI", ""),
        "MODEL_VERSION": os.environ.get("MODEL_VERSION", "unknown"),
        "S3_ENDPOINT": os.environ.get("S3_ENDPOINT", ""),
        "MAX_NEW_TOKENS": int(os.environ.get("MAX_NEW_TOKENS", "64")),
        "FAULT_INJECT": os.environ.get("FAULT_INJECT", "0").strip() == "1",
    }


with open(SCHEMA_PATH, encoding="utf-8") as _f:
    SCHEMA = json.load(_f)
VALIDATOR = Draft202012Validator(SCHEMA["json_schema"])


def validate_output(raw):
    """Return the parsed object if raw is valid against schema.json, else None."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict) or set(obj.keys()) != set(SCHEMA["keys"]):
        return None
    if not VALIDATOR.is_valid(obj):
        return None
    return obj


class State:
    def __init__(self):
        self.parser = None
        self.error = None
        self.lock = threading.Lock()


state = State()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_model(cfg, dest=CACHE_DIR):
    """Download every object under MODEL_URI and verify it against model.sha256 (if present)."""
    import boto3
    from botocore.config import Config

    uri = cfg["MODEL_URI"]
    if not uri.startswith("s3://"):
        raise ValueError(f"MODEL_URI must be an s3:// URI, got {uri!r}")
    bucket, _, prefix = uri[5:].partition("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    s3 = boto3.client("s3", endpoint_url=cfg["S3_ENDPOINT"], region_name="us-east-1",
                      config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                    retries={"max_attempts": 10, "mode": "standard"}))
    os.makedirs(dest, exist_ok=True)
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(o["Key"] for o in page.get("Contents", []))
    if not keys:
        raise FileNotFoundError(f"no objects under {uri}")
    t0 = time.time()
    total = 0
    for key in keys:
        name = key[len(prefix):]
        if not name or "/" in name:
            continue
        path = os.path.join(dest, name)
        s3.download_file(bucket, key, path)
        size = os.path.getsize(path)
        total += size
        log.info("downloaded s3://%s/%s from %s (%d bytes)", bucket, key, cfg["S3_ENDPOINT"], size)
    sha_path = os.path.join(dest, "model.sha256")
    if os.path.exists(sha_path):
        with open(sha_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                digest, name = line.split(None, 1)
                name = name.strip().lstrip("*")
                p = os.path.join(dest, name)
                if os.path.exists(p):
                    if sha256_file(p) != digest:
                        raise ValueError(f"checksum mismatch for {name}")
                    log.info("checksum ok: %s", name)
    log.info("model download from %s complete: %d bytes in %.1fs", uri, total, time.time() - t0)
    return dest


def load_model():
    cfg = settings()
    try:
        t0 = time.time()
        log.info("starting: MODEL_URI=%s MODEL_VERSION=%s S3_ENDPOINT=%s MAX_NEW_TOKENS=%s FAULT_INJECT=%s",
                 cfg["MODEL_URI"], cfg["MODEL_VERSION"], cfg["S3_ENDPOINT"], cfg["MAX_NEW_TOKENS"],
                 int(cfg["FAULT_INJECT"]))
        model_dir = download_model(cfg)
        from model import CommandParser

        parser = CommandParser(model_dir)
        parser.generate("set an alarm for seven am", 8)  # warm-up before reporting ready
        state.parser = parser
        log.info("model %s loaded and ready after %.1fs", cfg["MODEL_VERSION"], time.time() - t0)
    except Exception as e:  # keep the process alive (healthz) but never become ready
        state.error = repr(e)
        log.exception("model loading failed")


@asynccontextmanager
async def lifespan(_app):
    # Load in the background so /healthz answers at once and /readyz reports 503 meanwhile.
    threading.Thread(target=load_model, name="model-loader", daemon=True).start()
    yield


app = FastAPI(title="command parser", lifespan=lifespan)


class ParseRequest(BaseModel):
    text: str


def _headers():
    return {"X-Model-Version": settings()["MODEL_VERSION"], "X-Served-By": socket.gethostname()}


@app.get("/healthz")
def healthz():
    return {"status": "alive"}


@app.get("/readyz")
def readyz():
    if state.parser is None:
        return JSONResponse({"status": "loading" if state.error is None else "failed"}, status_code=503)
    return {"status": "ready", "model_version": settings()["MODEL_VERSION"]}


@app.post("/parse")
def parse(req: ParseRequest):
    cfg = settings()
    if state.parser is None:
        return JSONResponse({"error": "model_not_ready"}, status_code=503, headers=_headers())
    with state.lock:  # one generation at a time per process; the pod's CPU limit is the bottleneck
        raw = state.parser.generate(req.text, cfg["MAX_NEW_TOKENS"])
    if cfg["FAULT_INJECT"]:
        raw = "not json"
    obj = validate_output(raw)
    if obj is None:
        log.warning("invalid model output for %r: %r", req.text, raw)
        return JSONResponse({"error": "invalid_model_output"}, status_code=500, headers=_headers())
    return JSONResponse({k: obj[k] for k in SCHEMA["keys"]}, status_code=200, headers=_headers())
