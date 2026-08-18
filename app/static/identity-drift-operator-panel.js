// Read-only presentation helpers for completed Identity Drift assessments.
(function (root) {
  const PRIORITY = { blocked: 0, error: 1, passed: 2 };

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  }

  function completedAt(item) {
    const value = item && item.identity_drift && item.identity_drift.completed_at;
    const timestamp = Date.parse(value || "");
    return Number.isFinite(timestamp) ? timestamp : 0;
  }

  function orderCompletedAssessments(items) {
    return [...(Array.isArray(items) ? items : [])].sort((left, right) => {
      const leftStatus = left && left.identity_drift ? left.identity_drift.status : "";
      const rightStatus = right && right.identity_drift ? right.identity_drift.status : "";
      const priorityDifference = (PRIORITY[leftStatus] ?? 3) - (PRIORITY[rightStatus] ?? 3);
      return priorityDifference || completedAt(right) - completedAt(left);
    });
  }

  function formatScore(score) {
    const value = Number(score);
    return Number.isFinite(value) ? `${Math.round(value * 100)}%` : "—";
  }

  function mediaTypeLabel(mediaType) {
    if (mediaType === "video") return "וידאו";
    if (mediaType === "image") return "תמונה";
    return "";
  }

  function renderIdentityDriftOperatorPanel(payload) {
    const items = orderCompletedAssessments(payload && payload.items);
    if (!items.length) {
      return `<section class="workspace-section" data-identity-drift-panel>
        <h3>בדיקות זהות שהושלמו</h3>
        <p class="meta">עדיין אין בדיקות שהושלמו.</p>
      </section>`;
    }

    return `<section class="workspace-section" data-identity-drift-panel>
      <div class="section-toolbar">
        <div><h3>בדיקות זהות שהושלמו</h3><div class="meta">חסימות ושגיאות מוצגות ראשונות</div></div>
        <span class="badge">${items.length}</span>
      </div>
      <div class="grid">${items.map((item) => {
        const assessment = item.identity_drift || {};
        const reasons = Array.isArray(assessment.reasons) ? assessment.reasons : [];
        const mediaLabel = mediaTypeLabel(item.media_type);
        return `<article class="card" data-identity-status="${escapeHtml(assessment.status)}" data-shot-id="${escapeHtml(item.shot_id)}" data-media-type="${escapeHtml(item.media_type || "")}">
          <span class="badge">${escapeHtml(assessment.status || "unknown")}</span>
          ${mediaLabel ? `<span class="badge">${mediaLabel}</span>` : ""}
          <div class="title">שוט ${escapeHtml(item.shot_id)}</div>
          <div class="meta">ציון: ${formatScore(assessment.score)} · ניסיון ${escapeHtml(assessment.attempt || 1)}</div>
          ${assessment.worker_id ? `<div class="meta">עובד: ${escapeHtml(assessment.worker_id)}</div>` : ""}
          ${assessment.completed_at ? `<div class="meta">הושלם: ${escapeHtml(assessment.completed_at)}</div>` : ""}
          ${reasons.length ? `<p>${reasons.map(escapeHtml).join(" · ")}</p>` : ""}
        </article>`;
      }).join("")}</div>
    </section>`;
  }

  const api = { escapeHtml, formatScore, mediaTypeLabel, orderCompletedAssessments, renderIdentityDriftOperatorPanel };
  if (root) root.identityDriftOperatorPanel = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
