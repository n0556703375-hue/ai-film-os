from contextlib import closing
from app.database.connection import get_connection

def create_generated_shots(scene_id: int, shots: list[dict], replace_existing: bool = False):
    allowed = {"title", "shot_type", "duration_seconds", "action", "camera", "camera_angle",
               "composition", "lens", "lighting", "movement", "mood", "color_palette", "dialogue"}
    with closing(get_connection()) as conn:
        scene = conn.execute("SELECT * FROM scenes WHERE id=?", (scene_id,)).fetchone()
        if not scene:
            return None
        existing = conn.execute("SELECT COUNT(*) FROM shots WHERE scene_id=?", (scene_id,)).fetchone()[0]
        if existing and not replace_existing:
            raise ValueError("כבר קיימים שוטים בסצנה. יש לבחור החלפה מפורשת.")
        if replace_existing:
            conn.execute("DELETE FROM shots WHERE scene_id=?", (scene_id,))
        valid_assets = {row[0] for row in conn.execute(
            "SELECT id FROM assets WHERE project_id=?", (scene["project_id"],)
        ).fetchall()}
        for number, shot in enumerate(shots, 1):
            fields = {key: shot.get(key) for key in allowed if shot.get(key) is not None}
            fields.update({"project_id": scene["project_id"], "scene_id": scene_id,
                           "shot_number": number, "status": "מתוכנן",
                           "title": shot.get("title") or f"שוט {number}"})
            names = ",".join(fields)
            cur = conn.execute(f"INSERT INTO shots ({names}) VALUES ({','.join('?' for _ in fields)})",
                               list(fields.values()))
            ids = [int(v) for v in shot.get("asset_ids", []) if int(v) in valid_assets]
            conn.executemany("INSERT OR IGNORE INTO shot_assets (shot_id,asset_id) VALUES (?,?)",
                             [(cur.lastrowid, asset_id) for asset_id in ids])
        conn.commit()
    return get_scene(scene_id)

def list_scenes(project_id: int | None = None):
    query = """
        SELECT sc.*,
          (SELECT COUNT(*) FROM shots s WHERE s.scene_id=sc.id) AS shot_count,
          (SELECT COALESCE(SUM(duration_seconds),0) FROM shots s WHERE s.scene_id=sc.id) AS duration_seconds
        FROM scenes sc
    """
    params: tuple = ()
    if project_id is not None:
        query += " WHERE sc.project_id=?"
        params = (project_id,)
    query += " ORDER BY scene_number"
    with closing(get_connection()) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

def get_scene(scene_id: int):
    with closing(get_connection()) as conn:
        scene = conn.execute("SELECT * FROM scenes WHERE id=?", (scene_id,)).fetchone()
        if not scene:
            return None
        shots = conn.execute("""
            SELECT s.*,
              (SELECT COUNT(*) FROM shot_assets sa WHERE sa.shot_id=s.id) AS asset_count
            FROM shots s WHERE s.scene_id=? ORDER BY shot_number
        """, (scene_id,)).fetchall()
    result = dict(scene)
    result["shots"] = [dict(s) for s in shots]
    return result

def update_scene(scene_id: int, fields: dict):
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM scenes WHERE id=?", (scene_id,)).fetchone():
            return None
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(
            f"UPDATE scenes SET {sets},updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [*fields.values(), scene_id]
        )
        conn.commit()
    return get_scene(scene_id)

def create_scene(data: dict):
    data = dict(data)
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (data["project_id"],)).fetchone():
            raise ValueError("הפרויקט אינו קיים.")
        names = ",".join(data)
        placeholders = ",".join("?" for _ in data)
        cur = conn.execute(
            f"INSERT INTO scenes ({names}) VALUES ({placeholders})",
            list(data.values()),
        )
        conn.commit()
    return get_scene(cur.lastrowid)
