const $ = (id) => document.getElementById(id);

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[char]
  );

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "שגיאה");
  }

  return data;
}

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    document
      .querySelectorAll(".panel")
      .forEach((panel) => panel.classList.remove("active"));

    const target = $(button.dataset.tab);

    if (!target) {
      return;
    }

    target.classList.add("active");

    const loader = loaders[button.dataset.tab];

    if (loader) {
      loader().catch(showError);
    }
  });
});

async function loadDashboard() {
  const data = await api("/api/dashboard");

  $("dashboard").innerHTML = `
    <div class="grid">
      <div class="card">
        <div class="meta">שוטים</div>
        <div class="stat">${data.shots_total}</div>
      </div>

      <div class="card">
        <div class="meta">סצנות</div>
        <div class="stat">${data.scenes_total}</div>
      </div>

      <div class="card">
        <div class="meta">נכסים</div>
        <div class="stat">${data.assets_total}</div>
      </div>

      <div class="card">
        <div class="meta">בעיות פתוחות</div>
        <div class="stat">${data.open_issues}</div>
      </div>
    </div>
  `;
}

async function loadScenes() {
  const scenes = await api("/api/scenes");

  $("scenes").innerHTML = `
    <div class="grid">
      ${scenes
        .map(
          (scene) => `
            <div class="card">
              <span class="badge">סצנה ${scene.scene_number}</span>
              <div class="title">${esc(scene.title)}</div>
              <div class="meta">${scene.shot_count} שוטים</div>
              <button onclick="openScene(${scene.id})">פתיחה</button>
            </div>
          `
        )
        .join("")}
    </div>
  `;
}

async function openScene(id) {
  const scene = await api(`/api/scenes/${id}`);

  show(`
    <h2>סצנה ${scene.scene_number}: ${esc(scene.title)}</h2>

    <p>${esc(scene.story_goal || "טרם הוגדרה מטרת סצנה")}</p>

    <div class="grid">
      ${scene.shots
        .map(
          (shot) => `
            <div class="card">
              <div class="title">
                ${shot.shot_number}. ${esc(shot.title)}
              </div>
              <div class="meta">${esc(shot.status)}</div>
            </div>
          `
        )
        .join("")}
    </div>
  `);
}

async function loadShots() {
  const shots = await api("/api/shots");

  $("shots").innerHTML = `
    <div class="grid">
      ${shots
        .map(
          (shot) => `
            <div class="card">
              <div class="meta">
                שוט ${shot.shot_number}
                · סצנה ${shot.scene_number || "-"}
                · ${shot.asset_count} נכסים
              </div>

              <div class="title">${esc(shot.title)}</div>

              <span class="badge">${esc(shot.status)}</span>

              <div class="row">
                <button onclick="makePrompt(${shot.id})">
                  בניית פרומפט
                </button>

                <button onclick="checkContinuity(${shot.id})">
                  בדיקת רציפות
                </button>
              </div>
            </div>
          `
        )
        .join("")}
    </div>
  `;
}

async function makePrompt(id) {
  const data = await api(`/api/shots/${id}/prompt`, {
    method: "POST",
  });

  show(`
    <h2>פרומפט</h2>
    <pre>${esc(data.prompt)}</pre>
  `);
}

async function checkContinuity(id) {
  const data = await api(`/api/shots/${id}/continuity`, {
    method: "POST",
  });

  show(`
    <h2>בדיקת רציפות</h2>

    ${
      data.issues.length
        ? data.issues
            .map(
              (issue) => `
                <div class="card">
                  <b>${esc(issue.severity)}</b>
                  <p>${esc(issue.message)}</p>
                </div>
              `
            )
            .join("")
        : "<p>לא נמצאו בעיות.</p>"
    }
  `);
}

async function loadAssets() {
  const assets = await api("/api/assets");

  $("assets").innerHTML = `
    <div class="grid">
      ${assets
        .map(
          (asset) => `
            <div class="card">
              <span class="badge">${esc(asset.asset_type)}</span>

              <div class="title">${esc(asset.name)}</div>

              <p>${esc(asset.description)}</p>

              <div class="meta">
                ${esc(asset.visual_rules)}
              </div>
            </div>
          `
        )
        .join("")}
    </div>
  `;
}

function show(html) {
  $("modalContent").innerHTML = html;
  $("modal").style.display = "flex";
}

function closeModal() {
  $("modal").style.display = "none";
}

function showError(error) {
  console.error(error);

  show(`
    <h2>שגיאה</h2>
    <p>${esc(error.message)}</p>
  `);
}

const loaders = {
  dashboard: loadDashboard,
  scenes: loadScenes,
  shots: loadShots,
  assets: loadAssets,
};

loadDashboard().catch(showError);
