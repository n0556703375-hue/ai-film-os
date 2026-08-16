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
