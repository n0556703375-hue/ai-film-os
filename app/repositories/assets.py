from contextlib import closing
from app.database.connection import get_connection

def list_assets():
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT * FROM assets ORDER BY asset_type,name").fetchall()
    return [dict(r) for r in rows]

def create_asset(data: dict):
    data = dict(data)
    data["approved"] = int(data.get("approved", False))
    with closing(get_connection()) as conn:
        cur = conn.execute("""
            INSERT INTO assets
            (project_id,asset_type,name,description,visual_rules,master_prompt,negative_prompt,reference_url,approved)
            VALUES (1,?,?,?,?,?,?,?,?)
        """, (
            data["asset_type"], data["name"], data.get("description",""),
            data.get("visual_rules",""), data.get("master_prompt",""),
            data.get("negative_prompt",""), data.get("reference_url",""),
            data["approved"]
        ))
        conn.commit()
        row = conn.execute("SELECT * FROM assets WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)
