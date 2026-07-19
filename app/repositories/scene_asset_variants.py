from contextlib import closing

from app.database.connection import get_connection


ALLOWED_VARIANT_ASSET_TYPES = {"לוקיישן", "לבוש"}


def list_scene_variants(scene_id: int) -> list[dict]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT sav.*, a.name AS asset_name, a.asset_type, a.lock_status
            FROM scene_asset_variants sav
            JOIN assets a ON a.id=sav.asset_id
            WHERE sav.scene_id=?
            ORDER BY a.asset_type, a.name, sav.id
            """,
            (scene_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_scene_variant(scene_id: int, asset_id: int, data: dict) -> dict | None:
    with closing(get_connection()) as conn:
        scene = conn.execute("SELECT id,project_id FROM scenes WHERE id=?", (scene_id,)).fetchone()
        if not scene:
            return None
        asset = conn.execute(
            "SELECT id,project_id,asset_type,lock_status FROM assets WHERE id=?",
            (asset_id,),
        ).fetchone()
        if not asset:
            raise ValueError("הנכס אינו קיים.")
        if asset["project_id"] != scene["project_id"]:
            raise ValueError("הנכס והסצנה חייבים להשתייך לאותה הפקה.")
        if asset["asset_type"] not in ALLOWED_VARIANT_ASSET_TYPES:
            raise ValueError("וריאנטים ברמת סצנה נתמכים רק ללוקיישן וללבוש.")
        if asset["lock_status"] != "locked":
            raise ValueError("יש לנעול את נכס המקור לפני יצירת וריאנט סצנה.")

        conn.execute(
            """
            INSERT INTO scene_asset_variants
            (scene_id,asset_id,state_name,description,reference_url,visual_rules,updated_at)
            VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(scene_id,asset_id) DO UPDATE SET
              state_name=excluded.state_name,
              description=excluded.description,
              reference_url=excluded.reference_url,
              visual_rules=excluded.visual_rules,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                scene_id,
                asset_id,
                data["state_name"],
                data.get("description", ""),
                data.get("reference_url", ""),
                data.get("visual_rules", ""),
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT sav.*, a.name AS asset_name, a.asset_type, a.lock_status
            FROM scene_asset_variants sav
            JOIN assets a ON a.id=sav.asset_id
            WHERE sav.scene_id=? AND sav.asset_id=?
            """,
            (scene_id, asset_id),
        ).fetchone()
    return dict(row)
