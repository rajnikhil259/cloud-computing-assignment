"""Host-side S3 helper for the SeaweedFS gateway exposed by k3d at http://localhost:8333.

  python scripts/s3_sync.py ls BUCKET [PREFIX]
  python scripts/s3_sync.py get BUCKET KEY DEST
  python scripts/s3_sync.py get-prefix BUCKET PREFIX DEST_DIR
  python scripts/s3_sync.py put SRC BUCKET KEY

Credentials come from .secrets/s3.env (written by scripts/secrets.sh) or the environment.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "worker"))


def load_env():
    path = os.path.join(ROOT, ".secrets", "s3.env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)
    os.environ.setdefault("S3_ENDPOINT", "http://localhost:8333")


def main(argv):
    load_env()
    import s3util

    s3 = s3util.client()
    cmd = argv[0]
    if cmd == "ls":
        for k in s3util.list_keys(s3, argv[1], argv[2] if len(argv) > 2 else ""):
            print(f"s3://{argv[1]}/{k}\t{s3.head_object(Bucket=argv[1], Key=k)['ContentLength']}")
    elif cmd == "get":
        os.makedirs(os.path.dirname(argv[3]) or ".", exist_ok=True)
        s3.download_file(argv[1], argv[2], argv[3])
    elif cmd == "get-prefix":
        for k in s3util.list_keys(s3, argv[1], argv[2]):
            dest = os.path.join(argv[3], k[len(argv[2]):].lstrip("/"))
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            s3.download_file(argv[1], k, dest)
            print(f"s3://{argv[1]}/{k} -> {dest}")
    elif cmd == "put":
        s3.upload_file(argv[1], argv[2], argv[3])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:] or ["help"])
