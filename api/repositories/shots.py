from contextlib import closing
from app.database.connection import get_connection

def list_shots():
    with closing(get_connection()) as conn:
        rows = conn.execute("""
            SELECT s.*,
              (SELECT COUNT(*) FROM shot_assets sa WHERE sa.shot_id=s.id) AS asset_count,
              sc.scene_number
            FROM shots s
            LEFT JOIN scenes sc ON sc.id=s.scene_id
            ORDER BY s.shot_number
        """).fetchall()
    return [dict(r) for r in rows]

def get_shot(shot_id: int):
    with closing(get_connection()) as conn:
        shot = conn.execute("SELECT * FROM shots WHERE id=?", (shot_id,)).fetchone()
        if not shot:
            return None
        assets = conn.execute("""
            SELECT a.* FROM assets a
            JOIN shot_assets sa ON sa.asset_id=a.id
            WHERE sa.shot_id=?
            ORDER BY a.asset_type,a.name
        """, (shot_id,)).fetchall()
    result = dict(shot)
    result["assets"] = [dict(a) for a in assets]
    return result

def update_shot(shot_id: int, fields: dict):
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM shots WHERE id=?", (shot_id,)).fetchone():
            return None
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(
            f"UPDATE shots SET {sets},updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [*fields.values(), shot_id]
        )
        conn.commit()
    return get_shot(shot_id)

def set_shot_assets(shot_id: int, asset_ids: list[int]):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM shot_assets WHERE shot_id=?", (shot_id,))
        conn.executemany(
            "INSERT INTO shot_assets (shot_id,asset_id) VALUES (?,?)",
            [(shot_id, asset_id) for asset_id in asset_ids]
        )
        conn.commit()
