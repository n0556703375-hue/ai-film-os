// Compact, presentation-only project progress helpers.
// This module never mutates project data and accepts only API summary fields.

function normalizedCount(value) {
  const count = Number(value);
  return Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
}

function formatProjectProgressSummary(project = {}) {
  const scenes = normalizedCount(project.scenes_total);
  const shots = normalizedCount(project.shots_total);
  const assets = normalizedCount(project.assets_total);
  const statusTotals = project.shot_status_totals && typeof project.shot_status_totals === "object"
    ? project.shot_status_totals
    : {};

  const statuses = Object.entries(statusTotals)
    .map(([status, total]) => [String(status || "not_started"), normalizedCount(total)])
    .filter(([, total]) => total > 0)
    .sort(([left], [right]) => left.localeCompare(right, "he"))
    .map(([status, total]) => `${status}: ${total}`);

  const totals = `${scenes} סצנות · ${shots} שוטים · ${assets} נכסים`;
  return statuses.length ? `${totals} · ${statuses.join(" · ")}` : totals;
}

if (typeof window !== "undefined") {
  window.formatProjectProgressSummary = formatProjectProgressSummary;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { formatProjectProgressSummary, normalizedCount };
}
