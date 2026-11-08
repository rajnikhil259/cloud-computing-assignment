"""Seed SeaweedFS (runs as the Job "storage-seed" in namespace data).

1. Creates the buckets "datasets" and "models".
2. Uploads the files baked into this image from the repository:
     data/commands_pool.jsonl        -> s3://datasets/commands_pool.jsonl
     data/validation.jsonl (text)    -> s3://datasets/eval/validation_texts.jsonl  (teacher evaluation input only)
     datasets/teacher/shard-*.jsonl  -> s3://datasets/teacher/
     datasets/v1/*                   -> s3://datasets/v1/
3. When SEED_MODELS is "1" or "auto", downloads each model version from the GitHub Release
   "model-<version>" of MODEL_RELEASE_REPO, checks every file against model.sha256 and
   uploads model + tokenizer to s3://models/<version>/. With "auto", a missing release is a
   warning (e.g. before the first training run), with "1" it is an error.
"""
import glob
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

import s3util

APP = os.environ.get("APP_DIR", "/app")


def upload_file(s3, path, bucket, key):
    s3.upload_file(path, bucket, key)
    print(f"  uploaded {os.path.relpath(path, APP)} -> s3://{bucket}/{key} ({os.path.getsize(path)} bytes)")


def fetch(url, dest, tries=5):
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        return
                    f.write(chunk)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = e
        print(f"  download failed ({err}), attempt {attempt}/{tries}")
        time.sleep(3 * attempt)
    raise RuntimeError(f"could not download {url}")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_sha_file(text):
    out = {}
    for line in text.splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            out[name.strip().lstrip("*")] = digest
    return out


def seed_models(s3, repo, version, required):
    base = f"https://github.com/{repo}/releases/download/model-{version}"
    work = f"/tmp/models/{version}"
    os.makedirs(work, exist_ok=True)
    sha_path = os.path.join(work, "model.sha256")
    try:
        fetch(f"{base}/model.sha256", sha_path)
    except urllib.error.HTTPError as e:
        msg = f"release model-{version} not found in {repo} ({e.code})"
        if required:
            sys.exit(msg)
        print(f"  WARNING: {msg}; skipping models/{version}/")
        return
    with open(sha_path, encoding="utf-8") as f:
        expected = parse_sha_file(f.read())
    repo_copy = os.path.join(APP, "models", version, "model.sha256")
    if os.path.exists(repo_copy):
        with open(repo_copy, encoding="utf-8") as f:
            if parse_sha_file(f.read()) != expected:
                sys.exit(f"model.sha256 of release model-{version} differs from the copy in the repository")
    files = [n for n in expected if not n.endswith(".tar.gz")]
    for name in files:
        dest = os.path.join(work, name)
        fetch(f"{base}/{name}", dest)
        got = sha256_file(dest)
        if got != expected[name]:
            sys.exit(f"checksum mismatch for {name}: {got} != {expected[name]}")
        print(f"  verified {name} sha256={got[:16]}...")
        upload_file(s3, dest, "models", f"{version}/{name}")
    upload_file(s3, sha_path, "models", f"{version}/model.sha256")


def main():
    s3 = s3util.client()
    for b in ("datasets", "models"):
        print(f"bucket {b}: {'created' if s3util.ensure_bucket(s3, b) else 'already exists'}")

    print("datasets:")
    upload_file(s3, os.path.join(APP, "data/commands_pool.jsonl"), "datasets", "commands_pool.jsonl")
    with open(os.path.join(APP, "data/validation.jsonl"), encoding="utf-8") as f:
        texts = [{"id": r["id"], "text": r["text"]} for r in map(json.loads, filter(str.strip, f))]
    s3util.put_text(s3, "datasets", "eval/validation_texts.jsonl",
                    "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in texts))
    print(f"  uploaded {len(texts)} validation command texts -> s3://datasets/eval/validation_texts.jsonl")
    for path in sorted(glob.glob(os.path.join(APP, "datasets/teacher/*.jsonl"))):
        upload_file(s3, path, "datasets", "teacher/" + os.path.basename(path))
    for path in sorted(glob.glob(os.path.join(APP, "datasets/v1/*"))):
        upload_file(s3, path, "datasets", "v1/" + os.path.basename(path))

    mode = os.environ.get("SEED_MODELS", "auto").strip().lower()
    repo = os.environ.get("MODEL_RELEASE_REPO", "").strip()
    if mode in ("1", "auto") and repo:
        for v in os.environ.get("MODEL_VERSIONS", "v1 v2").split():
            print(f"models/{v}/ from release model-{v} of {repo}:")
            seed_models(s3, repo, v, required=(mode == "1"))
    else:
        print("model seeding skipped (SEED_MODELS=%s, MODEL_RELEASE_REPO=%r)" % (mode, repo))

    print("\nobject storage contents:")
    for b in ("datasets", "models"):
        for k in s3util.list_keys(s3, b):
            size = s3.head_object(Bucket=b, Key=k)["ContentLength"]
            print(f"  s3://{b}/{k}  {size}")


if __name__ == "__main__":
    main()
