// Adds the real image-upload workflow (file picker, not paste-a-URL) as the
// primary way to add a shot's source image, and gates the "יצירת וידאו"
// button on the backend readiness check so a doomed/paid submission never
// happens. Loaded after app.js, shot-approval.js and job-queue-ui.js, and
// follows their existing pattern of wrapping window.openShot.

const READINESS_REASON_LABELS = {
  no_approved_image: "יש לאשר תמונת שוט תחילה",
  provider_not_configured: "ספק הווידאו אינו מוגדר",
  worker_not_alive: "ה-worker אינו פעיל כרגע",
};

function readinessReasonLabel(reason) {
  if (READINESS_REASON_LABELS[reason]) return READINESS_REASON_LABELS[reason];
  if (reason.startsWith("image_not_publicly_accessible")) {
    return "התמונה אינה נגישה באופן ציבורי לספק הווידאו";
  }
  return reason;
}

// --- Upload button in the shot workspace media toolbar -------------------

const baseOpenShotForUpload = window.openShot;
window.openShot = async function openShotWithUpload(shotId) {
  await baseOpenShotForUpload(shotId);
  appendUploadControl(shotId);
  await annotateVideoButtonWithReadiness(shotId);
};

function appendUploadControl(shotId) {
  const content = $("modalContent");
  if (!content || content.querySelector("[data-upload-control]")) return;
  const mediaHeading = [...content.querySelectorAll("h3")]
    .find((heading) => heading.textContent.includes("תוצאות תמונה ווידאו"));
  const toolbar = mediaHeading && mediaHeading.closest(".section-toolbar");
  if (!toolbar) return;

  const label = document.createElement("label");
  label.className = "secondary";
  label.dataset.uploadControl = "true";
  label.style.cursor = "pointer";
  label.style.display = "inline-block";
  label.textContent = "העלאת תמונה מהמחשב";
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/png,image/jpeg,image/webp";
  input.style.display = "none";
  input.onchange = () => {
    const file = input.files[0];
    input.value = "";
    if (file) uploadShotImage(shotId, file);
  };
  label.appendChild(input);
  toolbar.appendChild(label);
}

async function uploadShotImage(shotId, file) {
  const objectUrl = URL.createObjectURL(file);
  show(`<h2>מעלה תמונה…</h2>
    <img src="${objectUrl}" alt="תצוגה מקדימה" style="max-width:100%;border-radius:12px">
    <p class="meta">${esc(file.name)} · ${(file.size / 1024).toFixed(0)} KB</p>`);
  const formData = new FormData();
  formData.append("file", file);
  try {
    const response = await fetch(`/api/shots/${shotId}/media/upload`, {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "העלאת התמונה נכשלה.");
    }
    await openShot(shotId);
  } catch (error) {
    showError(error);
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

// --- Readiness gate on the Generate Video button --------------------------

async function annotateVideoButtonWithReadiness(shotId) {
  const button = document.querySelector("[data-video-generation-button]");
  if (!button) return;
  try {
    const readiness = await api(`/api/video-generation/shots/${shotId}/readiness`);
    button.disabled = !readiness.ready;
    button.title = readiness.ready
      ? ""
      : readiness.reasons.map(readinessReasonLabel).join(" · ");
  } catch (error) {
    // Fail open on the readiness check itself — the click-time gate below
    // and the existing backend validation still protect against a bad
    // submission; we just lose the proactive disabled state.
    console.error("Readiness check failed", error);
  }
}

const baseShowVideoGenerationForm = window.showVideoGenerationForm;
window.showVideoGenerationForm = async function showVideoGenerationFormWithReadiness(shotId) {
  show("<h2>בודק מוכנות ליצירת וידאו…</h2>");
  let readiness;
  try {
    readiness = await api(`/api/video-generation/shots/${shotId}/readiness`);
  } catch (error) {
    showError(error);
    return;
  }
  const checklist = `
    <ul>
      <li>${readiness.approved_image ? "✓" : "✗"} תמונה מאושרת</li>
      <li>${readiness.image_publicly_accessible ? "✓" : "✗"} התמונה נגישה ציבורית</li>
      <li>${readiness.provider_configured ? "✓" : "✗"} ספק וידאו מוגדר</li>
      <li>${readiness.worker_alive ? "✓" : "✗"} ה-worker פעיל</li>
    </ul>`;
  if (!readiness.ready) {
    show(`<h2>לא ניתן ליצור וידאו כרגע</h2>${checklist}
      <button class="secondary" onclick="openShot(${shotId})">חזרה לשוט</button>`);
    return;
  }
  baseShowVideoGenerationForm(shotId);
};

// --- Friendlier failure messages (categories are already sanitized — see
// worker.py / seedance_provider.py — so showing them is safe; this only
// improves readability). --------------------------------------------------

const FAILURE_CATEGORY_LABELS = {
  authentication_failed: "בעיית הרשאה מול ספק הווידאו. יש לבדוק את הגדרות המערכת.",
  invalid_input: "פרטי הבקשה אינם תקינים עבור ספק הווידאו.",
  source_image_unreachable: "לא ניתן היה להוריד את תמונת השוט. יש להעלות את התמונה מחדש ולנסות שוב.",
  insufficient_credits: "אין מספיק קרדיט אצל ספק הווידאו.",
  rate_limited: "ספק הווידאו עמוס כרגע. ניתן לנסות שוב בעוד מספר דקות.",
  moderation_rejected: "התוכן נדחה על ידי בדיקת התוכן של ספק הווידאו.",
  provider_timeout: "ספק הווידאו לא הגיב בזמן. ניתן לנסות שוב.",
  provider_failed: "ספק הווידאו נתקל בשגיאה. ניתן לנסות שוב.",
  invalid_provider_response: "ספק הווידאו החזיר תגובה לא צפויה.",
  video_persistence_failed: "הווידאו נוצר, אך שמירת הקובץ במערכת נכשלה. ניתן לנסות שוב.",
};

function friendlyFailureMessage(rawError) {
  const text = String(rawError || "");
  for (const [category, label] of Object.entries(FAILURE_CATEGORY_LABELS)) {
    if (text.includes(category)) return label;
  }
  return text || "יצירת הווידאו נכשלה.";
}

const baseWaitForMediaJob = window.waitForMediaJob;
window.waitForMediaJob = async function waitForMediaJobWithFriendlyErrors(shotId, jobId, mediaLabel) {
  try {
    await baseWaitForMediaJob(shotId, jobId, mediaLabel);
  } catch (error) {
    error.message = friendlyFailureMessage(error.message);
    throw error;
  }
};
