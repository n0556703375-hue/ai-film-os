const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",""":"&quot;","'":"&#39;"}[c]));
async function api(url,opts={}){const r=await fetch(url,{headers:{"Content-Type":"application/json"},...opts});const d=await r.json();if(!r.ok)throw Error(d.detail||"שגיאה");return d}

document.querySelectorAll("nav button").forEach(btn=>btn.onclick=()=>{
  document.querySelectorAll(".panel").forEach(p=>p.classList.remove("active"));
  $(btn.dataset.tab).classList.add("active");
  loaders[btn.dataset.tab]();
});

async function loadDashboard(){
  const d=await api("/api/dashboard");
  $("dashboard").innerHTML=`<div class="grid">
    <div class="card"><div class="meta">שוטים</div><div class="stat">${d.shots_total}</div></div>
    <div class="card"><div class="meta">סצנות</div><div class="stat">${d.scenes_total}</div></div>
    <div class="card"><div class="meta">נכסים</div><div class="stat">${d.assets_total}</div></div>
    <div class="card"><div class="meta">בעיות פתוחות</div><div class="stat">${d.open_issues}</div></div>
  </div>`;
}
async function loadScenes(){
  const rows=await api("/api/scenes");
  $("scenes").innerHTML=`<div class=grid>${rows.map(s=>`<div class=card><span class=badge>סצנה ${s.scene_number}</span><div class=title>${esc(s.title)}</div><div class=meta>${s.shot_count} שוטים</div><button onclick="openScene(${s.id})">פתיחה</button></div>`).join("")}</div>`;
}
async function openScene(id){
  const s=await api(`/api/scenes/${id}`);
  show(`<h2>סצנה ${s.scene_number}: ${esc(s.title)}</h2><p>${esc(s.story_goal||"טרם הוגדרה מטרת סצנה")}</p><div class=grid>${s.shots.map(x=>`<div class=card><div class=title>${x.shot_number}. ${esc(x.title)}</div><div class=meta>${esc(x.status)}</div></div>`).join("")}</div>`);
}
async function loadShots(){
  const rows=await api("/api/shots");
  $("shots").innerHTML=`<div class=grid>${rows.map(s=>`<div class=card><div class=meta>שוט ${s.shot_number} · סצנה ${s.scene_number||"-"} · ${s.asset_count} נכסים</div><div class=title>${esc(s.title)}</div><span class=badge>${esc(s.status)}</span><div class=row><button onclick="makePrompt(${s.id})">בניית פרומפט</button><button onclick="checkContinuity(${s.id})">בדיקת רציפות</button></div></div>`).join("")}</div>`;
}
async function makePrompt(id){const d=await api(`/api/shots/${id}/prompt`,{method:"POST"});show(`<h2>פרומפט</h2><pre>${esc(d.prompt)}</pre>`)}
async function checkContinuity(id){const d=await api(`/api/shots/${id}/continuity`,{method:"POST"});show(`<h2>בדיקת רציפות</h2>${d.issues.length?d.issues.map(i=>`<div class=card><b>${esc(i.severity)}</b><p>${esc(i.message)}</p></div>`).join(""):"<p>לא נמצאו בעיות.</p>"}`)}
async function loadAssets(){
  const rows=await api("/api/assets");
  $("assets").innerHTML=`<div class=grid>${rows.map(a=>`<div class=card><span class=badge>${esc(a.asset_type)}</span><div class=title>${esc(a.name)}</div><p>${esc(a.description)}</p><div class=meta>${esc(a.visual_rules)}</div></div>`).join("")}</div>`;
}
function show(html){$("modalContent").innerHTML=html;$("modal").style.display="flex"}
function closeModal(){$("modal").style.display="none"}
const loaders={dashboard:loadDashboard,scenes:loadScenes,shots:loadShots,assets:loadAssets};
loadDashboard();
