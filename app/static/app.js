const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;",
    '"': "&quot;", "'": "&#39;"
  })[char]);

let currentProjectId = Number(localStorage.getItem("filmOsProjectId")) || null;
const PROJECT_SCOPED_BASES = ["/api/scenes", "/api/shots", "/api/assets", "/api/issues", "/api/dashboard"];

function withProject(url) {
  if (!currentProjectId) return url;
  const scoped = PROJECT_SCOPED_BASES.some(
    (base) => url === base || url.startsWith(base + "?") || url.startsWith(base + "/")
  );
  if (!scoped) return url;
  return `${url}${url.includes("?") ? "&" : "?"}project_id=${currentProjectId}`;
}

async function api(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const finalUrl = method === "GET" ? withProject(url) : url;
  const response = await fetch(finalUrl, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "שגיאה");
  return data;
}

async function loadProjects() {
  const projects = await api("/api/projects");
  if (!projects.length) return;
  if (!currentProjectId || !projects.some((p) => p.id === currentProjectId)) {
    currentProjectId = projects[0].id;
    localStorage.setItem("filmOsProjectId", currentProjectId);
  }
  $("projectSelect").innerHTML = projects
    .map((p) => `<option value="${p.id}" ${p.id === currentProjectId ? "selected" : ""}>${esc(p.name)}</option>`)
    .join("");
}

async function switchProject(id) {
  currentProjectId = Number(id);
  localStorage.setItem("filmOsProjectId", currentProjectId);
  const loader = loaders[currentTab];
  if (loader) await loader().catch(showError);
}

function newProject() {
  show(`<h2>הפקה חדשה</h2><div class="form-grid">
    <div class="wide"><label>שם ההפקה</label><input id="npName"></div>
    <div class="wide"><label>תיאור</label><textarea id="npDescription"></textarea></div>
    <div class="wide"><label>סגנון חזותי</label><textarea id="npStyle"></textarea></div>
    <div class="wide"><label>כללים</label><textarea id="npRules"></textarea></div>
  </div><button onclick="createProject()">יצירת הפקה</button>`);
}

async function createProject() {
  const project = await api("/api/projects", {method:"POST", body:JSON.stringify({
    name:$("npName").value, description:$("npDescription").value,
    visual_style:$("npStyle").value, rules:$("npRules").value
  })});
  currentProjectId = project.id;
  localStorage.setItem("filmOsProjectId", currentProjectId);
  closeModal();
  await loadProjects();
  await loadDashboard();
}

let currentTab = "dashboard";

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".panel").forEach((panel) => panel.classList.remove("active"));
    const target = $(button.dataset.tab);
    if (!target) return;
    target.classList.add("active");
    currentTab = button.dataset.tab;
    const loader = loaders[button.dataset.tab];
    if (loader) loader().catch(showError);
  });
});

async function loadDashboard() {
  const data = await api("/api/dashboard");
  $("dashboard").innerHTML = `
    <div class="grid">
      <div class="card"><div class="meta">שוטים</div><div class="stat">${data.shots_total}</div></div>
      <div class="card"><div class="meta">סצנות</div><div class="stat">${data.scenes_total}</div></div>
      <div class="card"><div class="meta">נכסים מאושרים</div><div class="stat">${data.approved_assets}/${data.assets_total}</div></div>
      <div class="card"><div class="meta">בעיות פתוחות</div><div class="stat">${data.open_issues}</div></div>
      <div class="card"><div class="meta">בעיות חמורות</div><div class="stat">${data.critical_issues}</div></div>
    </div>
    <div class="card" style="margin-top:18px">
      <h3>התקדמות כוללת</h3>
      <div class="progress-shell"><div class="progress-bar" style="width:${data.project_progress}%">${data.project_progress}%</div></div>
      <div class="pipeline">
        ${data.pipeline.map((p)=>`<div class="pipeline-step"><span>${esc(p.name)}</span><strong>${p.count}</strong></div>`).join("")}
      </div>
    </div>`;
}

async function loadScenes() {
  const scenes = await api("/api/scenes");
  $("scenes").innerHTML = `<div class="section-toolbar"><div><h2>סצנות</h2><div class="meta">סצנות המחוברות לשוטים ולמשך ההפקה</div></div><button onclick="newScene()">סצנה חדשה</button></div><div class="grid">${scenes.map((scene) => `
    <div class="card">
      <span class="badge">סצנה ${scene.scene_number}</span>
      <div class="title">${esc(scene.title)}</div>
      <div class="meta">${scene.shot_count} שוטים · ${Number(scene.duration_seconds || 0).toFixed(1)} שנ׳ · ${esc(scene.status || "מתוכנן")}</div>
      <p>${esc(scene.story_goal || "מטרת הסצנה טרם הוגדרה")}</p>
      <button onclick="openScene(${scene.id})">פתיחת Scene Workspace</button>
    </div>`).join("")}</div>`;
}

function newScene() {
  show(`<h2>סצנה חדשה</h2><div class="form-grid">
    <div><label>מספר סצנה</label><input id="newSceneNumber" type="number" min="1"></div>
    <div><label>סטטוס</label><input id="newSceneStatus" value="מתוכנן"></div>
    <div class="wide"><label>שם הסצנה</label><input id="newSceneTitle"></div>
    <div class="wide"><label>מטרה עלילתית</label><textarea id="newSceneGoal"></textarea></div>
  </div><button onclick="createScene()">יצירת סצנה</button>`);
}

async function createScene() {
  const scene = await api("/api/scenes", {method:"POST", body:JSON.stringify({
    project_id:currentProjectId,
    scene_number:Number($("newSceneNumber").value), title:$("newSceneTitle").value,
    status:$("newSceneStatus").value, story_goal:$("newSceneGoal").value
  })});
  await openScene(scene.id);
}

async function openScene(id) {
  const scene = await api(`/api/scenes/${id}`);
  show(`
    <div class="meta">סצנה ${scene.scene_number}</div>
    <h2>${esc(scene.title)}</h2>
    <div class="workspace-grid">
      <div class="workspace-section">
        <h3>Scene Bible</h3>
        <label>מספר סצנה</label><input id="scNumber" type="number" min="1" value="${scene.scene_number}">
        <label>סטטוס</label><input id="scStatus" value="${esc(scene.status || "מתוכנן")}">
        <label>שם הסצנה</label><input id="scTitle" value="${esc(scene.title)}">
        <label>מטרה עלילתית</label><textarea id="scGoal">${esc(scene.story_goal)}</textarea>
        <label>רגש מרכזי</label><textarea id="scEmotion">${esc(scene.emotion)}</textarea>
        <label>קונפליקט</label><textarea id="scConflict">${esc(scene.conflict)}</textarea>
        <label>מצב בתחילת הסצנה</label><textarea id="scBeginning">${esc(scene.beginning)}</textarea>
        <label>מצב בסיום הסצנה</label><textarea id="scEnding">${esc(scene.ending)}</textarea>
        <label>הערות</label><textarea id="scNotes">${esc(scene.notes)}</textarea>
        <button onclick="saveScene(${scene.id})">שמירת הסצנה</button>
      </div>
      <div class="workspace-section">
        <div class="section-toolbar"><h3>שוטים בסצנה</h3><button onclick="newShot(${scene.id})">שוט חדש</button></div>
        ${scene.shots.map((shot)=>`
          <div class="card">
            <div class="meta">שוט ${shot.shot_number} · ${shot.asset_count} נכסים</div>
            <div class="title">${esc(shot.title)}</div>
            <span class="badge">${esc(shot.status)}</span>
            <button onclick="openShot(${shot.id})">פתיחת Shot Workspace</button>
          </div>`).join("")}
      </div>
    </div>`);
}

async function saveScene(id) {
  const payload = {
    scene_number: Number($("scNumber").value),
    status: $("scStatus").value,
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
  $("shots").innerHTML = `<div class="section-toolbar"><div><h2>שוטים</h2><div class="meta">שדות צילום, גרסאות ותוצאות הפקה</div></div><button onclick="newShot()">שוט חדש</button></div><div class="grid">${shots.map((shot) => `
    <div class="card">
      <div class="meta">שוט ${shot.shot_number} · ${esc(shot.shot_type || "רגיל")} · סצנה ${shot.scene_number || "-"} · ${shot.asset_count} נכסים</div>
      <div class="title">${esc(shot.title)}</div>
      <span class="badge">${esc(shot.status)}</span>
      <div class="row">
        <button onclick="openShot(${shot.id})">פתיחת Workspace</button>
        <button class="secondary" onclick="checkContinuity(${shot.id})">בדיקת רציפות</button>
      </div>
    </div>`).join("")}</div>`;
}

async function newShot(sceneId = null) {
  const scenes = await api("/api/scenes");
  if (!scenes.length) return newScene();
  show(`<h2>שוט חדש</h2><div class="form-grid">
    <div><label>סצנה</label><select id="newShotScene">${scenes.map((s)=>`<option value="${s.id}" ${s.id===sceneId?"selected":""}>${s.scene_number} — ${esc(s.title)}</option>`).join("")}</select></div>
    <div><label>מספר שוט</label><input id="newShotNumber" type="number" min="1"></div>
    <div class="wide"><label>שם השוט</label><input id="newShotTitle"></div>
  </div><button onclick="createShot()">יצירת שוט</button>`);
}

async function createShot() {
  const shot = await api("/api/shots", {method:"POST", body:JSON.stringify({
    project_id:currentProjectId,
    scene_id:Number($("newShotScene").value), shot_number:Number($("newShotNumber").value),
    title:$("newShotTitle").value
  })});
  await openShot(shot.id);
}

async function openShot(id) {
  const [shot, assets, scenes] = await Promise.all([
    api(`/api/shots/${id}`),
    api("/api/assets"),
    api("/api/scenes")
  ]);
  const selected = new Set(shot.assets.map((a) => a.id));
  const shotTypes = ["רגיל","Establishing","Close-up","Medium","Wide","Insert","POV","Reaction","Transition"];

  show(`
    <div class="meta">סצנה ${shot.scene_number || "-"} · שוט ${shot.shot_number}</div>
    <h2>${esc(shot.title)}</h2>
    <div class="workspace-grid">
      <div>
        <div class="workspace-section">
          <h3>הגדרות שוט</h3>
          <label>שם השוט</label><input id="wsTitle" value="${esc(shot.title)}">
          <label>סצנה</label><select id="wsScene">${scenes.map((s)=>`<option value="${s.id}" ${s.id===shot.scene_id?"selected":""}>${s.scene_number} — ${esc(s.title)}</option>`).join("")}</select>
          <label>מספר שוט</label><input id="wsNumber" type="number" min="1" value="${shot.shot_number}">
          <label>משך בשניות</label><input id="wsDuration" type="number" min="0.1" step="0.1" value="${shot.duration_seconds || ""}">
          <label>סוג שוט</label>
          <select id="wsShotType">
            ${shotTypes.map((s)=>`<option ${s===(shot.shot_type||"רגיל")?"selected":""}>${s}</option>`).join("")}
          </select>
          <label>סטטוס</label>
          <select id="wsStatus">
            ${["מתוכנן","רפרנס","פרומפט מוכן","תמונה מאושרת","וידאו מוכן","וידאו מאושר","אודיו","QA","סופי"]
              .map((s)=>`<option ${s===shot.status?"selected":""}>${s}</option>`).join("")}
          </select>
          <label>פעולה</label><textarea id="wsAction">${esc(shot.action)}</textarea>
          <label>הערות</label><textarea id="wsNotes">${esc(shot.notes)}</textarea>
          <label>מצלמה וקומפוזיציה</label><textarea id="wsCamera">${esc(shot.camera)}</textarea>
          <label>זווית מצלמה</label><input id="wsCameraAngle" value="${esc(shot.camera_angle)}">
          <label>קומפוזיציה מובנית</label><textarea id="wsComposition">${esc(shot.composition)}</textarea>
          <label>עדשה</label><input id="wsLens" value="${esc(shot.lens)}">
          <label>תאורה</label><textarea id="wsLighting">${esc(shot.lighting)}</textarea>
          <label>תנועת מצלמה</label><textarea id="wsMovement">${esc(shot.movement)}</textarea>
          <label>מצב רוח</label><textarea id="wsMood">${esc(shot.mood)}</textarea>
          <label>פלטת צבעים</label><textarea id="wsPalette">${esc(shot.color_palette)}</textarea>
          <label>אודיו</label><textarea id="wsAudio">${esc(shot.audio)}</textarea>
          <label>דיאלוג</label><textarea id="wsDialogue">${esc(shot.dialogue)}</textarea>
          <label>פרומפט</label><textarea id="wsPrompt">${esc(shot.prompt)}</textarea>
          <label>Negative Prompt</label><textarea id="wsNegative">${esc(shot.negative_prompt)}</textarea>
          <div class="row">
            <button onclick="saveWorkspace(${shot.id})">שמירת שוט</button>
            <button class="secondary" onclick="runDirector(${shot.id})">Run Director</button>
          </div>
          <div class="row">
            <button class="secondary" onclick="generateWithOpenAI(${shot.id}, 'text')">AI: שיפור פרומפט</button>
            <button onclick="generateWithOpenAI(${shot.id}, 'image')">Nano Banana Pro · 2K</button>
          </div>
        </div>
      </div>
      <div>
        ${shot.previous_shot ? `
        <div class="workspace-section">
          <h3>השוואה לשוט קודם</h3>
          <div class="meta">שוט ${shot.previous_shot.shot_number}: ${esc(shot.previous_shot.title)}</div>
          <p>סוג: ${esc(shot.previous_shot.shot_type || "רגיל")}</p>
          <p>נכסים: ${shot.previous_shot.assets.map((a)=>esc(a.name)).join(", ") || "אין"}</p>
        </div>` : ""}
        <div class="workspace-section" style="margin-top:15px">
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
          <div class="section-toolbar"><h3>גרסאות פרומפט</h3><button onclick="makePrompt(${shot.id})">בניית פרומפט</button></div>
          ${shot.prompt_versions.length ? shot.prompt_versions.map((v)=>`<div class="history-item"><b>v${v.version}</b> · ${esc(v.source || "manual")}<div class="meta">${esc(v.created_at)}</div><p>${esc(v.prompt).slice(0,260)}</p></div>`).join("") : "<p>טרם נשמרו גרסאות.</p>"}
        </div>
        <div class="workspace-section" style="margin-top:15px">
          <div class="section-toolbar"><h3>תוצאות תמונה ווידאו</h3><button onclick="newMedia(${shot.id})">תוצאה חדשה</button></div>
          ${shot.media_results.length ? shot.media_results.map((m)=>`<div class="history-item"><b>${m.media_type==="image"?"תמונה":"וידאו"} v${m.version}</b> · ${esc(m.provider || "ללא ספק")} · ${esc(m.status)}<br><a href="${esc(m.url)}" target="_blank" rel="noopener">פתיחת תוצאה</a></div>`).join("") : "<p>טרם נשמרו תוצאות.</p>"}
          <button class="secondary" onclick="newIssueForShot(${shot.id})">הוספת בדיקת רציפות</button>
        </div>
      </div>
    </div>`);
}

async function saveWorkspace(id) {
  const payload = {
    title: $("wsTitle").value,
    scene_id: Number($("wsScene").value),
    shot_number: Number($("wsNumber").value),
    duration_seconds: $("wsDuration").value ? Number($("wsDuration").value) : null,
    shot_type: $("wsShotType").value,
    status: $("wsStatus").value,
    notes: $("wsNotes").value,
    action: $("wsAction").value,
    camera: $("wsCamera").value,
    camera_angle: $("wsCameraAngle").value,
    composition: $("wsComposition").value,
    lens: $("wsLens").value,
    lighting: $("wsLighting").value,
    movement: $("wsMovement").value,
    mood: $("wsMood").value,
    color_palette: $("wsPalette").value,
    audio: $("wsAudio").value,
    dialogue: $("wsDialogue").value,
    prompt: $("wsPrompt").value,
    negative_prompt: $("wsNegative").value,
  };
  await api(`/api/shots/${id}`, {method:"PATCH", body:JSON.stringify(payload)});
  alert("השוט נשמר.");
  await openShot(id);
}

async function newMedia(shotId) {
  const versions = await api(`/api/shots/${shotId}/prompts`);
  show(`<h2>תוצאת מדיה חדשה</h2><div class="form-grid">
    <div><label>סוג</label><select id="mediaType"><option value="image">תמונה</option><option value="video">וידאו</option></select></div>
    <div><label>סטטוס</label><input id="mediaStatus" value="טיוטה"></div>
    <div class="wide"><label>קישור לתוצאה</label><input id="mediaUrl"></div>
    <div><label>ספק</label><input id="mediaProvider" placeholder="Magnific / Runway / אחר"></div>
    <div><label>מודל</label><input id="mediaModel"></div>
    <div class="wide"><label>גרסת פרומפט מקור</label><select id="mediaPrompt"><option value="">ללא שיוך</option>${versions.map((v)=>`<option value="${v.id}">v${v.version} · ${esc(v.source)}</option>`).join("")}</select></div>
    <div class="wide"><label>הערות</label><textarea id="mediaNotes"></textarea></div>
  </div><button onclick="saveMedia(${shotId})">שמירת גרסה</button>`);
}

async function saveMedia(shotId) {
  await api(`/api/shots/${shotId}/media`, {method:"POST", body:JSON.stringify({
    media_type:$("mediaType").value, url:$("mediaUrl").value,
    provider:$("mediaProvider").value, model:$("mediaModel").value,
    prompt_version_id:$("mediaPrompt").value ? Number($("mediaPrompt").value) : null,
    status:$("mediaStatus").value, notes:$("mediaNotes").value
  })});
  await openShot(shotId);
}

function newIssueForShot(shotId) {
  show(`<h2>בדיקת רציפות חדשה</h2><div class="form-grid">
    <div><label>קטגוריה</label><input id="issueCategory"></div>
    <div><label>חומרה</label><select id="issueSeverity"><option>low</option><option selected>medium</option><option>high</option><option>critical</option></select></div>
    <div class="wide"><label>הבעיה</label><textarea id="issueMessage"></textarea></div>
    <div><label>מצב צפוי</label><textarea id="issueExpected"></textarea></div>
    <div><label>מצב שנמצא</label><textarea id="issueObserved"></textarea></div>
  </div><button onclick="saveIssue(${shotId})">שמירת בדיקה</button>`);
}

async function saveIssue(shotId) {
  await api("/api/issues", {method:"POST", body:JSON.stringify({
    project_id:currentProjectId,
    shot_id:shotId, category:$("issueCategory").value, severity:$("issueSeverity").value,
    message:$("issueMessage").value, expected:$("issueExpected").value,
    observed:$("issueObserved").value
  })});
  closeModal(); await loadQA();
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

async function generateWithOpenAI(id, mediaType) {
  if (mediaType === "image" && !confirm("ליצור תמונה חדשה? הפעולה משתמשת בקרדיט API.")) return;
  show(`<h2>יצירה באמצעות AI</h2><p>הבקשה נשלחה. נא להמתין…</p>`);
  try {
    const data = await api(`/api/generation/shots/${id}`, {
      method:"POST",
      body:JSON.stringify({
        media_type:mediaType,
        instructions:"",
        size:"1536x1024",
        quality:"medium"
      })
    });
    if (data.media_type === "image") {
      show(`<h2>Nano Banana Pro יוצר תמונת 2K</h2>
        <p>המשימה נשלחה. המערכת תבדוק אוטומטית מתי התמונה מוכנה.</p>`);
      await waitForMagnific(id, data.task_id);
      return;
    }
    show(`<h2>הפרומפט שופר ונשמר</h2><pre>${esc(data.prompt)}</pre>
      <button onclick="openShot(${id})">חזרה לשוט</button>`);
  } catch (error) {
    showError(error);
  }
}

async function waitForMagnific(shotId, taskId) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    try {
      const data = await api(`/api/generation/shots/${shotId}/magnific/${encodeURIComponent(taskId)}`);
      if (data.status === "COMPLETED" && data.media) {
        show(`<h2>התמונה נוצרה ב־Nano Banana Pro · 2K</h2>
          <img src="${esc(data.media.url)}" alt="תוצאת שוט" style="max-width:100%;border-radius:12px">
          <div class="row"><button onclick="openShot(${shotId})">שמירה וחזרה לשוט</button></div>`);
        return;
      }
      $("modalContent").innerHTML = `<h2>Nano Banana Pro יוצר תמונת 2K</h2>
        <p>סטטוס: ${esc(data.status)} · בדיקה ${attempt + 1}</p>`;
    } catch (error) {
      showError(error);
      return;
    }
  }
  show(`<h2>המשימה עדיין בתהליך</h2>
    <p>Magnific ממשיך ליצור את התמונה. אפשר לחזור לשוט ולבדוק שוב מאוחר יותר.</p>
    <button onclick="openShot(${shotId})">חזרה לשוט</button>`);
}

async function checkContinuity(id) {
  const data = await api(`/api/shots/${id}/continuity`, {method:"POST"});
  show(`<h2>בדיקת רציפות</h2>
    ${data.issues.length ? data.issues.map((issue) => `
      <div class="card issue-${esc(issue.severity)}">
        <b>${esc(issue.severity)}</b><p>${esc(issue.message)}</p>
      </div>`).join("") : "<p>לא נמצאו בעיות.</p>"}`);
}

/* Story Bible and QA functions remain unchanged */
async function loadAssets() {
  const assets = await api("/api/assets");
  $("assets").innerHTML = `
    <div class="asset-toolbar">
      <button onclick="newAsset()">נכס חדש</button>
      ${["הכול","דמות","לוקיישן","אביזר","לבוש","כלל","סגנון"]
        .map((t)=>`<button class="secondary" onclick="filterAssets('${t}')">${t}</button>`).join("")}
    </div>
    <div id="assetGrid" class="grid">${assets.map(assetCard).join("")}</div>`;
}
function assetCard(asset) {
  return `<div class="card" data-type="${esc(asset.asset_type)}">
    <span class="badge ${asset.approved?"approved":""}">${esc(asset.asset_type)}${asset.approved?" · מאושר":""}</span>
    <div class="title">${esc(asset.name)}</div><p>${esc(asset.description)}</p>
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
  show(`<h2>נכס חדש</h2><label>סוג</label><select id="asType">
    ${["דמות","לוקיישן","אביזר","לבוש","כלל","סגנון"].map((t)=>`<option>${t}</option>`).join("")}
    </select><label>שם</label><input id="asName"><label>תיאור</label><textarea id="asDescription"></textarea>
    <label>כללים חזותיים ורציפות</label><textarea id="asRules"></textarea>
    <label>Master Prompt</label><textarea id="asMaster"></textarea>
    <label>Negative Prompt</label><textarea id="asNegative"></textarea>
    <label>קישור לרפרנס</label><input id="asUrl"><button onclick="createAsset()">יצירת נכס</button>`);
}
async function createAsset() {
  const payload={project_id:currentProjectId,asset_type:$("asType").value,name:$("asName").value,description:$("asDescription").value,
  visual_rules:$("asRules").value,master_prompt:$("asMaster").value,negative_prompt:$("asNegative").value,
  reference_url:$("asUrl").value,approved:false};
  const asset=await api("/api/assets",{method:"POST",body:JSON.stringify(payload)});await openAsset(asset.id);
}
async function openAsset(id) {
  const asset=await api(`/api/assets/${id}`);
  show(`<div class="meta">${esc(asset.asset_type)} · גרסה ${asset.version}</div><h2>${esc(asset.name)}</h2>
  <div class="workspace-grid"><div class="workspace-section">
  <label>סוג</label><select id="asType">${["דמות","לוקיישן","אביזר","לבוש","כלל","סגנון"].map((t)=>`<option ${t===asset.asset_type?"selected":""}>${t}</option>`).join("")}</select>
  <label>שם</label><input id="asName" value="${esc(asset.name)}"><label>תיאור</label><textarea id="asDescription">${esc(asset.description)}</textarea>
  <label>כללים חזותיים ורציפות</label><textarea id="asRules">${esc(asset.visual_rules)}</textarea>
  <label>Master Prompt</label><textarea id="asMaster">${esc(asset.master_prompt)}</textarea>
  <label>Negative Prompt</label><textarea id="asNegative">${esc(asset.negative_prompt)}</textarea>
  <label>קישור לרפרנס</label><input id="asUrl" value="${esc(asset.reference_url)}">
  <label class="asset-check"><input type="checkbox" id="asApproved" ${asset.approved?"checked":""}><span>נכס מאושר</span></label>
  <div class="row"><button onclick="saveAsset(${asset.id})">שמירה</button><button class="danger" onclick="deleteAsset(${asset.id})">מחיקה</button></div>
  </div><div class="workspace-section"><h3>שוטים מקושרים</h3>
  ${asset.linked_shots.length?asset.linked_shots.map((s)=>`<div class="card"><div class="title">שוט ${s.shot_number}: ${esc(s.title)}</div><button onclick="openShot(${s.id})">פתיחת השוט</button></div>`).join(""):"<p>הנכס אינו משויך עדיין לשוטים.</p>"}
  </div></div>`);
}
async function saveAsset(id) {
  const payload={asset_type:$("asType").value,name:$("asName").value,description:$("asDescription").value,
  visual_rules:$("asRules").value,master_prompt:$("asMaster").value,negative_prompt:$("asNegative").value,
  reference_url:$("asUrl").value,approved:$("asApproved").checked};
  await api(`/api/assets/${id}`,{method:"PATCH",body:JSON.stringify(payload)});alert("הנכס נשמר.");await openAsset(id);
}
async function deleteAsset(id){if(!confirm("למחוק את הנכס?"))return;await api(`/api/assets/${id}`,{method:"DELETE"});closeModal();await loadAssets();}

async function loadQA() {
  const issues=await api("/api/issues");
  $("qa").innerHTML=`<div class="qa-toolbar"><button onclick="filterIssues('all')">הכול</button>
  <button class="secondary" onclick="filterIssues('critical')">Critical</button><button class="secondary" onclick="filterIssues('high')">High</button>
  <button class="secondary" onclick="filterIssues('medium')">Medium</button><button class="secondary" onclick="filterIssues('low')">Low</button>
  <button class="secondary" onclick="filterIssues('resolved')">Resolved</button><button class="danger" onclick="clearResolved()">מחיקת בעיות פתורות</button></div>
  <div id="issueGrid" class="grid">${issues.length?issues.map(issueCard).join(""):"<p>אין עדיין בעיות שמורות.</p>"}</div>`;
}
function issueCard(issue){return `<div class="card issue-${esc(issue.severity)} ${issue.resolved?"issue-resolved":""}" data-severity="${esc(issue.severity)}" data-resolved="${issue.resolved}">
<span class="badge">${esc(issue.severity)} · ${esc(issue.status || (issue.resolved?"נפתר":"פתוח"))}</span><div class="title">${esc(issue.category)}</div><p>${esc(issue.message)}</p>
${issue.expected?`<p><b>צפוי:</b> ${esc(issue.expected)}</p>`:""}${issue.observed?`<p><b>נמצא:</b> ${esc(issue.observed)}</p>`:""}${issue.resolution?`<p><b>פתרון:</b> ${esc(issue.resolution)}</p>`:""}
<div class="meta">${issue.shot_number?`שוט ${issue.shot_number}: ${esc(issue.shot_title)}`:""}</div>
<div class="row">${issue.shot_id?`<button onclick="openShot(${issue.shot_id})">פתיחת השוט</button>`:""}
<select onchange="setIssueStatus(${issue.id},this.value)">${["פתוח","בטיפול","נפתר","אושר כחריגה"].map((s)=>`<option ${s===(issue.status || (issue.resolved?"נפתר":"פתוח"))?"selected":""}>${s}</option>`).join("")}</select></div></div>`;}
function filterIssues(filter){document.querySelectorAll("#issueGrid .card").forEach((card)=>{const visible=filter==="all"||(filter==="resolved"&&card.dataset.resolved==="1")||card.dataset.severity===filter;card.style.display=visible?"":"none";});}
async function toggleIssue(id,resolved){await api(`/api/issues/${id}/resolve?resolved=${resolved}`,{method:"PATCH"});await loadQA();await loadDashboard();}
async function setIssueStatus(id,status){await api(`/api/issues/${id}`,{method:"PATCH",body:JSON.stringify({status})});await loadQA();await loadDashboard();}
async function clearResolved(){if(!confirm("למחוק את כל הבעיות הפתורות?"))return;await api("/api/issues/resolved",{method:"DELETE"});await loadQA();}

function show(html){$("modalContent").innerHTML=html;$("modal").style.display="flex";}
function closeModal(){$("modal").style.display="none";}
function showError(error){console.error(error);show(`<h2>שגיאה</h2><p>${esc(error.message)}</p>`);}

const loaders={dashboard:loadDashboard,scenes:loadScenes,shots:loadShots,assets:loadAssets,qa:loadQA};
(async function init() {
  try {
    await loadProjects();
  } catch (error) {
    console.error(error);
  }
  loadDashboard().catch(showError);
})();
