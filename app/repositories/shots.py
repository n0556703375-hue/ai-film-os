import json
from contextlib import closing
from app.database.connection import get_connection

def list_shots(project_id: int | None = None):
    query = """
        SELECT s.*,
          (SELECT COUNT(*) FROM shot_assets sa WHERE sa.shot_id=s.id) AS asset_count,
          sc.scene_number
        FROM shots s
        LEFT JOIN scenes sc ON sc.id=s.scene_id
    """
    params: tuple = ()
    if project_id is not None:
        query += " WHERE s.project_id=?"
        params = (project_id,)
    query += " ORDER BY s.shot_number"
    with closing(get_connection()) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

def _load_assets(conn, shot_id: int):
    rows = conn.execute("""
        SELECT a.* FROM assets a
        JOIN shot_assets sa ON sa.asset_id=a.id
        WHERE sa.shot_id=?
        ORDER BY a.asset_type,a.name
    """, (shot_id,)).fetchall()
    result = []
    for row in rows:
        asset = dict(row)
        refs = conn.execute("SELECT url FROM asset_reference_images WHERE asset_id=? ORDER BY id DESC",
                            (asset["id"],)).fetchall()
        asset["reference_images"] = [r["url"] for r in refs]
        result.append(asset)
    return result

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
            SELECT id,version,prompt,negative_prompt,source,created_at
            FROM prompt_versions
            WHERE shot_id=?
            ORDER BY version DESC
            LIMIT 10
        """, (shot_id,)).fetchall()

        media = conn.execute("""
            SELECT * FROM media_results
            WHERE shot_id=?
            ORDER BY created_at DESC,id DESC
        """, (shot_id,)).fetchall()

    result = dict(shot)
    result["assets"] = assets
    result["prompt_versions"] = [dict(v) for v in versions]
    result["media_results"] = [
        {**dict(item), "metadata": json.loads(item["metadata_json"] or "{}")}
        for item in media
    ]
    result["previous_shot"] = dict(previous) if previous else None
    if result["previous_shot"] is not None:
        result["previous_shot"]["assets"] = previous_assets
    return result

def update_shot(shot_id: int, fields: dict):
    with closing(get_connection()) as conn:
        previous = conn.execute("SELECT * FROM shots WHERE id=?", (shot_id,)).fetchone()
        if not previous:
            return None
        if "scene_id" in fields and fields["scene_id"] is not None:
            if not conn.execute("SELECT 1 FROM scenes WHERE id=?", (fields["scene_id"],)).fetchone():
                raise ValueError("הסצנה שנבחרה אינה קיימת.")
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(
            f"UPDATE shots SET {sets},updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [*fields.values(), shot_id]
        )
        if "prompt" in fields or "negative_prompt" in fields:
            prompt = fields.get("prompt", previous["prompt"])
            negative = fields.get("negative_prompt", previous["negative_prompt"])
            _save_prompt_version(conn, shot_id, prompt, negative, "manual")
        conn.commit()
    return get_shot(shot_id)

def create_shot(data: dict):
    data = dict(data)
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (data["project_id"],)).fetchone():
            raise ValueError("הפרויקט אינו קיים.")
        if not conn.execute("SELECT 1 FROM scenes WHERE id=?", (data["scene_id"],)).fetchone():
            raise ValueError("הסצנה שנבחרה אינה קיימת.")
        names = ",".join(data)
        placeholders = ",".join("?" for _ in data)
        cur = conn.execute(
            f"INSERT INTO shots ({names}) VALUES ({placeholders})",
            list(data.values()),
        )
        if data.get("prompt"):
            _save_prompt_version(
                conn, cur.lastrowid, data["prompt"], data.get("negative_prompt", ""), "manual"
            )
        conn.commit()
    return get_shot(cur.lastrowid)

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

def _save_prompt_version(
    conn, shot_id: int, prompt: str, negative_prompt: str = "", source: str = "manual"
):
    latest = conn.execute("""
        SELECT prompt,negative_prompt FROM prompt_versions
        WHERE shot_id=? ORDER BY version DESC LIMIT 1
    """, (shot_id,)).fetchone()
    if latest and latest["prompt"] == prompt and latest["negative_prompt"] == negative_prompt:
        return None
    version = conn.execute(
        "SELECT COALESCE(MAX(version),0)+1 FROM prompt_versions WHERE shot_id=?",
        (shot_id,),
    ).fetchone()[0]
    return conn.execute("""
        INSERT INTO prompt_versions (shot_id,version,prompt,negative_prompt,source)
        VALUES (?,?,?,?,?)
    """, (shot_id, version, prompt, negative_prompt, source)).lastrowid

def save_prompt_version(
    shot_id: int, prompt: str, negative_prompt: str = "", source: str = "generated"
):
    with closing(get_connection()) as conn:
        version_id = _save_prompt_version(conn, shot_id, prompt, negative_prompt, source)
        conn.commit()
    return version_id

def list_prompt_versions(shot_id: int):
    with closing(get_connection()) as conn:
        rows = conn.execute("""
            SELECT * FROM prompt_versions WHERE shot_id=? ORDER BY version DESC
        """, (shot_id,)).fetchall()
    return [dict(row) for row in rows]

def create_media_result(shot_id: int, data: dict):
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM shots WHERE id=?", (shot_id,)).fetchone():
            return None
        prompt_version_id = data.get("prompt_version_id")
        if prompt_version_id and not conn.execute(
            "SELECT 1 FROM prompt_versions WHERE id=? AND shot_id=?",
            (prompt_version_id, shot_id),
        ).fetchone():
            raise ValueError("גרסת הפרומפט אינה שייכת לשוט.")
        version = conn.execute("""
            SELECT COALESCE(MAX(version),0)+1 FROM media_results
            WHERE shot_id=? AND media_type=?
        """, (shot_id, data["media_type"])).fetchone()[0]
        cur = conn.execute("""
            INSERT INTO media_results
            (shot_id,media_type,version,url,provider,model,prompt_version_id,status,notes,metadata_json)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            shot_id, data["media_type"], version, data["url"], data.get("provider", ""),
            data.get("model", ""), prompt_version_id, data.get("status", "טיוטה"),
            data.get("notes", ""), json.dumps(data.get("metadata", {}), ensure_ascii=False),
        ))
        conn.commit()
        row = conn.execute("SELECT * FROM media_results WHERE id=?", (cur.lastrowid,)).fetchone()
    result = dict(row)
    result["metadata"] = json.loads(result["metadata_json"] or "{}")
    return result

def list_media_results(shot_id: int):
    with closing(get_connection()) as conn:
        rows = conn.execute("""
            SELECT * FROM media_results WHERE shot_id=?
            ORDER BY media_type,version DESC
        """, (shot_id,)).fetchall()
    return [
        {**dict(row), "metadata": json.loads(row["metadata_json"] or "{}")} for row in rows
    ]
