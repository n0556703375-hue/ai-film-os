SHOT_TITLES = [
    "מרום בלילה",
    "הרכבת הלבנה",
    "עיר שמזהה הכול",
    "ליאורה באטלס",
    "אי־התאמת שכבה",
    "הדלת מסרבת",
    "כתובת אפס",
    "דלת השירות",
    "יורדות מתחת לעיר",
    "חשיפת רובע הדרום",
    "נוכחות אפס",
    "ברכה סופרת",
    "הילה לא משויכת",
    "תמר והציר הלבן",
    "06:00",
    "פינוי בטיחותי",
    "מיכל רצה",
    "שלוש חזיתות",
    "הרכבת הריקה",
    "לא מחכה לזה",
]

ASSETS = [
    (
        "דמות",
        "ליאורה שחר",
        "חוקרת מפות בת 26; מדויקת, ערנית ומאופקת.",
        "חליפת עבודה עתידנית צנועה בתכלת־לבן, צווארון גבוה.",
    ),
    (
        "דמות",
        "מיכל שחר",
        "בת 17; מהירה, רגישה ונחושה.",
        "לבוש עתידני צנוע ופשוט יותר מליאורה.",
    ),
    (
        "דמות",
        "תמר ארבל",
        "מתכננת הציר הלבן; סמכותית ושקולה.",
        "לבוש מקצועי נקי ומובנה.",
    ),
    (
        "לוקיישן",
        "מרום",
        "עיר עתידנית ריאליסטית, מסודרת וסטרילית.",
        "לבן־כחול, כסף מאט, אור קר ונקי.",
    ),
    (
        "לוקיישן",
        "רובע הדרום",
        "רובע חי שאינו מזוהה במערכת.",
        "חם, צפוף, אישי ואנושי.",
    ),
    (
        "לוקיישן",
        "מרכז האטלס",
        "מרכז מיפוי ובקרה עתידני.",
        "משטחים לבנים, שכבות מידע עדינות, ללא ניאון.",
    ),
    (
        "אביזר",
        "סורק פרק־יד",
        "כלי עבודה דק של ליאורה לבדיקת שכבות וכתובות.",
        "לבן־כסוף, מסך כחול עדין.",
    ),
    (
        "אביזר",
        "העותק החתום",
        "מנגנון חד־פעמי שמעניק חלון פעולה קצר.",
        "אובייקט קטן, רשמי ומוגן.",
    ),
]


def seed_database(conn):
    project_count = conn.execute(
        "SELECT COUNT(*) FROM projects"
    ).fetchone()[0]

    if project_count == 0:
        conn.execute(
            """
            INSERT INTO projects (
                name,
                description,
                visual_style,
                rules
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "כתובת אפס",
                "מותחן עתידני־ריאליסטי נשי בשנת 2194 בעיר מרום.",
                (
                    "מרום לבן־כחול, נקי, קר וסטרילי; "
                    "רובע הדרום חם, אישי וצפוף."
                ),
                (
                    "נשים ונערות בלבד; לבוש צנוע; "
                    "ללא רומנטיקה וללא אלימות גרפית."
                ),
            ),
        )

    project_id = conn.execute(
        "SELECT id FROM projects ORDER BY id LIMIT 1"
    ).fetchone()[0]

    scene_count = conn.execute(
        "SELECT COUNT(*) FROM scenes"
    ).fetchone()[0]

    if scene_count == 0:
        for scene_number in range(1, 6):
            conn.execute(
                """
                INSERT INTO scenes (
                    project_id,
                    scene_number,
                    title
                )
                VALUES (?, ?, ?)
                """,
                (
                    project_id,
                    scene_number,
                    f"סצנה {scene_number}",
                ),
            )

    shot_count = conn.execute(
        "SELECT COUNT(*) FROM shots"
    ).fetchone()[0]

    if shot_count == 0:
        scene_ids = [
            row[0]
            for row in conn.execute(
                """
                SELECT id
                FROM scenes
                ORDER BY scene_number
                """
            ).fetchall()
        ]

        for shot_number, title in enumerate(
            SHOT_TITLES,
            start=1,
        ):
            scene_index = min(
                (shot_number - 1) // 4,
                len(scene_ids) - 1,
            )

            conn.execute(
                """
                INSERT INTO shots (
                    project_id,
                    scene_id,
                    shot_number,
                    title
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    project_id,
                    scene_ids[scene_index],
                    shot_number,
                    title,
                ),
            )

    asset_count = conn.execute(
        "SELECT COUNT(*) FROM assets"
    ).fetchone()[0]

    if asset_count == 0:
        for (
            asset_type,
            name,
            description,
            visual_rules,
        ) in ASSETS:
            conn.execute(
                """
                INSERT INTO assets (
                    project_id,
                    asset_type,
                    name,
                    description,
                    visual_rules
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    asset_type,
                    name,
                    description,
                    visual_rules,
                ),
            )
