const openSceneBeforeAssembly = window.openScene;

window.openScene = async function openSceneWithAssembly(sceneId) {
  await openSceneBeforeAssembly(sceneId);
  addSceneAssemblyAction(sceneId);
};

function addSceneAssemblyAction(sceneId) {
  const content = $("modalContent");
  if (!content || content.querySelector("[data-scene-assembly-button]")) return;

  const sceneHeading = content.querySelector("h2");
  if (!sceneHeading) return;

  const button = document.createElement("button");
  button.className = "secondary";
  button.dataset.sceneAssemblyButton = "true";
  button.textContent = "תצוגת הרכבת סצנה";
  button.onclick = () => openSceneAssembly(sceneId);
  sceneHeading.insertAdjacentElement("afterend", button);
}

async function openSceneAssembly(sceneId) {
  show("<h2>טוען הרכבת סצנה…</h2>");
  try {
    const manifest = await api(`/api/scenes/${sceneId}/preview-manifest`);
    renderSceneAssembly(manifest);
  } catch (error) {
    showError(error);
  }
}

function renderSceneAssembly(manifest) {
  const missing = new Set((manifest.missing_video_shot_ids || []).map(Number));
  show(`<div class="section-toolbar">
      <div>
        <div class="meta">סצנה ${esc(manifest.scene_number || "—")}</div>
        <h2>הרכבת סצנה — ${esc(manifest.title || "ללא שם")}</h2>
        <div class="meta">${Number(manifest.shot_count || 0)} שוטים · ${formatSceneDuration(manifest.duration_seconds)}</div>
      </div>
      <span class="badge">${manifest.ready_for_preview ? "מוכן לתצוגה" : "לא מוכן לתצוגה"}</span>
    </div>
    ${manifest.ready_for_preview ? "" : `<div class="card issue-high"><b>חסרים חומרים מאושרים</b><p>${missing.size} שוטים ללא וידאו מאושר או עם משך חסר.</p></div>`}
    <div class="workspace-section" data-scene-assembly-timeline>
      <h3>ציר זמן</h3>
      ${(manifest.timeline || []).length
        ? manifest.timeline.map((item) => renderAssemblyShot(item, missing.has(Number(item.shot_id)))).join("")
        : "<p>אין שוטים בסצנה.</p>"}
    </div>
    <div class="row">
      <button class="secondary" onclick="openScene(${Number(manifest.scene_id)})">חזרה לסצנה</button>
    </div>`);
}

function renderAssemblyShot(item, missingVideo) {
  const media = item.video_url
    ? `<video src="${esc(item.video_url)}" controls preload="metadata" style="width:100%;max-height:260px;border-radius:12px"></video>`
    : item.image_url
      ? `<img src="${esc(item.image_url)}" alt="שוט ${esc(item.shot_number)}" style="width:100%;max-height:260px;object-fit:cover;border-radius:12px">`
      : `<div class="meta">אין מדיה מאושרת להצגה</div>`;
  return `<div class="history-item ${missingVideo ? "issue-high" : ""}" data-shot-id="${Number(item.shot_id)}">
      <div class="section-toolbar">
        <div><b>שוט ${esc(item.shot_number)} — ${esc(item.title)}</b><div class="meta">${formatSceneDuration(item.duration_seconds)} · ${esc(item.status || "ללא סטטוס")}</div></div>
        <button class="secondary" onclick="openShot(${Number(item.shot_id)})">פתיחת שוט</button>
      </div>
      ${media}
      ${item.has_dialogue ? `<p><b>דיאלוג:</b> ${esc(item.dialogue)}</p>` : ""}
      ${item.has_audio_notes ? `<p><b>אודיו:</b> ${esc(item.audio_notes)}</p>` : ""}
      ${missingVideo ? `<p class="meta">נדרש וידאו מאושר לפני תצוגת הסצנה.</p>` : ""}
    </div>`;
}

function formatSceneDuration(value) {
  const seconds = Math.max(0, Number(value || 0));
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round((seconds - minutes * 60) * 10) / 10;
  return minutes ? `${minutes}:${String(remainder).padStart(4, "0")} דק׳` : `${remainder} שנ׳`;
}
