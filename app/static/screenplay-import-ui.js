// Two-stage screenplay import UI: parse -> structured preview -> compare
// against existing production data -> explicit approve. Talks to
// /api/screenplay-imports (app/api/screenplay_imports.py), not the older
// /api/import-runs chunked flow. Standalone page (script_import.html does
// not load app.js), so this file owns its own tiny DOM/fetch helpers
// rather than reusing app.js's.

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[ch]));
}

async function apiCall(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  } catch (_error) {
    throw new FilmOsApiError("לא ניתן להגיע לשרת. בדקי את החיבור ונסי שוב.", {
      code: "network_error", retryable: true,
    });
  }
  return parseApiResponse(response);
}

// Screenplays are uploaded in small pieces rather than one large POST — a
// network-level content filter observed in production (an Israeli ISP/
// organizational filter, "Rimon") blocks POST bodies above some threshold
// to this same endpoint with an HTML block page disguised as HTTP 200,
// while small POSTs to the identical path go through untouched.
// Production traffic showed a ~7.4KB and a ~61KB request blocked, and
// later a ~1000-character (under 2KB) request blocked too — there's no
// reliable fixed size to pick up front — so instead of guessing one,
// this starts at a modest size and, whenever a piece gets the same block
// signature, halves *that piece* and retries rather than failing
// outright. It also pauses briefly before each retry: production traffic
// has shown blocks persisting even as chunks shrink toward the floor,
// which is consistent with the filter also reacting to a fast burst of
// requests to the same path, not size alone — spacing requests out costs
// little and can only help that case. Chunking is purely a transport
// concern: the server only ever parses the fully reassembled text in one
// call (app/services/chunked_screenplay_upload.py), so none of this
// changes how the screenplay is understood.
const UPLOAD_CHUNK_START_CHARS = 1000;
const UPLOAD_CHUNK_MIN_CHARS = 20;
const UPLOAD_RETRY_DELAY_MS = 400;
const UPLOAD_MAX_FLOOR_RETRIES = 4;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function generateUploadId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// These are the FilmOsApiError codes safe_api.js throws when a response
// isn't the JSON we expect — exactly the shape of a network filter's HTML
// block page arriving with a 200 status. A real backend error uses its
// own stable category codes (see app/api/screenplay_imports.py) and is
// never one of these, so this check doesn't risk swallowing genuine
// application errors.
const NETWORK_FILTER_ERROR_CODES = new Set(["non_json_response", "empty_response", "malformed_json"]);

async function uploadScreenplayInChunks(text, { projectId, sourceType, sourceFilename, importRunId, force, onProgress }) {
  const uploadId = generateUploadId();
  const totalChars = text.length || 1;
  let offset = 0;
  let chunkSize = UPLOAD_CHUNK_START_CHARS;
  let floorRetries = 0;
  let result = null;

  do {
    const remaining = text.length - offset;
    const size = Math.min(chunkSize, Math.max(remaining, 1));
    const chunkText = text.slice(offset, offset + size);
    const isFinal = offset + size >= text.length;

    try {
      result = await apiCall("/api/screenplay-imports/upload-chunk", {
        method: "POST",
        body: JSON.stringify({
          upload_id: uploadId,
          chunk_text: chunkText,
          is_final: isFinal,
          project_id: projectId,
          source_type: sourceType,
          source_filename: sourceFilename,
          import_run_id: importRunId || null,
          force: Boolean(force),
        }),
      });
    } catch (error) {
      if (NETWORK_FILTER_ERROR_CODES.has(error && error.code)) {
        if (chunkSize > UPLOAD_CHUNK_MIN_CHARS) {
          chunkSize = Math.max(UPLOAD_CHUNK_MIN_CHARS, Math.floor(chunkSize / 2));
          await delay(UPLOAD_RETRY_DELAY_MS);
          continue; // retry the same offset at a smaller size, after a short pause
        }
        // Already at the floor size — can't shrink further. If this looks
        // like a burst/rate reaction rather than a pure size limit, waiting
        // longer (not smaller) is the only thing left to try before giving up.
        if (floorRetries < UPLOAD_MAX_FLOOR_RETRIES) {
          floorRetries += 1;
          await delay(UPLOAD_RETRY_DELAY_MS * (floorRetries + 1));
          continue;
        }
      }
      throw error;
    }

    offset += size;
    floorRetries = 0;
    if (onProgress) onProgress(offset, totalChars);
  } while (offset < text.length);

  return result;
}

const state = {
  phase: "input", // input -> preview -> diff -> done
  projectId: null,
  sourceType: "paste",
  sourceFilename: "",
  run: null,
  diff: null,
  approveResult: null,
  busy: false,
  errorMessage: null,
};

const SCENE_DETAIL_CATEGORY_LABELS = {
  action: "פעולה", dialogue: "דיאלוג", parenthetical: "הנחיה", transition: "מעבר",
  direction: "הנחיית במה", other: "אחר",
};

function blockLabel(block) {
  const type = SCENE_DETAIL_CATEGORY_LABELS[block.block_type] || block.block_type;
  if (block.block_type === "dialogue") {
    return `<b>${escapeHtml(block.character_name)}</b>${block.parenthetical ? ` <i>(${escapeHtml(block.parenthetical)})</i>` : ""}: ${escapeHtml(block.raw_text)}`;
  }
  return `<span class="badge">${type}</span> ${escapeHtml(block.raw_text)}`;
}

function sceneCard(scene, { expanded = false } = {}) {
  const badges = [scene.int_ext, scene.location, scene.time_of_day]
    .filter(Boolean).map((value) => `<span class="badge">${escapeHtml(value)}</span>`).join(" ");
  const lowConfidenceCount = (scene.blocks || []).filter((b) => b.confidence === "low").length;
  const warningBadge = lowConfidenceCount
    ? `<span class="badge issue-medium">${lowConfidenceCount} סיווגים לא ודאים</span>` : "";
  const blocksHtml = (scene.blocks || []).map((block) => `<div class="meta">${blockLabel(block)}</div>`).join("");
  return `
    <details class="card" ${expanded ? "open" : ""} style="margin-bottom:10px">
      <summary><b>סצנה ${scene.scene_number}</b> · ${escapeHtml(scene.original_heading)} ${badges} ${warningBadge}</summary>
      <p class="meta">${(scene.participants || []).map(escapeHtml).join(", ") || "אין דמויות מדברות"}</p>
      ${blocksHtml}
    </details>`;
}

function entityCard(entity, label, entityType) {
  const aliases = (entity.aliases || []).filter((a) => a !== entity.canonical_name);
  return `
    <div class="card entity-card" style="margin-bottom:8px" data-entity-type="${entityType}" data-original-name="${escapeHtml(entity.canonical_name)}">
      <b>${escapeHtml(entity.canonical_name)}</b>
      ${aliases.length ? `<span class="meta"> · גם: ${aliases.map(escapeHtml).join(", ")}</span>` : ""}
      <p class="meta">${label} ראשון: סצנה ${entity.first_appearance_scene_number}</p>
      <div class="row" style="margin-top:6px">
        <input class="entity-rename-input" type="text" value="${escapeHtml(entity.canonical_name)}" style="flex:1">
        <button class="secondary entity-rename-button" type="button">שינוי שם</button>
        <button class="secondary issue-high entity-delete-button" type="button">מחיקה</button>
      </div>
    </div>`;
}

function wireEntityCardControls() {
  document.querySelectorAll(".entity-card").forEach((card) => {
    const entityType = card.dataset.entityType;
    const originalName = card.dataset.originalName;
    card.querySelector(".entity-rename-button").onclick = async () => {
      const newName = card.querySelector(".entity-rename-input").value.trim();
      if (!newName || newName === originalName) return;
      await withEntityEditBusy(card, async () => {
        state.run = await apiCall(
          `/api/screenplay-imports/${state.run.id}/entities/${entityType}/rename`,
          { method: "POST", body: JSON.stringify({ canonical_name: originalName, new_name: newName }) },
        );
      });
    };
    card.querySelector(".entity-delete-button").onclick = async () => {
      if (!confirm(`למחוק את "${originalName}" מהפירוק?`)) return;
      await withEntityEditBusy(card, async () => {
        state.run = await apiCall(
          `/api/screenplay-imports/${state.run.id}/entities/${entityType}/delete`,
          { method: "POST", body: JSON.stringify({ canonical_name: originalName }) },
        );
      });
    };
  });
}

async function withEntityEditBusy(card, action) {
  card.querySelectorAll("button").forEach((b) => { b.disabled = true; });
  try {
    await action();
    state.errorMessage = null;
  } catch (error) {
    state.errorMessage = error && error.message ? error.message : "העדכון נכשל.";
  }
  renderPreview();
}

function warningsHtml(warnings) {
  if (!warnings || !warnings.length) return "";
  const items = warnings.map((w) => `<li class="issue-medium" style="padding:6px 10px">${escapeHtml(w.message)}</li>`).join("");
  return `<div class="card" style="margin-top:14px"><b>אזהרות (${warnings.length})</b><ul style="padding-inline-start:20px">${items}</ul></div>`;
}

// --- Phase: input ----------------------------------------------------------

function renderInput() {
  $("app").innerHTML = `
    <div class="workspace-section">
      <label>הפקה</label><select id="project"></select>
      <label>תסריט מלא (הדבקה או העלאת קובץ .txt/.fountain)</label>
      <input id="file" type="file" accept=".txt,.fountain,text/plain">
      <textarea id="screenplay" style="min-height:420px" placeholder="הדביקי כאן את כל התסריט...">${escapeHtml(state.pendingText || "")}</textarea>
      <p class="meta">הניתוח הראשוני אינו כותב לפרויקט. תתבקשי לבדוק ולאשר לפני שמירה בפועל.</p>
      <div class="row"><button id="parseButton">ניתוח התסריט</button><a href="/">חזרה למערכת</a></div>
      ${state.errorMessage ? `<div class="card issue-high" style="margin-top:12px">${escapeHtml(state.errorMessage)}</div>` : ""}
    </div>`;
  $("file").onchange = onFileChosen;
  $("parseButton").onclick = onParseClicked;
  populateProjects().catch((error) => {
    const message = error && error.message ? error.message : "לא ניתן היה לטעון את רשימת ההפקות.";
    const banner = document.createElement("div");
    banner.className = "card issue-high";
    banner.style.marginTop = "12px";
    banner.textContent = message;
    $("app").appendChild(banner);
  });
}

async function populateProjects() {
  const projects = await apiCall("/api/projects");
  $("project").innerHTML = projects.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  const saved = Number(localStorage.getItem("filmOsProjectId"));
  if (saved) $("project").value = String(saved);
  if (state.projectId) $("project").value = String(state.projectId);
}

const SUPPORTED_TEXT_EXTENSIONS = [".txt", ".fountain"];

function onFileChosen() {
  const file = $("file").files[0];
  if (!file) return;
  const lower = file.name.toLowerCase();
  if (!SUPPORTED_TEXT_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
    state.errorMessage = "פורמט הקובץ אינו נתמך. יש להעלות קובץ טקסט (.txt) או Fountain (.fountain), או להדביק את התסריט ישירות.";
    renderInput();
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    state.sourceType = "upload";
    state.sourceFilename = file.name;
    state.pendingText = String(reader.result || "");
    state.errorMessage = null;
    renderInput();
  };
  reader.onerror = () => {
    state.errorMessage = "לא ניתן היה לקרוא את הקובץ.";
    renderInput();
  };
  reader.readAsText(file, "utf-8");
}

async function onParseClicked() {
  const text = $("screenplay").value;
  if (text.trim().length < 10) {
    state.errorMessage = "יש להדביק או להעלות תסריט לניתוח.";
    renderInput();
    return;
  }
  state.projectId = Number($("project").value);
  localStorage.setItem("filmOsProjectId", String(state.projectId));
  state.pendingText = text;
  await runParse(text, { buttonId: "parseButton", force: false });
}

// Shared by the initial parse and by "re-analyze anyway" on the duplicate
// screen (force: true) — same upload, same finalize, only the duplicate-
// shortcut behavior differs.
async function runParse(text, { buttonId, force }) {
  await withBusyButton(buttonId, async () => {
    const uploadResult = await uploadScreenplayInChunks(text, {
      projectId: state.projectId,
      sourceType: state.sourceType,
      sourceFilename: state.sourceFilename,
      force,
      onProgress: (done, total) => setBusyButtonProgress(buttonId, done, total),
    });
    await finalizeUploadResult(uploadResult, "preview");
  });
}

// The upload-chunk endpoint's final response is deliberately small (just
// an id) rather than the full breakdown, since a large response can hit
// the same network filter as a large request — so the full structured
// preview is always fetched separately once the upload itself succeeded.
async function finalizeUploadResult(uploadResult, phaseOnSuccess) {
  state.errorMessage = null;
  if (uploadResult.duplicate_of_import_run_id) {
    state.run = {
      id: uploadResult.import_run_id,
      duplicate_of_import_run_id: uploadResult.duplicate_of_import_run_id,
    };
    state.phase = "duplicate";
    return;
  }
  state.run = await apiCall(`/api/screenplay-imports/${uploadResult.import_run_id}`);
  state.phase = phaseOnSuccess;
}

// --- Phase: duplicate (already-approved identical screenplay) --------------

function renderDuplicate() {
  $("app").innerHTML = `
    <div class="workspace-section">
      <h3>התסריט הזה כבר יובא ואושר</h3>
      <p class="meta">לא נוצרה ריצת ייבוא חדשה — הפירוק המאושר הקיים (מזהה ${state.run.duplicate_of_import_run_id}) זהה לחלוטין לטקסט שהוזן.</p>
      <p class="meta">אם המערכת עודכנה מאז האישור המקורי וברצונך לבדוק תצוגה מקדימה מחודשת על אותו טקסט בדיוק — ניתן לנתח מחדש במפורש. זה לא משנה שום דבר בפרויקט; עדיין תעברי דרך תצוגה מקדימה, השוואה ואישור מפורש לפני שמירה.</p>
      <div class="row">
        <button id="reanalyzeAnywayButton">נתח מחדש בכל זאת</button>
        <button class="secondary" onclick="restart()">חזרה למסך הזנה</button>
        <a href="/">פתיחת AI Film OS</a>
      </div>
    </div>`;
  $("reanalyzeAnywayButton").onclick = () => runParse(state.pendingText || "", {
    buttonId: "reanalyzeAnywayButton", force: true,
  });
}

// --- Phase: preview ----------------------------------------------------------

function renderPreview() {
  const run = state.run;
  const editing = Boolean(state.editingText);
  $("app").innerHTML = `
    <div class="workspace-section">
      <div class="pipeline">
        <div class="pipeline-step"><strong>${run.scene_count}</strong>סצנות</div>
        <div class="pipeline-step"><strong>${run.character_count}</strong>דמויות</div>
        <div class="pipeline-step"><strong>${run.location_count}</strong>לוקיישנים</div>
        <div class="pipeline-step"><strong>${run.prop_count}</strong>אביזרים</div>
        <div class="pipeline-step"><strong>${run.warnings.length}</strong>אזהרות</div>
      </div>
      ${warningsHtml(run.warnings)}
      ${editing ? `
        <div class="card" style="margin-top:14px">
          <label>עריכת התסריט לפני ניתוח מחדש</label>
          <textarea id="editScreenplay" style="min-height:320px">${escapeHtml(state.pendingEditText ?? run.screenplay_text)}</textarea>
          <div class="row">
            <button id="reparseButton">ניתוח מחדש</button>
            <button class="secondary" id="cancelEditButton">ביטול עריכה</button>
          </div>
        </div>` : ""}
      <div class="section-toolbar" style="margin-top:16px"><h3>סצנות (לפי סדר מקורי)</h3></div>
      ${run.scenes.map((s) => sceneCard(s)).join("")}
      <div class="section-toolbar"><h3>דמויות</h3></div>
      ${run.characters.map((c) => entityCard(c, "הופעה", "characters")).join("") || '<p class="meta">לא זוהו דמויות.</p>'}
      <div class="section-toolbar"><h3>לוקיישנים</h3></div>
      ${run.locations.map((l) => entityCard(l, "הופעה", "locations")).join("") || '<p class="meta">לא זוהו לוקיישנים.</p>'}
      <div class="section-toolbar"><h3>אביזרים</h3></div>
      ${run.props.map((p) => entityCard(p, "הופעה", "props")).join("") || '<p class="meta">לא זוהו אביזרים מסומנים במרכאות.</p>'}
      <div class="row" style="margin-top:16px">
        <button id="reviewButton">השוואה מול הפרויקט ואישור</button>
        ${editing ? "" : '<button class="secondary" id="editButton">עריכת התסריט וניתוח מחדש</button>'}
        <button class="secondary" onclick="restart()">ביטול</button>
      </div>
      ${state.errorMessage ? `<div class="card issue-high" style="margin-top:12px">${escapeHtml(state.errorMessage)}</div>` : ""}
    </div>`;
  $("reviewButton").onclick = onReviewClicked;
  if (editing) {
    $("reparseButton").onclick = onReparseClicked;
    $("cancelEditButton").onclick = () => { state.editingText = false; state.pendingEditText = null; renderPreview(); };
  } else {
    $("editButton").onclick = () => { state.editingText = true; renderPreview(); };
  }
  wireEntityCardControls();
}

async function onReparseClicked() {
  const text = $("editScreenplay").value;
  state.pendingEditText = text;
  if (text.trim().length < 10) {
    state.errorMessage = "יש להזין תסריט תקין.";
    return renderPreview();
  }
  const reparsingRunId = state.run.id;
  await withBusyButton("reparseButton", async () => {
    const uploadResult = await uploadScreenplayInChunks(text, {
      projectId: state.projectId,
      sourceType: state.sourceType,
      sourceFilename: state.sourceFilename,
      importRunId: reparsingRunId,
      onProgress: (done, total) => setBusyButtonProgress("reparseButton", done, total),
    });
    await finalizeUploadResult(uploadResult, "preview");
    state.editingText = false;
    state.pendingEditText = null;
  });
}

async function onReviewClicked() {
  await withBusyButton("reviewButton", async () => {
    state.diff = await apiCall(`/api/screenplay-imports/${state.run.id}/diff`);
    state.phase = "diff";
    state.errorMessage = null;
  });
}

// --- Phase: diff / compare --------------------------------------------------

function diffSceneRow(scene, existingId) {
  return `<li>${existingId ? `#${existingId} · ` : ""}סצנה ${scene.scene_number} · ${escapeHtml(scene.normalized_heading || scene.original_heading)}</li>`;
}

function renderDiff() {
  const diff = state.diff;
  const protectedRemovals = diff.removed.filter((s) => Number(s.shot_count || 0) > 0);
  const safeRemovals = diff.removed.filter((s) => !(Number(s.shot_count || 0) > 0));
  $("app").innerHTML = `
    <div class="workspace-section">
      <h3>השוואה מול הסצנות הקיימות בפרויקט</h3>
      <div class="pipeline">
        <div class="pipeline-step"><strong>${diff.added.length}</strong>נוספות</div>
        <div class="pipeline-step"><strong>${diff.changed.length}</strong>משתנות</div>
        <div class="pipeline-step"><strong>${diff.unchanged.length}</strong>ללא שינוי</div>
        <div class="pipeline-step"><strong>${diff.removed.length}</strong>מוסרות</div>
      </div>
      ${diff.added.length ? `<div class="card" style="margin-top:12px"><b>סצנות חדשות שיתווספו</b><ul>${diff.added.map((s) => diffSceneRow(s)).join("")}</ul></div>` : ""}
      ${diff.changed.length ? `<div class="card issue-medium" style="margin-top:12px"><b>סצנות קיימות שישתנו (המזהה נשמר)</b><ul>${diff.changed.map((row) => diffSceneRow(row.scene, row.existing_scene_id)).join("")}</ul></div>` : ""}
      ${safeRemovals.length ? `<div class="card issue-high" style="margin-top:12px"><b>סצנות קיימות שיוסרו</b><ul>${safeRemovals.map((s) => diffSceneRow(s, s.id)).join("")}</ul></div>` : ""}
      ${protectedRemovals.length ? `<div class="card issue-critical" style="margin-top:12px"><b>לא ניתן להסיר — קיימים שוטים בסצנות אלו</b><ul>${protectedRemovals.map((s) => diffSceneRow(s, s.id)).join("")}</ul><p class="meta">אישור הייבוא ייחסם כל עוד סצנות אלו מיועדות להסרה. יש לשמור עליהן בתסריט או להשאיר את הסצנות הקיימות ללא שינוי.</p></div>` : ""}
      ${!diff.has_differences ? '<p class="meta">אין שינויים — ייבוא ראשוני נקי.</p>' : ""}
      <div class="row" style="margin-top:16px">
        <button id="approveButton" ${protectedRemovals.length ? "disabled" : ""}>אישור ושמירה לפרויקט</button>
        <button class="secondary" onclick="backToPreview()">חזרה לתצוגה המקדימה</button>
      </div>
      ${state.errorMessage ? `<div class="card issue-high" style="margin-top:12px">${escapeHtml(state.errorMessage)}</div>` : ""}
    </div>`;
  $("approveButton").onclick = onApproveClicked;
}

function backToPreview() {
  state.phase = "preview";
  render();
}

async function onApproveClicked() {
  await withBusyButton("approveButton", async () => {
    const result = await apiCall(`/api/screenplay-imports/${state.run.id}/approve`, {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    });
    state.approveResult = result;
    state.phase = "done";
    state.errorMessage = null;
  });
}

// --- Phase: done -------------------------------------------------------------

function renderDone() {
  const result = state.approveResult;
  $("app").innerHTML = `
    <div class="workspace-section">
      <h3>הייבוא אושר ונשמר</h3>
      <div class="pipeline">
        <div class="pipeline-step"><strong>${result.scenes_added}</strong>נוספו</div>
        <div class="pipeline-step"><strong>${result.scenes_changed}</strong>עודכנו</div>
        <div class="pipeline-step"><strong>${result.scenes_removed}</strong>הוסרו</div>
        <div class="pipeline-step"><strong>${result.scenes_unchanged}</strong>ללא שינוי</div>
      </div>
      <p class="meta">${result.characters_created} דמויות, ${result.locations_created} לוקיישנים ו-${result.props_created} אביזרים נשמרו במאגר הפרויקט.</p>
      <p class="meta">${result.story_bible_cards_created} כרטיסי Story Bible חדשים נוצרו עבור ישויות שעדיין לא היו בספר הסיפור.</p>
      <div class="row">
        <a href="/">פתיחת AI Film OS</a>
        <button class="secondary" onclick="restart()">ייבוא תסריט נוסף</button>
      </div>
    </div>`;
}

// --- Shared plumbing ---------------------------------------------------------

function setBusyButtonProgress(buttonId, doneChars, totalChars) {
  const button = $(buttonId);
  if (!button || totalChars <= UPLOAD_CHUNK_START_CHARS) return;
  const percent = Math.min(100, Math.round((doneChars / totalChars) * 100));
  button.textContent = `מעלה... ${percent}%`;
}

async function withBusyButton(buttonId, action) {
  const button = $(buttonId);
  if (button) button.disabled = true;
  try {
    await action();
  } catch (error) {
    state.errorMessage = error && error.message ? error.message : "אירעה שגיאה.";
  } finally {
    render();
  }
}

function restart() {
  const projectId = state.projectId;
  Object.assign(state, {
    phase: "input", sourceType: "paste", sourceFilename: "", run: null, diff: null,
    approveResult: null, busy: false, errorMessage: null, pendingText: "", editingText: false,
    pendingEditText: null,
  });
  state.projectId = projectId;
  render();
}

function render() {
  if (state.phase === "input") return renderInput();
  if (state.phase === "duplicate") return renderDuplicate();
  if (state.phase === "preview") return renderPreview();
  if (state.phase === "diff") return renderDiff();
  if (state.phase === "done") return renderDone();
}

render();
