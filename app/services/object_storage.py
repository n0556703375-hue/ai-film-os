"""S3-compatible object storage for generated media (images/video).

Render's free tier has no persistent disk — every deploy/restart wipes
whatever was written under ``GENERATED_MEDIA_PATH`` while ``media_results``
rows keep pointing at now-missing files. This module lets generated media be
written to any S3-compatible bucket instead (Cloudflare R2, AWS S3, Backblaze
B2 — all speak the same signed-request protocol), so it survives deploys.

Deliberately hand-rolled AWS Signature Version 4 signing over ``httpx``
rather than adding the boto3/botocore dependency (a large SDK this project
otherwise has no use for) — this mirrors how every other provider adapter in
app/services/ (kling_provider.py, seedance_provider.py, sync_provider.py)
talks to its API directly rather than through a vendor SDK. Path-style
requests (``{endpoint}/{bucket}/{key}``) are used throughout, since that
addressing form is the one all three target providers document support for.

Configuration is environment-only, never persisted to the database:
    OBJECT_STORAGE_ENDPOINT       — S3 API endpoint, e.g.
                                     https://<accountid>.r2.cloudflarestorage.com
    OBJECT_STORAGE_BUCKET         — bucket name
    OBJECT_STORAGE_ACCESS_KEY     — access key id
    OBJECT_STORAGE_SECRET_KEY     — secret access key (never logged)
    OBJECT_STORAGE_REGION         — signing region (default "auto", R2's own
                                     default; AWS S3/B2 need their real region)
    OBJECT_STORAGE_PUBLIC_URL_BASE — public base URL media is served from
                                     once uploaded (a public bucket domain,
                                     CDN, or custom domain — NOT the signed
                                     API endpoint above, which requires auth
                                     on every request). Required for uploaded
                                     URLs to actually be fetchable by the
                                     browser or by external providers
                                     (fal.ai, Magnific) — without it,
                                     is_configured() is False and callers
                                     fall back to local disk storage.

When any of these is unset, ``is_configured()`` is False and every caller in
this codebase falls back to the pre-existing local-disk behavior (see
app/services/media_upload.py and app/services/video_persistence.py), logging
a clear warning that media will not survive a restart in that mode.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_SERVICE = "s3"
_UPLOAD_TIMEOUT_SECONDS = 60.0


class ObjectStorageError(RuntimeError):
    """A stable, sanitized reason an object storage operation failed.

    ``str(exc)`` never includes response bodies or credentials — only the
    fixed reason vocabulary below, safe to log or persist.
    """

    NOT_CONFIGURED = "not_configured"
    UPLOAD_FAILED = "upload_failed"
    DELETE_FAILED = "delete_failed"
    UNREACHABLE = "unreachable"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"object_storage_error: {reason}")


def is_configured() -> bool:
    return bool(
        settings.object_storage_endpoint
        and settings.object_storage_bucket
        and settings.object_storage_access_key
        and settings.object_storage_secret_key
        and settings.object_storage_public_url_base
    )


def _require_configured() -> None:
    if not is_configured():
        raise ObjectStorageError(ObjectStorageError.NOT_CONFIGURED)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, data: str) -> bytes:
    return hmac.new(key, data.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
    k_date = _hmac(f"AWS4{secret_key}".encode("utf-8"), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, _SERVICE)
    return _hmac(k_service, "aws4_request")


def _encode_path(path: str) -> str:
    # Every "/"-separated segment is percent-encoded on its own so the
    # separator itself is preserved — required by SigV4's canonical URI.
    return "/".join(quote(segment, safe="-_.~") for segment in path.split("/"))


def _signed_request(
    method: str,
    key: str,
    *,
    body: bytes = b"",
    content_type: str | None = None,
) -> httpx.Response:
    """Issue one SigV4-signed request against the configured bucket.

    Raises ``ObjectStorageError`` on any transport failure; a non-2xx HTTP
    response is returned to the caller to interpret (e.g. HEAD's 404 is a
    normal "does not exist" answer, not a failure).
    """
    _require_configured()

    endpoint = settings.object_storage_endpoint.rstrip("/")
    bucket = settings.object_storage_bucket
    region = settings.object_storage_region or "auto"
    access_key = settings.object_storage_access_key
    secret_key = settings.object_storage_secret_key

    parsed = urlparse(endpoint)
    host = parsed.netloc
    canonical_uri = _encode_path(f"/{bucket}/{key}")
    url = f"{parsed.scheme}://{host}{canonical_uri}"

    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = _sha256_hex(body)

    headers = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if content_type:
        headers["content-type"] = content_type

    signed_header_names = sorted(headers)
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in signed_header_names)
    signed_headers = ";".join(signed_header_names)

    canonical_request = "\n".join([
        method,
        canonical_uri,
        "",  # no query string
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    credential_scope = f"{date_stamp}/{region}/{_SERVICE}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        _sha256_hex(canonical_request.encode("utf-8")),
    ])

    signature = hmac.new(
        _signing_key(secret_key, date_stamp, region), string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    request_headers = {
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        "Authorization": authorization,
    }
    if content_type:
        request_headers["Content-Type"] = content_type

    try:
        with httpx.Client(timeout=_UPLOAD_TIMEOUT_SECONDS) as client:
            return client.request(method, url, content=body or None, headers=request_headers)
    except httpx.RequestError as exc:
        raise ObjectStorageError(ObjectStorageError.UNREACHABLE) from exc


def _public_url(key: str) -> str:
    base = settings.object_storage_public_url_base.rstrip("/")
    return f"{base}/{_encode_path(key).lstrip('/')}"


def upload(content: bytes, key: str, content_type: str) -> str:
    """Upload ``content`` under ``key`` and return its public URL.

    ``key`` should already be a safe, non-user-derived path (e.g.
    ``uploads/shot-7/<uuid>.png``) — this function does no sanitization of
    its own, matching the existing local-disk callers that build the key
    the same way they build a filesystem path today.
    """
    response = _signed_request("PUT", key, body=content, content_type=content_type)
    if response.status_code >= 300:
        logger.warning("object_storage upload failed: status=%s key=%s", response.status_code, key)
        raise ObjectStorageError(ObjectStorageError.UPLOAD_FAILED)
    return _public_url(key)


def delete(key: str) -> None:
    response = _signed_request("DELETE", key)
    # S3-compatible DELETE is idempotent: a 404 means it's already gone,
    # which is exactly the caller's desired end state, not a failure.
    if response.status_code >= 300 and response.status_code != 404:
        logger.warning("object_storage delete failed: status=%s key=%s", response.status_code, key)
        raise ObjectStorageError(ObjectStorageError.DELETE_FAILED)


def exists(key: str) -> bool:
    response = _signed_request("HEAD", key)
    return response.status_code < 300
