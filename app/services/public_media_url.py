"""Centralized helper for turning a stored media URL into one an external
provider (fal.ai/Seedance) can actually fetch, and for verifying it's really
reachable before a paid provider request is submitted.

Two responsibilities live here on purpose, not scattered across callers:

1. ``normalize_public_media_url`` — expand AI Film OS's own ``/generated/...``
   paths into a public HTTPS URL, and reject anything that isn't a genuine
   public HTTPS endpoint (no localhost/private/link-local/reserved hosts, no
   non-HTTPS schemes such as data:/blob:/file:/http:).
2. ``preflight_check_public_image`` — before paying for a provider request,
   make a short, bounded server-side fetch that proves the URL is currently
   reachable, returns 2xx, serves image/*, and doesn't redirect to a private
   host. This catches a stale/broken/not-yet-propagated URL before it costs
   money, rather than after.
"""

import ipaddress
import os
from urllib.parse import urljoin, urlparse

import httpx

_MAX_PREFLIGHT_REDIRECTS = 5
_MAX_PREFLIGHT_BYTES = 25 * 1024 * 1024  # 25 MB — generous for a single shot image
_PREFLIGHT_TIMEOUT_SECONDS = 6.0
_PREFLIGHT_READ_CHUNK_BYTES = 65536


class PublicMediaUrlError(ValueError):
    """A stable, sanitized reason a media URL failed normalization or preflight.

    ``str(exc)`` is built only from the fixed reason vocabulary below — never
    from provider/response text — so it stays safe to persist and to show in
    the UI.
    """

    EMPTY = "empty"
    NOT_HTTPS = "not_https"
    PRIVATE_HOST = "private_host"
    NO_PUBLIC_BASE_CONFIGURED = "no_public_base_configured"
    UNREACHABLE = "unreachable"
    WRONG_CONTENT_TYPE = "wrong_content_type"
    TOO_LARGE = "too_large"
    TOO_MANY_REDIRECTS = "too_many_redirects"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Source image is not publicly accessible: {reason}")


def _is_public_host(hostname: str) -> bool:
    host = hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def normalize_public_media_url(url: str) -> str:
    """Return an HTTPS URL an external provider can fetch, or raise.

    A leading ``/`` is treated as an AI Film OS-relative path (e.g.
    ``/generated/uploads/shot-1/<uuid>.png``) and expanded against
    ``PUBLIC_BASE_URL`` (or ``RENDER_EXTERNAL_URL`` as a fallback). Anything
    else must already be an absolute public HTTPS URL.
    """
    value = str(url or "").strip()
    if not value:
        raise PublicMediaUrlError(PublicMediaUrlError.EMPTY)

    if value.startswith("/"):
        public_base = (
            os.getenv("PUBLIC_BASE_URL", "").strip()
            or os.getenv("RENDER_EXTERNAL_URL", "").strip()
        )
        if not public_base:
            raise PublicMediaUrlError(PublicMediaUrlError.NO_PUBLIC_BASE_CONFIGURED)
        base = urlparse(public_base)
        if base.scheme != "https" or not base.hostname:
            raise PublicMediaUrlError(PublicMediaUrlError.NOT_HTTPS)
        return f"{public_base.rstrip('/')}/{value.lstrip('/')}"

    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PublicMediaUrlError(PublicMediaUrlError.NOT_HTTPS)
    if not _is_public_host(parsed.hostname):
        raise PublicMediaUrlError(PublicMediaUrlError.PRIVATE_HOST)
    return value


def preflight_check_public_image(
    url: str,
    *,
    timeout: float = _PREFLIGHT_TIMEOUT_SECONDS,
    max_redirects: int = _MAX_PREFLIGHT_REDIRECTS,
    max_bytes: int = _MAX_PREFLIGHT_BYTES,
) -> None:
    """Make a short, bounded fetch proving ``url`` is a reachable public image.

    Raises ``PublicMediaUrlError`` (never returns a value) if the URL is not
    a public HTTPS host, doesn't respond 2xx, doesn't serve ``image/*``, is
    too large, or redirects to a non-public host. Manually follows redirects
    (rather than trusting an HTTP client's automatic follow) so every hop is
    re-validated against the same private-network rules as the original URL —
    a public URL that redirects to an internal host must not pass.

    This never downloads more than a small chunk of the body; it is a
    readiness check, not a full fetch, and must never be used as a substitute
    for the provider's own download.
    """
    current = url
    for _ in range(max_redirects + 1):
        parsed = urlparse(current)
        if parsed.scheme != "https" or not parsed.hostname:
            raise PublicMediaUrlError(PublicMediaUrlError.NOT_HTTPS)
        if not _is_public_host(parsed.hostname):
            raise PublicMediaUrlError(PublicMediaUrlError.PRIVATE_HOST)

        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise PublicMediaUrlError(PublicMediaUrlError.UNREACHABLE)
                        current = urljoin(current, location)
                        continue

                    if not (200 <= response.status_code < 300):
                        raise PublicMediaUrlError(PublicMediaUrlError.UNREACHABLE)

                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if not content_type.startswith("image/"):
                        raise PublicMediaUrlError(PublicMediaUrlError.WRONG_CONTENT_TYPE)

                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_size = int(content_length)
                        except ValueError:
                            declared_size = None
                        if declared_size is not None and declared_size > max_bytes:
                            raise PublicMediaUrlError(PublicMediaUrlError.TOO_LARGE)

                    read_bytes = 0
                    for chunk in response.iter_bytes(chunk_size=_PREFLIGHT_READ_CHUNK_BYTES):
                        read_bytes += len(chunk)
                        if read_bytes > max_bytes:
                            raise PublicMediaUrlError(PublicMediaUrlError.TOO_LARGE)
                        break  # one chunk is enough to prove the body is real
                    return
        except httpx.RequestError:
            raise PublicMediaUrlError(PublicMediaUrlError.UNREACHABLE)
    raise PublicMediaUrlError(PublicMediaUrlError.TOO_MANY_REDIRECTS)
