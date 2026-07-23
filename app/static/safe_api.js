// Safe, provider-neutral response parsing for browser API calls.
// Raw HTML, proxy pages, and provider payloads are never surfaced to users.

class FilmOsApiError extends Error {
  constructor(message, { status = 0, code = "api_error", retryable = false } = {}) {
    super(message);
    this.name = "FilmOsApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

function isJsonContentType(contentType) {
  return /(^|\s|;)application\/(?:[a-z0-9.+-]*\+)?json(?:\s*;|$)/i.test(contentType || "");
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
    const safeDetail = data && typeof data.detail === "string" && data.detail.trim()
      ? data.detail.trim()
      : "אירעה שגיאה בבקשה.";
    throw new FilmOsApiError(safeDetail, {
      status,
      code: data && typeof data.code === "string" ? data.code : "http_error",
      retryable: data && typeof data.retryable === "boolean" ? data.retryable : retryable,
    });
  }

  return data;
}

if (typeof window !== "undefined") {
  window.FilmOsApiError = FilmOsApiError;
  window.parseApiResponse = parseApiResponse;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { FilmOsApiError, isJsonContentType, parseApiResponse };
}
