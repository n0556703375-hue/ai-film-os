const APPROVAL_STATUS_LABELS = {
  "מתוכנן": "מתוכנן",
  "פרומפט מוכן": "פרומפט מוכן",
  "תמונת טיוטה": "תמונת טיוטה",
  "תמונה מאושרת": "תמונה מאושרת",
  "וידאו טיוטה": "וידאו טיוטה",
  "וידאו מאושר": "וידאו מאושר",
  "סופי": "סופי",
};

async function appendShotApprovalPanel(shotId) {
  const root = document.getElementById("modalContent");
  if (!root || !document.getElementById("wsTitle")) return;
  const pipeline = await api(`/api/shots/${shotId}/pipeline`);
  const panel = document.createElement("div");
  panel.className = "workspace-section";
  panel.style.marginTop = "15px";
  panel.innerHTML = `
    <div class="section-toolbar">
      <div><h3>מסלול אישור</h3><div class="meta">סטטוס נוכחי: ${esc(APPROVAL_STATUS_LABELS[pipeline.status] || pipeline.status)}</div></div>
      <button onclick="finalizeShot(${shotId})" ${pipeline.status === "סופי" ? "disabled" : ""}>אישור שוט סופי</button>
    </div>
    <div class="pipeline">
      ${["מתוכנן","פרומפט מוכן","תמונת טיוטה","תמונה מאושרת","וידאו טיוטה","וידאו מאושר","סופי"].map((status) =>
        `<div class="pipeline-step ${status === pipeline.status ? "approved" : ""}"><span>${status}</span></div>`
      ).join("")}
    </div>
    <h4>אישור תוצאות</h4>
    ${pipeline.media_results.length ? pipeline.media_results.map((media) => `
      <div class="history-item">
        <b>${media.media_type === "image" ? "תמונה" : "וידאו"} v${media.version}</b>
        · ${esc(media.status)} · ${esc(media.provider || "ללא ספק")}
        <div class="row">
          <a href="${esc(media.url)}" target="_blank" rel="noopener">פתיחת תוצאה</a>
          <button onclick="decideMedia(${shotId},${media.id},'approve')" ${media.status === "מאושר" ? "disabled" : ""}>אישור</button>
          <button class="danger" onclick="decideMedia(${shotId},${media.id},'reject')" ${media.status === "נדחה" ? "disabled" : ""}>דחייה</button>
        </div>
      </div>`).join("") : "<p>טרם קיימות תוצאות תמונה או וידאו.</p>"}
    <h4>היסטוריית החלטות</h4>
    ${pipeline.approval_events.length ? pipeline.approval_events.map((event) => `
      <div class="history-item"><b>${esc(event.event_type)}</b> · ${esc(event.from_status)} → ${esc(event.to_status)}
      <div class="meta">${esc(event.created_at)}${event.notes ? ` · ${esc(event.notes)}` : ""}</div></div>`).join("") : "<p>טרם נשמרו החלטות.</p>"}
  `;
  root.appendChild(panel);
}

async function decideMedia(shotId, mediaId, decision) {
  const notes = prompt(decision === "approve" ? "הערת אישור (רשות)" : "סיבת הדחייה", "");
  if (notes === null) return;
  try {
    await api(`/api/shots/${shotId}/media/${mediaId}/decision`, {
      method: "POST",
      body: JSON.stringify({decision, notes}),
    });
    await openShot(shotId);
  } catch (error) {
    showError(error);
  }
}

async function finalizeShot(shotId) {
  if (!confirm("לאשר את השוט כסופי? נדרשות תמונה מאושרת, וידאו מאושר וללא בעיית רציפות קריטית פתוחה.")) return;
  try {
    await api(`/api/shots/${shotId}/finalize`, {
      method: "POST",
      body: JSON.stringify({notes: "אושר מתוך Shot Workspace"}),
    });
    await openShot(shotId);
  } catch (error) {
    showError(error);
  }
}

const baseOpenShotForApproval = window.openShot;
window.openShot = async function openShotWithApproval(id) {
  await baseOpenShotForApproval(id);
  try {
    await appendShotApprovalPanel(id);
  } catch (error) {
    console.error("Approval panel failed", error);
  }
};
