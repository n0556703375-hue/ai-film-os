let shotFilterState = { status: "", scene: "", query: "" };

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

  $("shots").innerHTML = `<div class="section-toolbar">
      <div><h2>שוטים</h2><div class="meta">${filtered.length} מתוך ${shots.length} שוטים</div></div>
      <button onclick="newShot()">שוט חדש</button>
    </div>
    <div class="card" data-shot-filters>
      <div class="form-grid">
        <div><label>חיפוש</label><input id="shotFilterQuery" value="${esc(shotFilterState.query)}" placeholder="שם, מספר או סוג שוט" oninput="updateShotFilters()"></div>
        <div><label>סטטוס</label><select id="shotFilterStatus" onchange="updateShotFilters()"><option value="">כל הסטטוסים</option>${statuses.map((status) => `<option value="${esc(status)}" ${status === shotFilterState.status ? "selected" : ""}>${esc(status)}</option>`).join("")}</select></div>
        <div><label>סצנה</label><select id="shotFilterScene" onchange="updateShotFilters()"><option value="">כל הסצנות</option>${scenes.map((scene) => `<option value="${esc(scene)}" ${String(scene) === shotFilterState.scene ? "selected" : ""}>סצנה ${esc(scene)}</option>`).join("")}</select></div>
        <div><label>&nbsp;</label><button class="secondary" onclick="clearShotFilters()">ניקוי מסננים</button></div>
      </div>
    </div>
    <div class="grid">${filtered.length ? filtered.map(renderFilteredShotCard).join("") : `<div class="card"><b>לא נמצאו שוטים תואמים</b><p class="meta">שני את המסננים כדי להציג תוצאות נוספות.</p></div>`}</div>`;
};

function renderFilteredShotCard(shot) {
  return `<div class="card">
    <div class="meta">שוט ${shot.shot_number} · ${esc(shot.shot_type || "רגיל")} · סצנה ${shot.scene_number || "-"} · ${shot.asset_count} נכסים</div>
    <div class="title">${esc(shot.title)}</div>
    <span class="badge">${esc(shot.status)}</span>
    <div class="row">
      <button onclick="openShot(${Number(shot.id)})">פתיחת Workspace</button>
      <button class="secondary" onclick="checkContinuity(${Number(shot.id)})">בדיקת רציפות</button>
    </div>
  </div>`;
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
