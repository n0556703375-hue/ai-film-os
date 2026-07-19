const directGenerateWithOpenAI = window.generateWithOpenAI;
const baseOpenShot = window.openShot;

window.generateWithOpenAI = async function generateWithQueuedMedia(shotId, mediaType) {
  if (mediaType !== "image") {
    return directGenerateWithOpenAI(shotId, mediaType);
  }
  if (!confirm("ליצור תמונה חדשה? הפעולה משתמשת בקרדיט API ותתבצע בתור הרקע.")) return;

  show("<h2>הוספת יצירת תמונה לתור</h2><p>הבקשה נשמרת ותמשיך גם אם החלון ייסגר.</p>");
  try {
    const data = await api(`/api/generation/shots/${shotId}/queue`, {
      method: "POST",
      body: JSON.stringify({
        media_type: "image",
        instructions: "",
        size: "1536x1024",
        quality: "medium",
      }),
    });
    await waitForMediaJob(shotId, data.job.id, "תמונה");
  } catch (error) {
    showError(error);
  }
};

window.openShot = async function openShotWithVideoControls(shotId) {
  await baseOpenShot(shotId);
  const content = $("modalContent");
  if (!content || content.querySelector("[data-video-generation-button]")) return;
  const mediaHeading = [...content.querySelectorAll("h3")]
    .find((heading) => heading.textContent.includes("תוצאות תמונה ווידאו"));
  const toolbar = mediaHeading && mediaHeading.closest(".section-toolbar");
  if (!toolbar) return;

  const button = document.createElement("button");
  button.className = "secondary";
  button.dataset.videoGenerationButton = "true";
  button.textContent = "יצירת וידאו";
  button.onclick = () => showVideoGenerationForm(shotId);
  toolbar.appendChild(button);
};

function showVideoGenerationForm(shotId) {
  show(`<h2>הגדרות יצירת וידאו</h2>
    <p class="meta">נדרשת תמונת שוט מאושרת. שליחת המשימה עשויה להשתמש בקרדיט API לאחר חיבור ספק.</p>
    <div class="form-grid">
      <div><label>משך בשניות</label><input id="videoDuration" type="number" min="1" max="30" step="0.5" value="5"></div>
      <div><label>יחס תמונה</label><select id="videoAspect"><option>16:9</option><option>9:16</option><option>1:1</option></select></div>
      <div><label>מצב אודיו</label><select id="videoAudio"><option value="none">ללא</option><option value="ambient">אווירה</option><option value="dialogue">דיאלוג</option><option value="music">מוזיקה</option></select></div>
      <div><label>העדפת מודל</label><select id="videoModel"><option value="auto">אוטומטי</option><option value="cinematic">קולנועי</option><option value="fast">מהיר</option><option value="high_fidelity">איכות גבוהה</option></select></div>
      <div class="wide"><label>תנועת מצלמה</label><textarea id="videoMotion" placeholder="למשל: slow dolly in, subtle handheld"></textarea></div>
      <div class="wide"><label>הוראות נוספות</label><textarea id="videoInstructions" placeholder="שמירת זהות, תנועה רצויה, מגבלות רציפות"></textarea></div>
    </div>
    <button onclick="queueVideoGeneration(${shotId})">הוספה לתור הווידאו</button>
    <button class="secondary" onclick="openShot(${shotId})">ביטול</button>`);
}

async function queueVideoGeneration(shotId) {
  if (!confirm("להוסיף יצירת וידאו לתור? לאחר חיבור ספק הפעולה עשויה להשתמש בקרדיט API.")) return;
  try {
    const data = await api(`/api/video-generation/shots/${shotId}/queue`, {
      method: "POST",
      body: JSON.stringify({
        duration_seconds: Number($("videoDuration").value),
        camera_motion: $("videoMotion").value,
        audio_mode: $("videoAudio").value,
        aspect_ratio: $("videoAspect").value,
        model_hint: $("videoModel").value,
        instructions: $("videoInstructions").value,
      }),
    });
    show("<h2>משימת הווידאו נוספה לתור</h2><p>המשימה נשמרה ותמשיך ברקע.</p>");
    await waitForMediaJob(shotId, data.job.id, "וידאו");
  } catch (error) {
    showError(error);
  }
}

async function waitForMediaJob(shotId, jobId, mediaLabel = "מדיה") {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    const job = await api(`/api/jobs/${jobId}`);
    if (job.status === "completed") {
      const result = job.result || {};
      show(`<h2>${mediaLabel} השוט מוכן</h2>
        ${mediaLabel === "תמונה" && result.url ? `<img src="${esc(result.url)}" alt="תוצאת שוט" style="max-width:100%;border-radius:12px">` : ""}
        ${mediaLabel === "וידאו" && result.url ? `<video src="${esc(result.url)}" controls style="max-width:100%;border-radius:12px"></video>` : ""}
        <div class="row"><button onclick="openShot(${shotId})">חזרה לשוט</button></div>`);
      return;
    }
    if (job.status === "failed") {
      throw new Error(job.last_error || `יצירת ${mediaLabel} נכשלה.`);
    }
    $("modalContent").innerHTML = `<h2>יצירת ${mediaLabel} בתור הרקע</h2>
      <p>סטטוס: ${esc(job.status)} · ניסיון ${Number(job.attempts || 0)} מתוך ${Number(job.max_attempts || 0)}</p>
      <p class="meta">אפשר לסגור את החלון; המשימה תמשיך ברקע.</p>`;
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
  show(`<h2>המשימה ממשיכה ברקע</h2>
    <p>אפשר לחזור לשוט ולבדוק את תוצאת המדיה מאוחר יותר.</p>
    <button onclick="openShot(${shotId})">חזרה לשוט</button>`);
}
