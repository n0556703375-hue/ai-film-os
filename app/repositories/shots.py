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

def _load_assets(conn, shot_id: int):
    return conn.execute("""
        SELECT a.* FROM assets a
        JOIN shot_assets sa ON sa.asset_id=a.id
        WHERE sa.shot_id=?
        ORDER BY a.asset_type,a.name
    """, (shot_id,)).fetchall()

def get_shot(shot_id: int):
    with closing(get_connection()) as conn:
        shot = conn.execute("""
            SELECT s.*, sc.scene_number, sc.title AS scene_title,
                   sc.story_goal, sc.emotion AS scene_emotion,
                   sc.conflict AS scene_conflict
            FROM shots s
            LEFT JOIN scenes sc ON sc.id=s.scene_id
            WHERE s.id=?
        """, (shot_id,)).fetchone()
        if not shot:
            return None

        assets = _load_assets(conn, shot_id)

        previous = conn.execute("""
            SELECT id,shot_number,title,shot_type,lighting,mood
            FROM shots
            WHERE scene_id=? AND shot_number<?
            ORDER BY shot_number DESC
            LIMIT 1
        """, (shot["scene_id"], shot["shot_number"])).fetchone()

        previous_assets = _load_assets(conn, previous["id"]) if previous else []

        versions = conn.execute("""
            SELECT id,version,prompt,created_at
            FROM prompt_versions
            WHERE shot_id=?
            ORDER BY version DESC
            LIMIT 10
        """, (shot_id,)).fetchall()

    result = dict(shot)
    result["assets"] = [dict(a) for a in assets]
    result["prompt_versions"] = [dict(v) for v in versions]
    result["previous_shot"] = dict(previous) if previous else None
    if result["previous_shot"] is not None:
        result["previous_shot"]["assets"] = [dict(a) for a in previous_assets]
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
        valid_ids = set()
        if asset_ids:
            placeholders = ",".join("?" for _ in asset_ids)
            valid_ids = {
                row[0] for row in conn.execute(
                    f"SELECT id FROM assets WHERE id IN ({placeholders})",
                    asset_ids
                ).fetchall()
            }
        if len(valid_ids) != len(set(asset_ids)):
            raise ValueError("אחד הנכסים שנבחרו אינו קיים.")

        conn.execute("DELETE FROM shot_assets WHERE shot_id=?", (shot_id,))
        conn.executemany(
            "INSERT INTO shot_assets (shot_id,asset_id) VALUES (?,?)",
            [(shot_id, asset_id) for asset_id in asset_ids]
        )
        conn.commit()

def save_prompt_version(shot_id: int, prompt: str):
    with closing(get_connection()) as conn:
        current = conn.execute(
            "SELECT COALESCE(MAX(version),0) FROM prompt_versions WHERE shot_id=?",
            (shot_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO prompt_versions (shot_id,version,prompt) VALUES (?,?,?)",
            (shot_id, current + 1, prompt)
        )
        conn.commit()
