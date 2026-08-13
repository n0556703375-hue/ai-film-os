const loadDashboardBeforeCosts = window.loadDashboard;

window.loadDashboard = async function loadDashboardWithCosts() {
  await loadDashboardBeforeCosts();
  await renderProjectCostSummary();
};

async function renderProjectCostSummary() {
  const dashboard = $("dashboard");
  if (!dashboard || !currentProjectId || dashboard.querySelector("[data-cost-summary]")) return;

  const [summary, jobs] = await Promise.all([
    api(`/api/jobs/cost-summary?project_id=${currentProjectId}`),
    api(`/api/jobs?project_id=${currentProjectId}`),
  ]);

  const completed = jobs.filter((job) => job.status === "completed").length;
  const active = jobs.filter((job) => ["queued", "running", "retrying"].includes(job.status)).length;
  const failed = jobs.filter((job) => job.status === "failed").length;
  const variance = Number(summary.actual_cost_usd || 0) - Number(summary.estimated_cost_usd || 0);

  const section = document.createElement("div");
  section.dataset.costSummary = "true";
  section.className = "workspace-section";
  section.style.marginTop = "18px";
  section.innerHTML = `
    <div class="section-toolbar">
      <div>
        <h3>עלות וקרדיטים</h3>
        <div class="meta">מעקב קריאה בלבד אחר משימות המדיה של ההפקה</div>
      </div>
      <span class="badge">${Number(summary.job_count || 0)} משימות</span>
    </div>
    <div class="grid">
      <div class="card"><div class="meta">עלות משוערת (משימות שנוצרו)</div><div class="stat">${formatUsd(summary.estimated_cost_usd)}</div></div>
      <div class="card"><div class="meta">עלות בפועל</div><div class="stat">${formatUsd(summary.actual_cost_usd)}</div></div>
      <div class="card"><div class="meta">פער</div><div class="stat">${formatSignedUsd(variance)}</div></div>
      <div class="card"><div class="meta">פעילות</div><div class="stat">${active}</div><div class="meta">${completed} הושלמו · ${failed} נכשלו</div></div>
    </div>
    ${renderProjectedCost(summary)}
    ${renderRecentCostJobs(jobs.slice(0, 5))}`;
  dashboard.appendChild(section);
}

function renderProjectedCost(summary) {
  const shotCount = Number(summary.shot_count || 0);
  if (!shotCount) return "";
  const perShot = Number(summary.projected_shot_cost_usd || 0);
  if (!perShot) {
    return `<p class="meta">אין ספק וידאו מוגדר כרגע, כך שלא ניתן להעריך עלות לפרויקט.</p>`;
  }
  return `
    <div class="card" style="margin-top:14px">
      <div class="meta">תחזית עלות לכל הפרויקט (${shotCount} שוטים × ${formatUsd(perShot)} לשוט, בהנחת 5 שניות וידאו לשוט)</div>
      <div class="stat">${formatUsd(summary.projected_total_cost_usd)}</div>
      <div class="meta">הערכה גסה בלבד לפי מחיר ספק הווידאו הנוכחי — אינה כוללת עלויות תמונה, ואינה מחליפה את "עלות משוערת" שמעל, שמשקפת משימות שכבר נוצרו בפועל.</div>
    </div>`;
}

function renderRecentCostJobs(jobs) {
  if (!jobs.length) return `<p class="meta">טרם נרשמו משימות מדיה לפרויקט.</p>`;
  return `<h4>משימות אחרונות</h4>${jobs.map((job) => `
    <div class="history-item">
      <b>${job.job_type === "video" ? "וידאו" : "תמונה"}</b> · ${esc(job.status)}
      <div class="meta">שוט ${Number(job.shot_id)} · משוער ${formatUsd(job.estimated_cost_usd)} · בפועל ${formatUsd(job.actual_cost_usd)}</div>
    </div>`).join("")}`;
}

function formatUsd(value) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(amount);
}

function formatSignedUsd(value) {
  const amount = Number(value || 0);
  const prefix = amount > 0 ? "+" : "";
  return `${prefix}${formatUsd(amount)}`;
}
