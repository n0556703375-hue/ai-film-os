// Safe, provider-neutral response parsing for browser API calls.
// Raw HTML, proxy pages, and provider payloads are never surfaced to users.

const SAFE_PROGRESS_FIELDS = [
  "completed_stages",
  "failed_stage",
  "scenes_created",
  "shots_created",
  "failed_scene_id",
  "failed_scene_number",
];

class FilmOsApiError extends Error {
  constructor(message, { status = 0, code = "api_error", retryable = false, progress = null } = {}) {
    super(message);
    this.name = "FilmOsApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.progress = progress;
  }
}

function isJsonContentType(contentType) {
  return /(^|\s|;)application\/(?:[a-z0-9.+-]*\+)?json(?:\s*;|$)/i.test(contentType || "");
}

function safeProgress(detail) {
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const progress = {};
  for (const field of SAFE_PROGRESS_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(detail, field)) progress[field] = detail[field];
  }
  return Object.keys(progress).length ? progress : null;
}

async function parseApiResponse(response) {
  const status = Number(response.status || 0);
  const retryable = [408, 429, 502, 503, 504].includes(status);
  const contentType = response.headers && typeof response.headers.get === "function"
    ? response.headers.get("content-type") || ""
    : "";
  const body = await response.text();

  if (!body.trim()) {
    if (response.ok) return null;
    throw new FilmOsApiError("השרת החזיר תשובה ריקה.", {
      status,
      code: "empty_response",
      retryable,
    });
  }

  if (!isJsonContentType(contentType)) {
    throw new FilmOsApiError("השרת החזיר תשובה שאינה תקינה.", {
      status,
      code: "non_json_response",
      retryable,
    });
  }

  let data;
  try {
    data = JSON.parse(body);
  } catch (_error) {
    throw new FilmOsApiError("השרת החזיר תשובה שאינה תקינה.", {
      status,
      code: "malformed_json",
      retryable,
    });
  }

  if (!response.ok) {
    const detail = data && data.detail;
    const structuredDetail = detail && typeof detail === "object" && !Array.isArray(detail) ? detail : null;
    const safeDetail = typeof detail === "string" && detail.trim()
      ? detail.trim()
      : structuredDetail && typeof structuredDetail.message === "string" && structuredDetail.message.trim()
        ? structuredDetail.message.trim()
        : "אירעה שגיאה בבקשה.";
    throw new FilmOsApiError(safeDetail, {
      status,
      code: structuredDetail && typeof structuredDetail.code === "string"
        ? structuredDetail.code
        : data && typeof data.code === "string" ? data.code : "http_error",
      retryable: structuredDetail && typeof structuredDetail.retryable === "boolean"
        ? structuredDetail.retryable
        : data && typeof data.retryable === "boolean" ? data.retryable : retryable,
      progress: safeProgress(structuredDetail),
    });
  }

  return data;
}

if (typeof window !== "undefined") {
  window.FilmOsApiError = FilmOsApiError;
  window.parseApiResponse = parseApiResponse;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { FilmOsApiError, isJsonContentType, parseApiResponse, safeProgress };
}
