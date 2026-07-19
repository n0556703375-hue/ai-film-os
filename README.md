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
- **Magnific: יצירת תמונה** — שולח משימת Mystic, עוקב אחריה עד להשלמה ושומר את קישור התמונה כתוצאת מדיה בשוט.

החיבורים קוראים סודות והגדרות מסביבת ההפעלה בלבד:

- `OPENAI_API_KEY` — לשיפור פרומפטים.
- `OPENAI_TEXT_MODEL` — ברירת מחדל: `gpt-5-mini`.
- `MAGNIFIC_API_KEY` — חובה ליצירת תמונות ב־Magnific.
- `MAGNIFIC_IMAGE_MODEL` — ברירת מחדל: `realism`.
- `MAGNIFIC_RESOLUTION` — ברירת מחדל: `2k`.
- `MAGNIFIC_ADHERENCE`, `MAGNIFIC_HDR`, `MAGNIFIC_CREATIVE_DETAILING` — שליטה באופי היצירה.

המפתחות אינם נשמרים במאגר. תוצאות Magnific נשמרות כקישורים חיצוניים ולכן אינן תלויות באחסון המקומי של Render. חיבור הווידאו יופעל בהמשך באמצעות API הווידאו של Magnific.
