let shotFilterState = { status: "", scene: "", query: "" };
let selectedShotIds = new Set();
let pendingBatchFinalizeIds = [];

window.loadShots = async function loadShotsWithFilters() {
  const shots = await api("/api/shots");
  const statuses = [...new Set(shots.map((shot) => shot.status).filter(Boolean))].sort();
  const scenes = [...new Set(shots.map((shot) => shot.scene_number).filter((value) => value !== null && value !== undefined))].sort((a, b) => Number(a) - Number(b));
  const filtered = shots.filter((shot) => {
    const matchesStatus = !shotFilterState.status || shot.status === shotFilterState.status;
    const matchesScene = !shotFilterState.scene || String(shot.scene_number || "") === shotFilterState.scene;
    const haystack = `${shot.title || ""} ${shot.shot_number || ""} ${shot.shot_type || ""}`.toLowerCase();
    const matchesQuery = !shotFilterState.query || haystack.includes(shotFilterState.query.toLowerCase());
    return matchesStatus && matchesScene && matchesQuery;
  });
  selectedShotIds = new Set([...selectedShotIds].filter((id) => shots.some((shot) => Number(shot.id) === id)));

  $("shots").innerHTML = `<div class="section-toolbar">
      <div><h2>שוטים</h2><div class="meta">${filtered.length} מתוך ${shots.length} שוטים · ${selectedShotIds.size} נבחרו</div></div>
      <button onclick="newShot()">שוט חדש</button>
    </div>
    <div class="card" data-shot-filters>
      <div class="form-grid">
        <div><label>חיפוש</label><input id="shotFilterQuery" value="${esc(shotFilterState.query)}" placeholder="שם, מספר או סוג שוט" oninput="updateShotFilters()"></div>
        <div><label>סטטוס</label><select id="shotFilterStatus" onchange="updateShotFilters()"><option value="">כל הסטטוסים</option>${statuses.map((status) => `<option value="${esc(status)}" ${status === shotFilterState.status ? "selected" : ""}>${esc(status)}</option>`).join("")}</select></div>
        <div><label>סצנה</label><select id="shotFilterScene" onchange="updateShotFilters()"><option value="">כל הסצנות</option>${scenes.map((scene) => `<option value="${esc(scene)}" ${String(scene) === shotFilterState.scene ? "selected" : ""}>סצנה ${esc(scene)}</option>`).join("")}</select></div>
        <div><label>&nbsp;</label><button class="secondary" onclick="clearShotFilters()">ניקוי מסננים</button></div>
      </div>
      <div class="row" data-shot-batch-actions>
        <button class="secondary" onclick="selectVisibleShots([${filtered.map((shot) => Number(shot.id)).join(",")}])">בחירת המוצגים</button>
        <button class="secondary" onclick="clearShotSelection()">ניקוי בחירה</button>
        <select id="batchShotStatus"><option value="מתוכנן">מתוכנן</option><option value="פרומפט מוכן">פרומפט מוכן</option></select>
        <button onclick="applyBatchShotStatus()" ${selectedShotIds.size ? "" : "disabled"}>עדכון ${selectedShotIds.size} שוטים</button>
        <button class="secondary" onclick="previewBatchFinalize()" ${selectedShotIds.size ? "" : "disabled"}>בדיקת סיום מרוכז</button>
      </div>
    </div>
    <div class="grid">${filtered.length ? filtered.map(renderFilteredShotCard).join("") : `<div class="card"><b>לא נמצאו שוטים תואמים</b><p class="meta">שני את המסננים כדי להציג תוצאות נוספות.</p></div>`}</div>`;
};

function renderFilteredShotCard(shot) {
  const id = Number(shot.id);
  return `<div class="card">
    <label class="row"><input type="checkbox" data-shot-select value="${id}" ${selectedShotIds.has(id) ? "checked" : ""} onchange="toggleShotSelection(${id}, this.checked)"> בחירת השוט</label>
    <div class="meta">שוט ${shot.shot_number} · ${esc(shot.shot_type || "רגיל")} · סצנה ${shot.scene_number || "-"} · ${shot.asset_count} נכסים</div>
    <div class="title">${esc(shot.title)}</div>
    <span class="badge">${esc(shot.status)}</span>
    <div class="row">
      <button onclick="openShot(${id})">פתיחת Workspace</button>
      <button class="secondary" onclick="checkContinuity(${id})">בדיקת רציפות</button>
    </div>
  </div>`;
}

function toggleShotSelection(id, checked) {
  if (checked) selectedShotIds.add(Number(id));
  else selectedShotIds.delete(Number(id));
  loadShots().catch(showError);
}

function selectVisibleShots(ids) {
  ids.forEach((id) => selectedShotIds.add(Number(id)));
  loadShots().catch(showError);
}

function clearShotSelection() {
  selectedShotIds.clear();
  pendingBatchFinalizeIds = [];
  loadShots().catch(showError);
}

async function applyBatchShotStatus() {
  if (!selectedShotIds.size) return alert("יש לבחור לפחות שוט אחד.");
  const status = $("batchShotStatus")?.value;
  if (!confirm(`לעדכן ${selectedShotIds.size} שוטים לסטטוס "${status}"?`)) return;
  await api("/api/shots/batch/status", {
    method: "PATCH",
    body: JSON.stringify({
      project_id: currentProjectId,
      shot_ids: [...selectedShotIds],
      status,
      confirmed: true,
    }),
  });
  selectedShotIds.clear();
  await loadShots();
}

async function previewBatchFinalize() {
  if (!selectedShotIds.size) return alert("יש לבחור לפחות שוט אחד.");
  pendingBatchFinalizeIds = [...selectedShotIds];
  const preview = await api("/api/shots/batch/finalize-preview", {
    method: "POST",
    body: JSON.stringify({ shot_ids: pendingBatchFinalizeIds }),
  });
  const actionable = preview.items.filter((item) => item.eligible && !item.already_final).length;
  const alreadyFinal = preview.items.filter((item) => item.already_final).length;
  const blocked = preview.items.filter((item) => !item.eligible);
  show(`<h2>בדיקת סיום מרוכז</h2>
    <div class="grid">
      <div class="card"><div class="meta">כשירים לסיום</div><div class="stat">${actionable}</div></div>
      <div class="card"><div class="meta">כבר סופיים</div><div class="stat">${alreadyFinal}</div></div>
      <div class="card"><div class="meta">חסומים</div><div class="stat">${blocked.length}</div></div>
    </div>
    ${blocked.length ? `<div class="workspace-section"><h3>שוטים חסומים</h3>${blocked.map((item) => `<div class="card"><b>שוט ${item.shot_id}</b><div class="meta">${item.reasons.map(esc).join(" · ")}</div></div>`).join("")}</div>` : ""}
    <label>הערה להיסטוריית האישור</label><textarea id="batchFinalizeNotes" maxlength="5000" placeholder="אופציונלי"></textarea>
    <button onclick="confirmBatchFinalize()" ${actionable ? "" : "disabled"}>סיום ${actionable} שוטים כשירים</button>
    <p class="meta">רק שוטים שעברו את בדיקות התמונה, הווידאו והרציפות יסומנו כסופיים.</p>`);
}

async function confirmBatchFinalize() {
  if (!pendingBatchFinalizeIds.length) return alert("אין בחירה פעילה לסיום.");
  if (!confirm("לסיים את כל השוטים הכשירים? הפעולה תירשם בהיסטוריית האישורים.")) return;
  const result = await api("/api/shots/batch/finalize", {
    method: "POST",
    body: JSON.stringify({
      shot_ids: pendingBatchFinalizeIds,
      notes: $("batchFinalizeNotes")?.value || "",
      confirmed: true,
    }),
  });
  pendingBatchFinalizeIds = [];
  selectedShotIds.clear();
  show(`<h2>הסיום המרוכז הושלם</h2>
    <div class="grid">
      <div class="card"><div class="meta">הושלמו</div><div class="stat">${result.finalized}</div></div>
      <div class="card"><div class="meta">חסומים</div><div class="stat">${result.blocked}</div></div>
      <div class="card"><div class="meta">כבר היו סופיים</div><div class="stat">${result.already_final}</div></div>
    </div>
    <button onclick="closeModal(); loadShots().catch(showError)">חזרה לשוטים</button>`);
}

function updateShotFilters() {
  shotFilterState = {
    query: $("shotFilterQuery")?.value || "",
    status: $("shotFilterStatus")?.value || "",
    scene: $("shotFilterScene")?.value || "",
  };
  loadShots().catch(showError);
}

function clearShotFilters() {
  shotFilterState = { status: "", scene: "", query: "" };
  loadShots().catch(showError);
}
