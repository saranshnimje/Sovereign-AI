"""
Neon Object Storage service — S3-compatible storage for document binaries.

All document uploads, downloads, and deletes go through this module.
Backend is the sole component that ever touches Object Storage —
credentials are never exposed to the frontend.

Environment variables:
    NEON_STORAGE_ENDPOINT      — S3-compatible endpoint URL
    NEON_STORAGE_REGION        — AWS region (default: us-east-2)
    NEON_STORAGE_ACCESS_KEY_ID — access key
    NEON_STORAGE_SECRET_ACCESS_KEY — secret key
    NEON_STORAGE_BUCKET        — bucket name
"""
from __future__ import annotations

import logging

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from config import get_settings

logger = logging.getLogger(__name__)

# ── Lazy singleton ──────────────────────────────────────────────

_s3_client = None


def _get_client():
    """Return a lazily-initialised boto3 S3 client."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client

    settings = get_settings()
    endpoint = settings.neon_storage_endpoint
    access_key = settings.neon_storage_access_key
    secret_key = settings.neon_storage_secret_key
    region = settings.neon_storage_region

    if not all([endpoint, access_key, secret_key]):
        logger.warning(
            "Neon Object Storage credentials not configured — "
            "uploads/downloads to object storage will fail."
        )
        return None

    _s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region or "us-east-2",
        config=BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )
    return _s3_client


# ── Public helpers ──────────────────────────────────────────────


def is_available() -> bool:
    """Return True if object storage credentials are configured."""
    return _get_client() is not None


def _bucket() -> str:
    settings = get_settings()
    if not settings.neon_storage_bucket:
        raise RuntimeError("NEON_STORAGE_BUCKET is not set")
    return settings.neon_storage_bucket


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Upload raw bytes to object storage."""
    client = _get_client()
    if client is None:
        raise RuntimeError("Object storage not configured")
    client.put_object(
        Bucket=_bucket(),
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    logger.info("Uploaded to object storage", extra={"key": key, "size": len(data)})


def upload_file(key: str, local_path: str, content_type: str = "application/octet-stream") -> None:
    """Upload a local file to object storage."""
    client = _get_client()
    if client is None:
        raise RuntimeError("Object storage not configured")
    client.upload_file(
        Filename=local_path,
        Bucket=_bucket(),
        Key=key,
        ExtraArgs={"ContentType": content_type},
    )
    logger.info("Uploaded file to object storage", extra={"key": key})


def download_bytes(key: str) -> bytes:
    """Download an object and return its bytes."""
    client = _get_client()
    if client is None:
        raise RuntimeError("Object storage not configured")
    resp = client.get_object(Bucket=_bucket(), Key=key)
    return resp["Body"].read()


def download_to_file(key: str, local_path: str) -> None:
    """Download an object to a local file path."""
    client = _get_client()
    if client is None:
        raise RuntimeError("Object storage not configured")
    client.download_file(
        Bucket=_bucket(),
        Key=key,
        Filename=local_path,
    )


def delete_object(key: str) -> None:
    """Delete an object from storage. No-op if the key does not exist."""
    client = _get_client()
    if client is None:
        return
    try:
        client.delete_object(Bucket=_bucket(), Key=key)
        logger.info("Deleted from object storage", extra={"key": key})
    except ClientError as exc:
        logger.warning("Failed to delete object", extra={"key": key, "error": str(exc)})


def get_presigned_url(key: str, expires_in: int = 3600) -> str | None:
    """Return a presigned download URL (for direct frontend access if needed later)."""
    client = _get_client()
    if client is None:
        return None
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=expires_in,
    )


def object_exists(key: str) -> bool:
    """Check whether an object exists in storage."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.head_object(Bucket=_bucket(), Key=key)
        return True
    except ClientError:
        return False
