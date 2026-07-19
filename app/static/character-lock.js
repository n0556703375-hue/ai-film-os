const LOCK_LABELS = {draft: "טיוטה", review: "בבדיקה", locked: "נעול"};
const LOCKABLE_TYPES = new Set(["דמות", "לוקיישן", "לבוש"]);

async function openAsset(id) {
  const asset = await api(`/api/assets/${id}`);
  const isLockable = LOCKABLE_TYPES.has(asset.asset_type);
  const isCharacter = asset.asset_type === "דמות";
  const isLocked = asset.lock_status === "locked";
  const lockLabel = LOCK_LABELS[asset.lock_status] || asset.lock_status || "טיוטה";
  const references = asset.reference_images || [];
  const lockTitle = isCharacter ? "Character Lock" : asset.asset_type === "לוקיישן" ? "Location Lock" : "Wardrobe Lock";

  show(`<div class="meta">${esc(asset.asset_type)} · גרסה ${asset.version}</div>
  <div class="row"><h2>${esc(asset.name)}</h2>${isLockable ? `<span class="badge ${isLocked ? "approved" : ""}">${lockTitle}: ${esc(lockLabel)}</span>` : ""}</div>
  <div class="workspace-grid"><div class="workspace-section">
  ${isLocked ? `<div class="card"><b>הנכס נעול</b><p class="meta">שדות ה־Master והרפרנס הראשי מוגנים משינוי עד לפתיחת הנעילה.</p></div>` : ""}
  <label>סוג</label><select id="asType" ${isLocked ? "disabled" : ""}>${["דמות","לוקיישן","אביזר","לבוש","כלל","סגנון"].map((t)=>`<option ${t===asset.asset_type?"selected":""}>${t}</option>`).join("")}</select>
  <label>שם</label><input id="asName" value="${esc(asset.name)}"><label>תיאור</label><textarea id="asDescription">${esc(asset.description)}</textarea>
  <label>כללים חזותיים ורציפות</label><textarea id="asRules" ${isLocked ? "disabled" : ""}>${esc(asset.visual_rules)}</textarea>
  <label>Master Prompt</label><textarea id="asMaster" ${isLocked ? "disabled" : ""}>${esc(asset.master_prompt)}</textarea>
  <label>Negative Prompt</label><textarea id="asNegative" ${isLocked ? "disabled" : ""}>${esc(asset.negative_prompt)}</textarea>
  <label>תמונת רפרנס ראשית</label><input id="asUrl" value="${esc(asset.reference_url)}" ${isLocked ? "disabled" : ""}>
  ${asset.reference_url?`<img src="${esc(asset.reference_url)}" alt="רפרנס ${esc(asset.name)}" style="width:100%;max-height:320px;object-fit:contain;border-radius:10px;margin-top:10px">`:""}
  <label class="asset-check"><input type="checkbox" id="asApproved" ${asset.approved?"checked":""}><span>נכס מאושר</span></label>
  <div class="row"><button onclick="saveAsset(${asset.id})">שמירה</button><button class="danger" onclick="deleteAsset(${asset.id})">מחיקה</button></div>
  </div><div>
  ${isLockable ? `<div class="workspace-section"><div class="section-toolbar"><h3>${lockTitle}</h3>${isLocked ? `<button class="danger" onclick="unlockAsset(${asset.id})">פתיחת נעילה</button>` : ""}</div>
  <p class="meta">יש לאשר רפרנס אחד לפחות, לבחור אותו כ־Master ואז לנעול. רק נכס נעול יוכל להשתתף ביצירת שוט.</p>
  <div class="row"><button onclick="generateCharacterReference(${asset.id},'portrait')">Master</button>
  <button onclick="generateCharacterReference(${asset.id},'full_body')">וריאציה רחבה</button>
  <button onclick="generateCharacterReference(${asset.id},'three_quarter')">וריאציה ¾</button></div>
  <div class="reference-grid">${references.length ? references.map((r)=>`
    <div class="card ${asset.master_reference_id===r.id ? "approved" : ""}">
      <img src="/api/assets/${asset.id}/references/${r.id}/image" alt="${esc(r.view_type)}" style="width:100%;aspect-ratio:3/4;object-fit:cover;border-radius:10px" onerror="this.classList.add('image-error')">
      <div class="meta">${esc(r.view_type)} · ${esc(r.model)}${asset.master_reference_id===r.id ? " · MASTER" : ""}</div>
      <label class="asset-check"><input type="checkbox" ${r.approved ? "checked" : ""} onchange="setReferenceApproval(${asset.id},${r.id},this.checked)"><span>רפרנס מאושר</span></label>
      <div class="row"><a href="/api/assets/${asset.id}/references/${r.id}/image" target="_blank" rel="noopener">פתיחה</a>
      ${!isLocked && r.approved ? `<button onclick="lockAsset(${asset.id},${r.id},'${asset.asset_type}')">נעילה כ־Master</button>` : ""}</div>
    </div>`).join("") : "<p>טרם נוצרו רפרנסים.</p>"}</div>
  </div>` : ""}
  <div class="workspace-section" style="margin-top:15px"><h3>שוטים מקושרים</h3>
  ${asset.linked_shots.length?asset.linked_shots.map((s)=>`<div class="card"><div class="title">שוט ${s.shot_number}: ${esc(s.title)}</div><button onclick="openShot(${s.id})">פתיחת השוט</button></div>`).join(""):"<p>הנכס אינו משויך עדיין לשוטים.</p>"}
  </div></div></div>`);
}

async function setReferenceApproval(assetId, referenceId, approved) {
  try {
    await api(`/api/assets/${assetId}/references/${referenceId}/approval`, {
      method: "PUT",
      body: JSON.stringify({approved}),
    });
    await openAsset(assetId);
  } catch (error) {
    showError(error);
  }
}

async function lockAsset(assetId, referenceId, assetType) {
  if (!confirm(`לנעול את ${assetType} עם הרפרנס הזה כ־Master? שדות ה־Master יוגנו משינוי.`)) return;
  try {
    await api(`/api/assets/${assetId}/lock`, {
      method: "POST",
      body: JSON.stringify({master_reference_id: referenceId}),
    });
    await openAsset(assetId);
  } catch (error) {
    showError(error);
  }
}

async function unlockAsset(assetId) {
  if (!confirm("לפתוח את הנעילה? לאחר מכן ניתן יהיה לשנות את ה־Master והרפרנסים.")) return;
  try {
    await api(`/api/assets/${assetId}/unlock`, {method: "POST"});
    await openAsset(assetId);
  } catch (error) {
    showError(error);
  }
}

const lockCharacter = lockAsset;
const unlockCharacter = unlockAsset;
