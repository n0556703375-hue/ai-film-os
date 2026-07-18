from contextlib import closing
from app.database.connection import get_connection

def list_scenes():
    with closing(get_connection()) as conn:
        rows = conn.execute("""
            SELECT sc.*,
              (SELECT COUNT(*) FROM shots s WHERE s.scene_id=sc.id) AS shot_count
            FROM scenes sc ORDER BY scene_number
        """).fetchall()
    return [dict(r) for r in rows]

def get_scene(scene_id: int):
    with closing(get_connection()) as conn:
        scene = conn.execute("SELECT * FROM scenes WHERE id=?", (scene_id,)).fetchone()
        if not scene:
            return None
        shots = conn.execute(
            "SELECT * FROM shots WHERE scene_id=? ORDER BY shot_number",
            (scene_id,)
        ).fetchall()
    result = dict(scene)
    result["shots"] = [dict(s) for s in shots]
    return result
