"""S3-compatible object storage (SeaweedFS locally). Objects are never served directly to browsers:
every download is streamed through the API after authorization, so there are no pre-signed URLs to leak."""
from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_settings


@lru_cache
def client():
    s = get_settings()
    access, secret = s.s3_credentials()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="us-east-1",
        config=Config(
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def ensure_bucket() -> None:
    bucket = get_settings().s3_bucket
    try:
        client().head_bucket(Bucket=bucket)
    except ClientError:
        client().create_bucket(Bucket=bucket)


def put(key: str, data: bytes, content_type: str) -> None:
    client().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=data, ContentType=content_type)


def get(key: str) -> bytes:
    return client().get_object(Bucket=get_settings().s3_bucket, Key=key)["Body"].read()


def delete(key: str) -> None:
    client().delete_object(Bucket=get_settings().s3_bucket, Key=key)


def list_keys(prefix: str = "") -> list[str]:
    keys: list[str] = []
    paginator = client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=get_settings().s3_bucket, Prefix=prefix):
        keys.extend(o["Key"] for o in page.get("Contents", []))
    return keys


def healthy() -> tuple[bool, str]:
    try:
        client().head_bucket(Bucket=get_settings().s3_bucket)
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__
