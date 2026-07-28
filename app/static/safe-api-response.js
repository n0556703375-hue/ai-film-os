(() => {
  const originalFetch = window.fetch.bind(window);

  function normalizedErrorPayload(message, code, status) {
    return {
      detail: message,
      code,
      status,
      retryable: status === 502 || status === 503 || status === 504,
    };
  }

  function normalizeStructuredPayload(payload, status) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
    if (payload.detail && typeof payload.detail === "object") {
      const detail = payload.detail;
      return {
        ...payload,
        ...detail,
        detail: detail.message || "הבקשה נעצרה עקב תקלה זמנית.",
        status,
      };
    }
    return payload;
  }

  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    const safeResponse = new Proxy(response, {
      get(target, property) {
        if (property !== "json") {
          const value = Reflect.get(target, property, target);
          return typeof value === "function" ? value.bind(target) : value;
        }

        return async () => {
          let text;
          try {
            text = await target.clone().text();
          } catch (_error) {
            return normalizedErrorPayload(
              "לא ניתן היה לקרוא את תשובת השרת.",
              "response_read_failed",
              target.status,
            );
          }

          if (!text.trim()) {
            return target.ok
              ? {}
              : normalizedErrorPayload(
                  "השרת החזיר תשובה ריקה. ניתן לנסות שוב.",
                  "empty_response",
                  target.status,
                );
          }

          try {
            return normalizeStructuredPayload(JSON.parse(text), target.status);
          } catch (_error) {
            return normalizedErrorPayload(
              "השרת החזיר תשובה שאינה תקינה. ניתן לנסות שוב מהמקטע האחרון שהושלם.",
              "invalid_response",
              target.status,
            );
          }
        };
      },
    });

    return safeResponse;
  };
})();
