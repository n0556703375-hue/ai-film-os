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
