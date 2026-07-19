const openShotBeforeContinuity = window.openShot;

window.openShot = async function openShotWithContinuity(shotId) {
  await openShotBeforeContinuity(shotId);
  await renderContinuityPanel(shotId);
};

async function renderContinuityPanel(shotId) {
  const content = $("modalContent");
  if (!content || content.querySelector("[data-continuity-panel]")) return;

  const [preview, openIssues] = await Promise.all([
    api(`/api/issues/shots/${shotId}/continuity-preview`),
    api("/api/issues?resolved=false"),
  ]);
  const persistedBlockers = openIssues.filter(
    (issue) => Number(issue.shot_id) === Number(shotId)
      && ["critical", "high"].includes(issue.severity)
      && !["נפתר", "אושר כחריגה"].includes(issue.status),
  );
  const previewBlockers = preview.issues.filter(
    (issue) => ["critical", "high"].includes(issue.severity),
  );

  const panel = document.createElement("div");
  panel.className = "workspace-section";
  panel.dataset.continuityPanel = "true";
  panel.style.marginTop = "15px";
  panel.innerHTML = `<div class="section-toolbar">
      <div><h3>Continuity Director</h3>
      <div class="meta">השוואה לשוט הקודם ולשוט הבא</div></div>
      <span class="badge">${persistedBlockers.length} חסימות פעילות</span>
    </div>
    ${persistedBlockers.length ? `
      <div class="card issue-high">
        <b>האישור הסופי חסום</b>
        <p>יש לפתור או לאשר כחריגה את הבעיות הבאות:</p>
        ${persistedBlockers.map(renderPersistedBlocker).join("")}
      </div>` : `<div class="card"><b>אין חסימות שמורות</b><p class="meta">לא נמצאו בעיות high או critical פתוחות שמונעות אישור סופי.</p></div>`}
    <h4>ממצאי השוואה מקדימה</h4>
    ${previewBlockers.length
      ? previewBlockers.map(renderPreviewBlocker).join("")
      : `<p class="meta">לא נמצאו הבדלים חמורים מול השוטים השכנים.</p>`}
    <div class="row">
      <button class="secondary" onclick="checkContinuity(${shotId})">בדיקת רציפות מלאה</button>
      <button class="secondary" onclick="loadQA(); closeModal()">פתיחת QA Center</button>
    </div>`;

  const workspaceGrid = content.querySelector(".workspace-grid");
  const targetColumn = workspaceGrid?.lastElementChild || content;
  targetColumn.appendChild(panel);
}

function renderPersistedBlocker(issue) {
  return `<div class="history-item">
    <b>${esc(issue.severity)}</b> · ${esc(issue.category || "continuity")}
    <p>${esc(issue.message)}</p>
  </div>`;
}

function renderPreviewBlocker(issue) {
  const neighborButton = issue.neighbor_shot_id
    ? `<button class="secondary" onclick="openShot(${Number(issue.neighbor_shot_id)})">פתיחת שוט ${esc(issue.neighbor_shot_number || "שכן")}</button>`
    : "";
  return `<div class="history-item issue-${esc(issue.severity)}">
    <b>${esc(issue.severity)}</b> · ${esc(issue.relation || "השוואה")}
    <p>${esc(issue.message)}</p>
    ${issue.expected || issue.observed ? `<div class="meta">צפוי: ${esc(issue.expected || "—")} · נמצא: ${esc(issue.observed || "—")}</div>` : ""}
    ${neighborButton}
  </div>`;
}
