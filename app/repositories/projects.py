from contextlib import closing

from app.database.connection import get_connection
from app.database.query import execute_query


def list_projects():
    with closing(get_connection()) as conn:
        rows = execute_query(
            conn,
            """
            SELECT p.*,
              (SELECT COUNT(*) FROM scenes sc WHERE sc.project_id=p.id) AS scenes_total,
              (SELECT COUNT(*) FROM shots s WHERE s.project_id=p.id) AS shots_total,
              (SELECT COUNT(*) FROM assets a WHERE a.project_id=p.id) AS assets_total
            FROM projects p ORDER BY p.id
            """,
        ).fetchall()
        status_rows = execute_query(
            conn,
            """
            SELECT project_id, status, COUNT(*) AS total
            FROM shots
            GROUP BY project_id, status
            ORDER BY project_id, status
            """,
        ).fetchall()

    status_totals_by_project = {}
    for row in status_rows:
        project_id = row["project_id"]
        status = row["status"] or "not_started"
        status_totals_by_project.setdefault(project_id, {})[status] = row["total"]

    projects = []
    for row in rows:
        project = dict(row)
        project["shot_status_totals"] = status_totals_by_project.get(project["id"], {})
        projects.append(project)
    return projects


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
        row = execute_query(
            conn,
            """
            INSERT INTO projects (name,description,visual_style,rules)
            VALUES (?,?,?,?)
            RETURNING *
            """,
            (
                data["name"], data.get("description", ""),
                data.get("visual_style", ""), data.get("rules", ""),
            ),
        ).fetchone()
        conn.commit()
    return dict(row)


def update_project(project_id: int, fields: dict):
    with closing(get_connection()) as conn:
        if not execute_query(
            conn, "SELECT 1 FROM projects WHERE id=?", (project_id,)
        ).fetchone():
            return None
        sets = ", ".join(f"{k}=?" for k in fields)
        row = execute_query(
            conn,
            f"UPDATE projects SET {sets},updated_at=CURRENT_TIMESTAMP WHERE id=? RETURNING *",
            [*fields.values(), project_id],
        ).fetchone()
        conn.commit()
    return dict(row)
