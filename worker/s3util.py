"""Small helpers around boto3 for the SeaweedFS S3 gateway.

Credentials are read from the standard AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
environment variables, which Kubernetes fills from a Secret. Nothing is hard-coded.
"""
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def client(endpoint=None):
    endpoint = endpoint or os.environ["S3_ENDPOINT"]
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=Config(signature_version="s3v4",
                      s3={"addressing_style": "path"},
                      retries={"max_attempts": 10, "mode": "standard"}),
    )


def split_uri(uri):
    """'s3://models/v1/' -> ('models', 'v1/')"""
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3:// URI: {uri}")
    bucket, _, key = uri[len("s3://"):].partition("/")
    return bucket, key


def get_text(s3, bucket, key):
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")


def get_text_or_none(s3, bucket, key):
    try:
        return get_text(s3, bucket, key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
            return None
        raise


def put_text(s3, bucket, key, text, content_type="application/x-ndjson"):
    s3.put_object(Bucket=bucket, Key=key, Body=text.encode("utf-8"), ContentType=content_type)


def list_keys(s3, bucket, prefix=""):
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(o["Key"] for o in page.get("Contents", []))
    return sorted(keys)


def ensure_bucket(s3, bucket):
    try:
        s3.head_bucket(Bucket=bucket)
        return False
    except ClientError:
        s3.create_bucket(Bucket=bucket)
        return True
