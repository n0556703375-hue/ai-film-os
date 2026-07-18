const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;",
    '"': "&quot;", "'": "&#39;"
  })[char]);

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "שגיאה");
  return data;
}

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".panel").forEach((panel) => panel.classList.remove("active"));
    const target = $(button.dataset.tab);
    if (!target) return;
    target.classList.add("active");
    const loader = loaders[button.dataset.tab];
    if (loader) loader().catch(showError);
  });
});

async function loadDashboard() {
  const data = await api("/api/dashboard");
  $("dashboard").innerHTML = `<div class="grid">
    <div class="card"><div class="meta">שוטים</div><div class="stat">${data.shots_total}</div></div>
    <div class="card"><div class="meta">סצנות</div><div class="stat">${data.scenes_total}</div></div>
    <div class="card"><div class="meta">נכסים</div><div class="stat">${data.assets_total}</div></div>
    <div class="card"><div class="meta">בעיות פתוחות</div><div class="stat">${data.open_issues}</div></div>
  </div>`;
}

async function loadScenes() {
  const scenes = await api("/api/scenes");
  $("scenes").innerHTML = `<div class="grid">${scenes.map((scene) => `
    <div class="card">
      <span class="badge">סצנה ${scene.scene_number}</span>
      <div class="title">${esc(scene.title)}</div>
      <div class="meta">${scene.shot_count} שוטים</div>
      <p>${esc(scene.story_goal || "מטרת הסצנה טרם הוגדרה")}</p>
      <button onclick="openScene(${scene.id})">פתיחת Scene Workspace</button>
    </div>`).join("")}</div>`;
}

async function openScene(id) {
  const scene = await api(`/api/scenes/${id}`);
  show(`
    <div class="meta">סצנה ${scene.scene_number}</div>
    <h2>${esc(scene.title)}</h2>
    <div class="workspace-grid">
      <div class="workspace-section">
        <h3>Scene Bible</h3>
        <label>שם הסצנה</label>
        <input id="scTitle" value="${esc(scene.title)}">
        <label>מטרה עלילתית</label>
        <textarea id="scGoal">${esc(scene.story_goal)}</textarea>
        <label>רגש מרכזי</label>
        <textarea id="scEmotion">${esc(scene.emotion)}</textarea>
        <label>קונפליקט</label>
        <textarea id="scConflict">${esc(scene.conflict)}</textarea>
        <label>מצב בתחילת הסצנה</label>
        <textarea id="scBeginning">${esc(scene.beginning)}</textarea>
        <label>מצב בסיום הסצנה</label>
        <textarea id="scEnding">${esc(scene.ending)}</textarea>
        <label>הערות</label>
        <textarea id="scNotes">${esc(scene.notes)}</textarea>
        <button onclick="saveScene(${scene.id})">שמירת הסצנה</button>
      </div>
      <div class="workspace-section">
        <h3>שוטים בסצנה</h3>
        ${scene.shots.map((shot)=>`
          <div class="card">
            <div class="meta">שוט ${shot.shot_number} · ${shot.asset_count} נכסים</div>
            <div class="title">${esc(shot.title)}</div>
            <span class="badge">${esc(shot.status)}</span>
            <button onclick="openShot(${shot.id})">פתיחת Shot Workspace</button>
          </div>`).join("")}
      </div>
    </div>
  `);
}

async function saveScene(id) {
  const payload = {
    title: $("scTitle").value,
    story_goal: $("scGoal").value,
    emotion: $("scEmotion").value,
    conflict: $("scConflict").value,
    beginning: $("scBeginning").value,
    ending: $("scEnding").value,
    notes: $("scNotes").value,
  };
  await api(`/api/scenes/${id}`, {method:"PATCH", body:JSON.stringify(payload)});
  alert("הסצנה נשמרה.");
  await openScene(id);
}

async function loadShots() {
  const shots = await api("/api/shots");
  $("shots").innerHTML = `<div class="grid">${shots.map((shot) => `
    <div class="card">
      <div class="meta">שוט ${shot.shot_number} · סצנה ${shot.scene_number || "-"} · ${shot.asset_count} נכסים</div>
      <div class="title">${esc(shot.title)}</div>
      <span class="badge">${esc(shot.status)}</span>
      <div class="row">
        <button onclick="openShot(${shot.id})">פתיחת Workspace</button>
        <button class="secondary" onclick="checkContinuity(${shot.id})">בדיקת רציפות</button>
      </div>
    </div>`).join("")}</div>`;
}

async function openShot(id) {
  const [shot, assets] = await Promise.all([
    api(`/api/shots/${id}`),
    api("/api/assets")
  ]);
  const selected = new Set(shot.assets.map((a) => a.id));

  show(`
    <div class="meta">סצנה ${shot.scene_number || "-"} · שוט ${shot.shot_number}</div>
    <h2>${esc(shot.title)}</h2>
    <div class="workspace-grid">
      <div>
        <div class="workspace-section">
          <h3>הגדרות שוט</h3>
          <label>סטטוס</label>
          <select id="wsStatus">
            ${["מתוכנן","רפרנס","פרומפט מוכן","תמונה מאושרת","וידאו מוכן","וידאו מאושר","אודיו","QA","סופי"]
              .map((s)=>`<option ${s===shot.status?"selected":""}>${s}</option>`).join("")}
          </select>
          <label>הערות / פעולה</label>
          <textarea id="wsNotes">${esc(shot.notes)}</textarea>
          <label>מצלמה וקומפוזיציה</label>
          <textarea id="wsCamera">${esc(shot.camera)}</textarea>
          <label>עדשה</label>
          <input id="wsLens" value="${esc(shot.lens)}">
          <label>תאורה</label>
          <textarea id="wsLighting">${esc(shot.lighting)}</textarea>
          <label>תנועת מצלמה</label>
          <textarea id="wsMovement">${esc(shot.movement)}</textarea>
          <label>מצב רוח</label>
          <textarea id="wsMood">${esc(shot.mood)}</textarea>
          <label>דיאלוג</label>
          <textarea id="wsDialogue">${esc(shot.dialogue)}</textarea>
          <div class="row">
            <button onclick="saveWorkspace(${shot.id})">שמירת שוט</button>
            <button class="secondary" onclick="runDirector(${shot.id})">Run Director</button>
          </div>
        </div>
      </div>
      <div>
        <div class="workspace-section">
          <h3>נכסים משויכים</h3>
          <div class="asset-checks">
            ${assets.map((a)=>`
              <label class="asset-check">
                <input type="checkbox" class="wsAsset" value="${a.id}" ${selected.has(a.id)?"checked":""}>
                <span>${esc(a.asset_type)} — ${esc(a.name)} ${a.approved?"✓":""}</span>
              </label>`).join("")}
          </div>
          <button onclick="saveShotAssets(${shot.id})">שמירת שיוך נכסים</button>
        </div>
        <div class="workspace-section" style="margin-top:15px">
          <h3>פרומפט נוכחי</h3>
          <pre>${esc(shot.prompt || "טרם נוצר פרומפט")}</pre>
          <button onclick="makePrompt(${shot.id})">בניית פרומפט</button>
        </div>
        <div class="workspace-section" style="margin-top:15px">
          <h3>היסטוריית פרומפטים</h3>
          ${shot.prompt_versions.length
            ? shot.prompt_versions.map((v)=>`<div class="history-item"><b>גרסה ${v.version}</b><div class="meta">${esc(v.created_at)}</div></div>`).join("")
            : "<p>אין עדיין גרסאות.</p>"}
        </div>
      </div>
    </div>
  `);
}

async function saveWorkspace(id) {
  const payload = {
    status: $("wsStatus").value,
    notes: $("wsNotes").value,
    camera: $("wsCamera").value,
    lens: $("wsLens").value,
    lighting: $("wsLighting").value,
    movement: $("wsMovement").value,
    mood: $("wsMood").value,
    dialogue: $("wsDialogue").value,
  };
  await api(`/api/shots/${id}`, {method:"PATCH", body:JSON.stringify(payload)});
  alert("השוט נשמר.");
  await openShot(id);
}

async function saveShotAssets(id) {
  const asset_ids = [...document.querySelectorAll(".wsAsset:checked")].map((x)=>Number(x.value));
  await api(`/api/shots/${id}/assets`, {method:"PUT", body:JSON.stringify({asset_ids})});
  alert("שיוך הנכסים נשמר.");
  await openShot(id);
}

async function makePrompt(id) {
  const data = await api(`/api/shots/${id}/prompt`, {method:"POST"});
  show(`<h2>פרומפט</h2><pre>${esc(data.prompt)}</pre><button onclick="openShot(${id})">חזרה לשוט</button>`);
}

async function runDirector(id) {
  const data = await api(`/api/shots/${id}/director`, {method:"POST"});
  show(`<h2>Run Director</h2>
    <p><b>מוכן:</b> ${data.ready ? "כן" : "לא"}</p>
    <p><b>הפעולה הבאה:</b> ${esc(data.next_action)}</p>
    <h3>בעיות</h3>
    ${data.issues.length ? data.issues.map((i)=>`
      <div class="card issue-${esc(i.severity)}">
        <b>${esc(i.severity)}</b><p>${esc(i.message)}</p>
      </div>`).join("") : "<p>לא נמצאו בעיות.</p>"}
    ${data.prompt ? `<h3>פרומפט</h3><pre>${esc(data.prompt)}</pre>` : ""}
    <button onclick="openShot(${id})">חזרה לשוט</button>`);
}

async function checkContinuity(id) {
  const data = await api(`/api/shots/${id}/continuity`, {method:"POST"});
  show(`<h2>בדיקת רציפות</h2>
    ${data.issues.length ? data.issues.map((issue) => `
      <div class="card issue-${esc(issue.severity)}">
        <b>${esc(issue.severity)}</b><p>${esc(issue.message)}</p>
      </div>`).join("") : "<p>לא נמצאו בעיות.</p>"}`);
}

async function loadAssets() {
  const assets = await api("/api/assets");
  $("assets").innerHTML = `
    <div class="asset-toolbar">
      <button onclick="newAsset()">נכס חדש</button>
      ${["הכול","דמות","לוקיישן","אביזר","לבוש","כלל","סגנון"]
        .map((t)=>`<button class="secondary" onclick="filterAssets('${t}')">${t}</button>`).join("")}
    </div>
    <div id="assetGrid" class="grid">
      ${assets.map(assetCard).join("")}
    </div>`;
  window.currentAssets = assets;
}

function assetCard(asset) {
  return `<div class="card" data-type="${esc(asset.asset_type)}">
    <span class="badge ${asset.approved?"approved":""}">
      ${esc(asset.asset_type)}${asset.approved?" · מאושר":""}
    </span>
    <div class="title">${esc(asset.name)}</div>
    <p>${esc(asset.description)}</p>
    <div class="meta">${esc(asset.visual_rules)}</div>
    <button onclick="openAsset(${asset.id})">פתיחת Story Bible</button>
  </div>`;
}

function filterAssets(type) {
  document.querySelectorAll("#assetGrid .card").forEach((card)=>{
    card.style.display = type==="הכול" || card.dataset.type===type ? "" : "none";
  });
}

function newAsset() {
  show(`<h2>נכס חדש</h2>
    <label>סוג</label>
    <select id="asType">
      ${["דמות","לוקיישן","אביזר","לבוש","כלל","סגנון"].map((t)=>`<option>${t}</option>`).join("")}
    </select>
    <label>שם</label><input id="asName">
    <label>תיאור</label><textarea id="asDescription"></textarea>
    <label>כללים חזותיים ורציפות</label><textarea id="asRules"></textarea>
    <label>Master Prompt</label><textarea id="asMaster"></textarea>
    <label>Negative Prompt</label><textarea id="asNegative"></textarea>
    <label>קישור לרפרנס</label><input id="asUrl">
    <button onclick="createAsset()">יצירת נכס</button>`);
}

async function createAsset() {
  const payload = {
    asset_type:$("asType").value,
    name:$("asName").value,
    description:$("asDescription").value,
    visual_rules:$("asRules").value,
    master_prompt:$("asMaster").value,
    negative_prompt:$("asNegative").value,
    reference_url:$("asUrl").value,
    approved:false
  };
  const asset = await api("/api/assets", {method:"POST", body:JSON.stringify(payload)});
  await openAsset(asset.id);
}

async function openAsset(id) {
  const asset = await api(`/api/assets/${id}`);
  show(`<div class="meta">${esc(asset.asset_type)} · גרסה ${asset.version}</div>
    <h2>${esc(asset.name)}</h2>
    <div class="workspace-grid">
      <div class="workspace-section">
        <label>סוג</label>
        <select id="asType">
          ${["דמות","לוקיישן","אביזר","לבוש","כלל","סגנון"]
            .map((t)=>`<option ${t===asset.asset_type?"selected":""}>${t}</option>`).join("")}
        </select>
        <label>שם</label><input id="asName" value="${esc(asset.name)}">
        <label>תיאור</label><textarea id="asDescription">${esc(asset.description)}</textarea>
        <label>כללים חזותיים ורציפות</label><textarea id="asRules">${esc(asset.visual_rules)}</textarea>
        <label>Master Prompt</label><textarea id="asMaster">${esc(asset.master_prompt)}</textarea>
        <label>Negative Prompt</label><textarea id="asNegative">${esc(asset.negative_prompt)}</textarea>
        <label>קישור לרפרנס</label><input id="asUrl" value="${esc(asset.reference_url)}">
        <label class="asset-check">
          <input type="checkbox" id="asApproved" ${asset.approved?"checked":""}>
          <span>נכס מאושר</span>
        </label>
        <div class="row">
          <button onclick="saveAsset(${asset.id})">שמירה</button>
          <button class="danger" onclick="deleteAsset(${asset.id})">מחיקה</button>
        </div>
      </div>
      <div class="workspace-section">
        <h3>שוטים מקושרים</h3>
        ${asset.linked_shots.length
          ? asset.linked_shots.map((s)=>`
            <div class="card">
              <div class="title">שוט ${s.shot_number}: ${esc(s.title)}</div>
              <span class="badge">${esc(s.status)}</span>
              <button onclick="openShot(${s.id})">פתיחת השוט</button>
            </div>`).join("")
          : "<p>הנכס אינו משויך עדיין לשוטים.</p>"}
      </div>
    </div>`);
}

async function saveAsset(id) {
  const payload = {
    asset_type:$("asType").value,
    name:$("asName").value,
    description:$("asDescription").value,
    visual_rules:$("asRules").value,
    master_prompt:$("asMaster").value,
    negative_prompt:$("asNegative").value,
    reference_url:$("asUrl").value,
    approved:$("asApproved").checked
  };
  await api(`/api/assets/${id}`, {method:"PATCH", body:JSON.stringify(payload)});
  alert("הנכס נשמר.");
  await openAsset(id);
}

async function deleteAsset(id) {
  if (!confirm("למחוק את הנכס? השיוכים שלו לשוטים יוסרו.")) return;
  await api(`/api/assets/${id}`, {method:"DELETE"});
  closeModal();
  await loadAssets();
}

function show(html) {$("modalContent").innerHTML = html; $("modal").style.display = "flex";}
function closeModal() {$("modal").style.display = "none";}
function showError(error) {console.error(error); show(`<h2>שגיאה</h2><p>${esc(error.message)}</p>`);}

const loaders = {
  dashboard: loadDashboard,
  scenes: loadScenes,
  shots: loadShots,
  assets: loadAssets,
};

loadDashboard().catch(showError);
