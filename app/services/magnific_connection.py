import time

import httpx

from app.core.config import settings


PROBE_TASK_ID = "ai-film-os-connection-probe"


def check_magnific_connection() -> dict:
    """Validate Magnific network access and API-key acceptance without creating media."""
    if not settings.magnific_api_key:
        return {
            "connected": False,
            "status": "not_configured",
            "message": "MAGNIFIC_API_KEY אינו מוגדר בסביבת ההפעלה.",
            "http_status": None,
            "latency_ms": None,
        }

    url = (
        f"{settings.magnific_api_base}/v1/ai/text-to-image/"
        f"nano-banana-pro/{PROBE_TASK_ID}"
    )
    headers = {
        "x-magnific-api-key": settings.magnific_api_key,
        "Accept": "application/json",
        "User-Agent": "AI-Film-OS/connection-check",
    }
    started = time.perf_counter()

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
    except httpx.TimeoutException:
        return {
            "connected": False,
            "status": "timeout",
            "message": "החיבור ל־Magnific חרג מזמן ההמתנה.",
            "http_status": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    except httpx.RequestError as exc:
        return {
            "connected": False,
            "status": "network_error",
            "message": f"לא ניתן להגיע ל־Magnific: {exc.__class__.__name__}",
            "http_status": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }

    latency_ms = round((time.perf_counter() - started) * 1000)

    # A missing probe task is expected. A 404 confirms that the API endpoint was
    # reached and the supplied key was accepted, without starting a paid job.
    if response.status_code == 404:
        return {
            "connected": True,
            "status": "connected",
            "message": "החיבור ל־Magnific תקין והמפתח התקבל.",
            "http_status": response.status_code,
            "latency_ms": latency_ms,
        }

    if response.status_code in {401, 403}:
        return {
            "connected": False,
            "status": "invalid_key",
            "message": "Magnific דחה את מפתח ה־API. יש לעדכן את MAGNIFIC_API_KEY.",
            "http_status": response.status_code,
            "latency_ms": latency_ms,
        }

    if 200 <= response.status_code < 300:
        return {
            "connected": True,
            "status": "connected",
            "message": "החיבור ל־Magnific תקין.",
            "http_status": response.status_code,
            "latency_ms": latency_ms,
        }

    return {
        "connected": False,
        "status": "provider_error",
        "message": "Magnific החזיר תגובה לא צפויה. יש לנסות שוב מאוחר יותר.",
        "http_status": response.status_code,
        "latency_ms": latency_ms,
    }
