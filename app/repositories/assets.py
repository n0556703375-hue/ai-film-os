from contextlib import closing
import json
from app.database.connection import get_connection

def list_assets(project_id: int | None = None):
    query = "SELECT * FROM assets"
    params: tuple = ()
    if project_id is not None:
        query += " WHERE project_id=?"
        params = (project_id,)
    query += " ORDER BY asset_type,name"
    with closing(get_connection()) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

def get_asset(asset_id: int):
    with closing(get_connection()) as conn:
        asset = conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if not asset:
            return None
        shots = conn.execute("""
            SELECT s.id,s.shot_number,s.title,s.status
            FROM shots s
            JOIN shot_assets sa ON sa.shot_id=s.id
            WHERE sa.asset_id=?
            ORDER BY s.shot_number
        """, (asset_id,)).fetchall()
        references = conn.execute("""
            SELECT * FROM asset_reference_images WHERE asset_id=?
            ORDER BY created_at DESC,id DESC
        """, (asset_id,)).fetchall()
    result = dict(asset)
    result["linked_shots"] = [dict(s) for s in shots]
    result["reference_images"] = [
        {**dict(r), "metadata": json.loads(r["metadata_json"] or "{}")} for r in references
    ]
    return result

def create_reference_image(asset_id: int, data: dict):
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone():
            return None
        cur = conn.execute("""
            INSERT INTO asset_reference_images
            (asset_id,view_type,url,prompt,provider,model,metadata_json)
            VALUES (?,?,?,?,?,?,?)
        """, (asset_id, data["view_type"], data["url"], data.get("prompt", ""),
              data.get("provider", "Magnific"), data.get("model", "Nano Banana Pro"),
              json.dumps(data.get("metadata", {}), ensure_ascii=False)))
        conn.execute("UPDATE assets SET reference_url=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (data["url"], asset_id))
        conn.commit()
        row = conn.execute("SELECT * FROM asset_reference_images WHERE id=?", (cur.lastrowid,)).fetchone()
    return {**dict(row), "metadata": json.loads(row["metadata_json"] or "{}")}

def create_asset(data: dict):
    data = dict(data)
    data["approved"] = int(data.get("approved", False))
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (data.get("project_id", 1),)).fetchone():
            raise ValueError("הפרויקט אינו קיים.")
        cur = conn.execute("""
            INSERT INTO assets
            (project_id,asset_type,name,description,visual_rules,master_prompt,negative_prompt,reference_url,approved)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            data.get("project_id", 1),
            data["asset_type"], data["name"], data.get("description",""),
            data.get("visual_rules",""), data.get("master_prompt",""),
            data.get("negative_prompt",""), data.get("reference_url",""),
            data["approved"]
        ))
        conn.commit()
        row = conn.execute("SELECT * FROM assets WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)

def update_asset(asset_id: int, fields: dict):
    fields = dict(fields)
    if "approved" in fields:
        fields["approved"] = int(fields["approved"])
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone():
            return None
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(
            f"""UPDATE assets SET {sets},
            version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            [*fields.values(), asset_id]
        )
        conn.commit()
    return get_asset(asset_id)

def delete_asset(asset_id: int) -> bool:
    with closing(get_connection()) as conn:
        cur = conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
        conn.commit()
    return cur.rowcount > 0
