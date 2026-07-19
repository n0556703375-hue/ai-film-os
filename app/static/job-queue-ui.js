const directGenerateWithOpenAI = window.generateWithOpenAI;

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
    await waitForMediaJob(shotId, data.job.id);
  } catch (error) {
    showError(error);
  }
};

async function waitForMediaJob(shotId, jobId) {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    const job = await api(`/api/jobs/${jobId}`);
    if (job.status === "completed") {
      const result = job.result || {};
      show(`<h2>תמונת השוט מוכנה</h2>
        ${result.url ? `<img src="${esc(result.url)}" alt="תוצאת שוט" style="max-width:100%;border-radius:12px">` : ""}
        <div class="row"><button onclick="openShot(${shotId})">חזרה לשוט</button></div>`);
      return;
    }
    if (job.status === "failed") {
      throw new Error(job.last_error || "יצירת התמונה נכשלה.");
    }
    $("modalContent").innerHTML = `<h2>יצירת התמונה בתור הרקע</h2>
      <p>סטטוס: ${esc(job.status)} · ניסיון ${Number(job.attempts || 0)} מתוך ${Number(job.max_attempts || 0)}</p>
      <p class="meta">אפשר לסגור את החלון; המשימה תמשיך ברקע.</p>`;
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
  show(`<h2>המשימה ממשיכה ברקע</h2>
    <p>אפשר לחזור לשוט ולבדוק את תוצאת המדיה מאוחר יותר.</p>
    <button onclick="openShot(${shotId})">חזרה לשוט</button>`);
}
