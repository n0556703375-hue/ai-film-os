function productionBrainCard(item, kind) {
  const target = item.shot_id ? `שוט ${item.shot_id}` : item.asset_id ? `נכס ${item.asset_id}` : "פרויקט";
  const title = kind === "blocker" ? "חסם" : "פעולה מומלצת";
  const message = item.message || (item.type === "generate_shot_image" ? "השוט מוכן ליצירת תמונה." : item.type);
  return `<div class="card">
    <div class="meta">${title} · ${esc(target)}</div>
    <div class="title">${esc(message)}</div>
    <div class="meta">${esc(item.type)}</div>
    ${item.requires_confirmation ? '<span class="badge">דורש אישור</span>' : ''}
  </div>`;
}

async function loadProductionBrain() {
  if (!currentProjectId) return;
  const data = await api(`/api/projects/${currentProjectId}/production-brain`);
  const decision = data.decision || {};
  const snapshot = data.snapshot || {};
  const blockers = decision.blockers || [];
  const actions = decision.ready_actions || [];
  const projectStatus = decision.project_status === "blocked" ? "חסום" : "מוכן";

  $("production-brain").innerHTML = `
    <div class="section-toolbar">
      <div>
        <h2>מנהל ההפקה</h2>
        <div class="meta">תמונת מצב והמלצות read-only לפרויקט הפעיל</div>
      </div>
      <button class="secondary" onclick="loadProductionBrain().catch(showError)">רענון</button>
    </div>
    <div class="grid">
      <div class="card"><div class="meta">מצב הפרויקט</div><div class="stat">${projectStatus}</div></div>
      <div class="card"><div class="meta">חסמים</div><div class="stat">${blockers.length}</div></div>
      <div class="card"><div class="meta">פעולות מוכנות</div><div class="stat">${actions.length}</div></div>
      <div class="card"><div class="meta">סצנות / שוטים</div><div class="stat">${(snapshot.scenes || []).length}/${(snapshot.shots || []).length}</div></div>
    </div>
    <div class="workspace-grid" style="margin-top:18px">
      <div class="workspace-section">
        <h3>מה חסום</h3>
        ${blockers.length ? blockers.map((item) => productionBrainCard(item, "blocker")).join("") : "<p>אין חסמים פעילים.</p>"}
      </div>
      <div class="workspace-section">
        <h3>מה לעשות עכשיו</h3>
        ${actions.length ? actions.map((item) => productionBrainCard(item, "action")).join("") : "<p>אין פעולות מוכנות כרגע.</p>"}
      </div>
    </div>`;
}
