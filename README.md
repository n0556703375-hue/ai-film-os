# AI Film OS v3 — „כתובת אפס”

מערכת מודולרית בעברית לניהול הפקת סרטי AI: Story Bible, סצנות, שוטים, פרומפטים, תוצאות מדיה ובקרת רציפות.

## יכולות

- סצנות המחוברות לשוטים, כולל סדר, סטטוס ומשך מצטבר.
- Shot Workspace מובנה: משך, סוג שוט, זווית, עדשה, תנועה, קומפוזיציה, פעולה, תאורה, צבע, אודיו ודיאלוג.
- היסטוריית גרסאות אוטומטית לפרומפט ול־Negative Prompt.
- תוצאות תמונה ווידאו ממוספרות, עם ספק, מודל, סטטוס ושיוך לגרסת פרומפט.
- Continuity QA מובנה: קטגוריה, חומרה, סטטוס, מצב צפוי, מצב שנמצא ופתרון.
- Story Bible לנכסים ושיוכם לשוטים.
- ממשק RTL רספונסיבי ו־API מודולרי.

השדרוג משתמש ב־SQLite migrations מצטברים בלבד. בהפעלה הראשונה מתווספים השדות והטבלאות החדשים בלי למחוק או לאפס נתונים קיימים.

## הפעלה

```bash
pip install -r requirements.txt
python run.py
```

פתחו `http://localhost:8000`.

## מבנה

```text
app/
├── api/
├── core/
├── database/
├── models/
├── repositories/
├── services/
├── static/
└── templates/
```

## בדיקות

```bash
python -m unittest discover -s tests -v
```

## יצירה אוטומטית באמצעות OpenAI ו־Magnific

ב־Shot Workspace נוספו שתי פעולות:

- **AI: שיפור פרומפט** — OpenAI משפר את פרומפט השוט עבור Magnific ושומר גרסה חדשה.
- **Magnific: יצירת תמונה** — שולח משימת Nano Banana Pro, עוקב אחריה עד להשלמה ושומר את קישור התמונה כתוצאת מדיה בשוט.

החיבורים קוראים סודות והגדרות מסביבת ההפעלה בלבד:

- `OPENAI_API_KEY` — לשיפור פרומפטים.
- `OPENAI_TEXT_MODEL` — ברירת מחדל: `gpt-5-mini`.
- `MAGNIFIC_API_KEY` — חובה ליצירת תמונות ב־Magnific.
- `MAGNIFIC_IMAGE_MODEL` — ברירת מחדל: `nano-banana-pro`.
- `MAGNIFIC_RESOLUTION` — ברירת מחדל: `2K`.

המפתחות אינם נשמרים במאגר. תוצאות Magnific נשמרות כקישורים חיצוניים ולכן אינן תלויות באחסון המקומי של Render.

## וידאו: Kling + Sync.so (Milestone B Gate 2)

לאחר אישור תמונת השוט, ה־worker יכול ליצור וידאו image-to-video דרך Kling ואופציונלית להוסיף lip-sync דרך Sync.so. בחירת הספק מתבצעת אוטומטית: אם `KLING_ACCESS_KEY` וגם `KLING_SECRET_KEY` מוגדרים, ה־worker משתמש ב־Kling; אחרת ספק הווידאו נשאר מנוטרל.

Kling מאמת עם זוג AccessKey/SecretKey שחותם JWT קצר־מועד (HS256) בכל בקשה — אין מפתח bearer ארוך־טווח. ה־SecretKey משמש לחתימה מקומית בלבד ואינו נשלח לרשת.

| משתנה סביבה | תפקיד |
|---|---|
| `KLING_ACCESS_KEY` | Kling AccessKey (מ־https://app.klingai.com). חובה כדי להפעיל את ספק הווידאו. |
| `KLING_SECRET_KEY` | Kling SecretKey — חותם את ה־JWT מקומית, לעולם אינו משודר. חובה. |
| `KLING_API_BASE` | דומיין ה־API. ברירת מחדל: `https://api-singapore.klingai.com`. |
| `KLING_DEFAULT_MODEL` | דגם ברירת מחדל כשאין התאמת פרופיל. ברירת מחדל: `kling-v2-master`. |
| `SYNC_API_KEY` | אופציונלי — מפעיל את שלב ה־lip-sync של Sync.so. |
| `SYNC_API_BASE` | דומיין ה־API של Sync.so. ברירת מחדל: `https://api.sync.so`. |
| `SYNC_DEFAULT_MODEL` | דגם Sync.so נתמך. ברירת מחדל: `sync-3`. |

עמידות ה־worker (Gate 2): מזהה משימת ה־Kling נשמר על שורת ה־job (`provider_task_id`) מיד לאחר השליחה. ניסיון חוזר או הפעלה מחדש של ה־worker ממשיך לבצע polling על אותה המשימה במקום לשלוח משימה כפולה (ומחויבת בנפרד). משימה שנתקעה במצב `running` בעקבות קריסה משוחזרת אוטומטית ל־`retrying` דרך `reclaim_stale_jobs`.

המפתחות נקראים מסביבת ההפעלה בלבד ואינם נשמרים במאגר. ראו `.env.example`. הערך: אין לבצע deploy אוטומטי — פריסת Render היא ידנית.

## וידאו: Seedance 2.0 via fal.ai (ספק ראשי) — ייצוב ה-vertical slice

הספק הראשי כיום הוא Seedance 2.0 דרך fal.ai (`FAL_API_KEY`); Kling נשאר כספק גיבוי (fallback) אם שני מפתחות ה-Kling מוגדרים ו-`FAL_API_KEY` ריק. ראו `get_video_provider()` ב-`app/services/video_provider.py`.

**זרימת הפקה מלאה:** העלאת תמונה (`POST /api/shots/{id}/media/upload`, multipart — לא הדבקת URL) → אישור תמונה → `GET /api/video-generation/shots/{id}/readiness` (בדיקה שאינה גובה תשלום) → יצירת וידאו → ה-worker הרקע (`app/background_worker.py`, thread יחיד בתוך תהליך ה-web — מתאים ל-Render free tier ללא worker service נפרד) שולח ל-Seedance ומאחסן את תוצאת ה-video_result.

**עמידות (mirrors Kling's Gate 2 guarantee):** `SeedanceProvider.submit()` רק שולח בקשה ל-fal.ai ומחזיר מזהה — הוא **אינו** חוסם. `provider_task_id` נשמר על ה-job מיד, לפני כל polling. `check_task()` היא בדיקת סטטוס בודדת ולא חוסמת. קריסה/הפעלה מחדש של ה-worker או כישלון בר-ניסיון-חוזר ממשיכים polling על אותה בקשת fal.ai ולעולם אינם שולחים בקשה כפולה (ומחויבת בנפרד). כישלונות מדווחים כקטגוריה יציבה ובטוחה (`SeedanceErrorCategory` — למשל `authentication_failed`, `source_image_unreachable`, `moderation_rejected`) ולא כטקסט חופשי מהספק; קטגוריות מסוימות (auth, moderation, קלט לא תקין) מסומנות non-retryable ולא צורכות ניסיונות חוזרים לשווא.

**✅ פתרון לחוסם השחרור — אחסון מדיה חיצוני (S3-compatible):** ל-Render free tier **אין** אפשרות דיסק מתמיד כלל (persistent disk דורש תוכנית בתשלום, Starter ומעלה). קובץ שנשמר תחת `GENERATED_MEDIA_PATH` (ברירת מחדל: תיקייה בתוך קוד האפליקציה עצמו) **נמחק בכל deploy/restart**, בעוד השורה ב-media_results ממשיכה להצביע עליו — כלומר וידאו/תמונה שהועלו יעלמו מבלי אזהרה, אלא אם מוגדר אחסון חיצוני.

`app/services/object_storage.py` מממש קליינט S3-compatible (חתימת AWS SigV4 ידנית מעל httpx, בלי תלות ב-boto3) שתומך ב-Cloudflare R2, AWS S3 ו-Backblaze B2 — כולם חושפים את אותו פרוטוקול. שתי נקודות הכתיבה היחידות של מדיה שנוצרת (`app/services/media_upload.py` — העלאת תמונה, ו-`app/services/video_persistence.py` — הורדת/שמירת וידאו מהספק) בודקות תחילה אם האחסון החיצוני מוגדר:

* **מוגדר** (כל 5 משתני `OBJECT_STORAGE_*` למטה) — הקובץ נכתב ישירות לבאקט ומוחזר URL ציבורי קבוע, ששורד deploy/restart.
* **לא מוגדר** — נופל אוטומטית לאחסון המקומי הקיים (fallback מלא, ללא שינוי התנהגות), עם אזהרה ברורה בלוג בכל כתיבה שהמדיה לא persistent במצב הזה.

ראו `.env.example` לרשימת המשתנים (`OBJECT_STORAGE_ENDPOINT`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ACCESS_KEY`, `OBJECT_STORAGE_SECRET_KEY`, `OBJECT_STORAGE_REGION`, `OBJECT_STORAGE_PUBLIC_URL_BASE`) ואת ההסבר לכל אחד. אף אחד מהם לא נשמר במאגר הנתונים — קונפיגורציית סביבה בלבד.

חלופה זמינה גם: שדרוג Render לתוכנית עם persistent disk (`render.yaml` כבר כולל בלוק `disk` מוכן, מכבה כברירת מחדל בתוכנית free) — אך אחסון אובייקטים חיצוני הוא הפתרון המומלץ, גם בתוכנית בתשלום, כי הוא לא תלוי בדיסק יחיד של אינסטנס אחד.

## ספק "מצב טיוטה" מקומי (ComfyUI) — וידאו + תמונה, ללא עלות

בנוסף לספקי הווידאו החיצוניים (Kling/Seedance) ולספק התמונה החיצוני (Magnific/Nano Banana Pro) קיים כעת **ספק שלישי, מקומי וחינמי**, לאיטרציה מהירה על שוט לפני שליחתו לספק החיצוני היקר. זו תוספת בלבד — הספקים החיצוניים לא נגעו בהם, וברירת המחדל של "מצב טיוטה" היא **כבויה**, כך שהתנהגות קיימת לא משתנה עד שמישהו מסמן את התיבה במפורש.

**איך זה עובד:** [ComfyUI](https://github.com/comfyanonymous/ComfyUI) רץ כשירות נפרד על מחשב מקומי (לא ב-Render, לא בענן) עם GPU — למשל תחנת עבודה עם RTX 5070 12GB. `COMFYUI_ENDPOINT` (למשל `http://localhost:8188`) מצביע לשם. כשמישהו מסמן "מצב טיוטה מקומי" במסך יצירת שוט (וידאו או תמונה), הבקשה מנותבת ל-ComfyUI במקום לספק החיצוני:

* **וידאו**: `app/services/providers/local_comfyui_provider.py` — תומך ב-**LTX-2.3** (כולל אודיו מסונכרן) ו-**Wan 2.2** (ללא אודיו). מממש בדיוק את אותו ממשק `submit()`/`check_task()` הקיים כבר עבור Kling/Seedance (`app/services/video_provider.py`), ואת אותה לולאת polling ב-`app/worker.py` — לא נוסף מנגנון חדש.
* **תמונה**: `app/services/providers/local_comfyui_image_provider.py` — תומך ב-**SDXL** ו-**Flux.1** (מכומת ל-Q4 כדי להיכנס ל-12GB VRAM). מממש את אותו pattern submit/poll שכבר קיים ב-`app/worker.py` עבור Magnific.
* שני הספקים חולקים לקוח HTTP משותף (`app/services/providers/comfyui_client.py`) שלא יוצא לאינטרנט הציבורי כלל — כל בקשה הולכת ל-`COMFYUI_ENDPOINT` בלבד.

**דרישה מקדימה — התקנה מקומית של ComfyUI:** זה **לא** מבוצע כחלק מה-repo הזה (ComfyUI עצמו לא נכנס ל-git). יש להתקין אותו בנפרד על המחשב עם ה-GPU, ולשמור שם גם את קבצי ה-workflow (JSON) שהאינטגרציה כאן טוענת דרך `COMFYUI_WORKFLOW_LTX_PATH` / `COMFYUI_WORKFLOW_WAN_PATH` / `COMFYUI_WORKFLOW_SDXL_PATH` / `COMFYUI_WORKFLOW_FLUX_PATH`. כל קובץ workflow חייב להיות "API format" export של ComfyUI, עם node-ים מסומנים בכותרת (`_meta.title`) בדיוק `AIFilmOS_Prompt` / `AIFilmOS_Image` / `AIFilmOS_Frames` / `AIFilmOS_Seed` — כך שהאינטגרציה יודעת אילו ערכים לעדכן לפני שליחה. ההסכם המלא מתועד ב-docstring של `comfyui_client.py`.

ראו `.env.example` לרשימת כל משתני ה-`COMFYUI_*`. כשה-`COMFYUI_ENDPOINT` ריק, מצב הטיוטה פשוט לא זמין — ניסיון להפעיל אותו מחזיר שגיאה ברורה, לא נופל בשקט לספק החיצוני (כדי לא לגבות בטעות דרך ספק בתשלום כשהכוונה הייתה טיוטה חינמית).

## בדיקת AI לעקביות זהות (Identity Drift) — תמונה + וידאו, אוטומטית

בדיקה אוטומטית (לא ידנית) שמשווה כל תמונה/וידאו שנוצר לשוט מול תמונת הרפרנס הנעולה (Master) של הדמויות המשויכות אליו, באמצעות OpenAI Vision (`OPENAI_VISION_MODEL`), ומחזירה ציון דמיון וזיהוי חריגות (למשל `different_person`, `age_shift`, `face_structure_changed`).

**מה תוקן כאן:** המנגנון היה קיים בקוד (endpoints, worker, אחסון תוצאה) אבל לא היה מחובר לשום דבר שמריץ אותו בפועל — התור נשאר ריק לתמיד כי שום דבר לא סימן פריט חדש כ"ממתין", ושום thread לא קרא לעבד אותו. עכשיו:

* **חיבור אוטומטי:** בכל פעם שנוצרת תוצאת מדיה (תמונה או וידאו) לשוט שיש לו דמות נעולה (`lock_status='locked'`), `create_media_result` מסמן אותה אוטומטית כ"ממתינה" (`app/repositories/shots.py`). ה-thread שכבר רץ ברקע לעיבוד תור המדיה (`app/background_worker.py`) מעבד גם פריטי זהות ממתינים — אין צורך בהרצה ידנית של סקריפט, כל עוד `OPENAI_API_KEY` מוגדר (אחרת הבדיקה פשוט נשארת ממתינה, לא נכשלת).
* **מקבילה לווידאו:** `app/services/video_identity_vision.py` מחלץ פריים מייצג מהווידאו שנוצר (`app/services/video_frame_extraction.py`, דרך ffmpeg מובנה ב-`imageio[ffmpeg]`, בלי תלות במערכת) וממיר אותו ל-`data:` URI — ואז מעביר אותו לאותה בדיקה בדיוק שהתמונות כבר עוברות (`evaluate_shot_identity`), ללא לוגיקת השוואה כפולה.
* ה-API הקיים (`GET /api/shots/identity-drift/pending`, `.../completed`, `POST .../requeue-stale` וכו') משרת כעת גם תמונה וגם וידאו יחד — כל פריט כולל `media_type` להבחנה.
* הרצה ידנית עדיין אפשרית דרך `scripts/process_identity_assessments.py` אם רוצים לעבד באופן חד-פעמי/מתוזמן מחוץ ל-thread הרקע.
* **Thread נפרד לבדיקות AI:** בדיקות ה-Identity Drift רצות עכשיו על thread רקע ייעודי, נפרד מה-thread שמעבד את תור יצירת המדיה (`app/background_worker.py::_identity_worker_loop`) — עדיין באותו תהליך/שירות Render יחיד (לא נוסף שירות worker נפרד), אבל קריאת OpenAI Vision איטית או תקועה כבר לא יכולה לעכב יצירת תמונה/וידאו חדשים, ולהפך.
* **נראות בממשק:** תג סטטוס ("ממתין לבדיקת AI" / "עברה בדיקת זהות" / "נחסם — סטיית זהות" וכו') מוצג ליד כל תוצאת מדיה בעמוד השוט הראשי (לא רק בפאנל התפעולי הנפרד), ואם הבדיקה תקועה "ממתינה" כי `OPENAI_API_KEY` לא מוגדר — מוצגת אזהרה מפורשת על כך (`GET /api/shots/identity-drift/status`).

## מילוי אוטומטי של נכסים לשוט (דמויות/לוקיישנים/אביזרים/לבוש)

עד עכשיו שיוך נכסים לשוט ("נכסים משויכים") היה ידני בלבד — סימון checkbox לכל נכס בנפרד. כפתור חדש "מילוי אוטומטי לפי הטקסט" (`POST /api/shots/{shot_id}/assets/autofill`) סורק את שדות הטקסט החופשי של השוט (פעולה, דיאלוג, הערות, מצלמה, קומפוזיציה, פרומפט וכו') ומחפש בהם את שמות הנכסים של הפרויקט — כולל התחשבות במילות יחס/יידוע עבריות שמתחברות ישירות למילה (כמו "בסכין", "האור", "למטבח").

* `app/services/shot_asset_autofill.py` — פונקציה טהורה, מבוססת התאמת מחרוזות (לא AI — אין תלות במפתח API, מיידי וחינמי).
* **Additive בלבד:** לעולם לא מסיר נכס ששויך ידנית, רק מוסיף התאמות חדשות. אם לא נמצאה אף התאמה חדשה — לא נשמר כלום.
* משמש כנקודת התחלה מהירה, לא תחליף לבדיקה ידנית — מומלץ לעבור על השיוך שנוצר ולתקן אם צריך.

## בדיקת AI לרציפות חזותית (Visual Continuity) — הרחבה של בדיקת ה-Continuity

בדיקת ה-Continuity הקיימת (`app/services/continuity.py`) היא כללית בלבד — משווה שמות דמויות/לוקיישנים/אביזרים בין שוטים סמוכים, בלי לנתח את התמונה בפועל. עכשיו יש גם שכבת AI אופציונלית שמשווה את הפריימים עצמם:

* `app/services/visual_continuity_vision.py` שולח את התמונה/פריים האחרון של השוט הנוכחי ושל השוט השכן (הקודם/הבא) ל-OpenAI Vision, ומבקש ציון רציפות (0–1) ודגלים כמו `wardrobe_changed`, `lighting_changed`, `framing_mismatch`.
* `app/services/shot_visual_continuity.py` מחבר את זה לנתונים אמיתיים — שולף את תוצאת המדיה האחרונה של כל שוט (ומחלץ פריים מווידאו במידת הצורך, באותו מנגנון של Identity Drift), וקורא לבדיקה. פועל Best-effort בלבד: מחזיר רשימה ריקה בלי לזרוק שגיאה אם אין `OPENAI_API_KEY`, אם לשוט אין עדיין מדיה, או אם קריאת ה-AI נכשלת.
* `GET /api/issues/shots/{shot_id}/continuity-preview` כולל כעת גם את הבעיות מבדיקת ה-AI (ניתן לכבות עם `?include_ai=false`), יחד עם בעיות הבדיקה הכללית הקיימת — אותו endpoint, אותה צורת תשובה.
