from contextlib import closing

from app.database.connection import get_connection
from app.database.query import execute_query


def list_projects():
    with closing(get_connection()) as conn:
        rows = conn.execute("""
            SELECT p.*,
              (SELECT COUNT(*) FROM scenes sc WHERE sc.project_id=p.id) AS scenes_total,
              (SELECT COUNT(*) FROM shots s WHERE s.project_id=p.id) AS shots_total,
              (SELECT COUNT(*) FROM assets a WHERE a.project_id=p.id) AS assets_total
            FROM projects p ORDER BY p.id
        """).fetchall()
    return [dict(r) for r in rows]


def get_project(project_id: int):
    with closing(get_connection()) as conn:
        row = execute_query(
            conn,
            "SELECT * FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
    return dict(row) if row else None


def create_project(data: dict):
    with closing(get_connection()) as conn:
        cur = conn.execute("""
            INSERT INTO projects (name,description,visual_style,rules)
            VALUES (?,?,?,?)
        """, (
            data["name"], data.get("description", ""),
            data.get("visual_style", ""), data.get("rules", ""),
        ))
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def update_project(project_id: int, fields: dict):
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            return None
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(
            f"UPDATE projects SET {sets},updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [*fields.values(), project_id]
        )
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return dict(row)
