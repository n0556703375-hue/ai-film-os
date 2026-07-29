from contextlib import closing
from app.database.connection import get_connection


def list_issues(resolved: bool | None = None, project_id: int | None = None):
    query = """
        SELECT ci.*, s.shot_number, s.title AS shot_title, a.name AS asset_name
        FROM continuity_issues ci
        LEFT JOIN shots s ON s.id=ci.shot_id
        LEFT JOIN assets a ON a.id=ci.asset_id
    """
    conditions = []
    params = []
    if resolved is not None:
        conditions.append("ci.resolved=?")
        params.append(int(resolved))
    if project_id is not None:
        conditions.append("ci.project_id=?")
        params.append(project_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += """
        ORDER BY
          CASE ci.severity
            WHEN 'critical' THEN 1
            WHEN 'high' THEN 2
            WHEN 'medium' THEN 3
            ELSE 4
          END,
          ci.created_at DESC
    """
    with closing(get_connection()) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def replace_shot_issues(shot_id: int, issues: list[dict]):
    with closing(get_connection()) as conn:
        shot = conn.execute(
            "SELECT project_id FROM shots WHERE id=?", (shot_id,)
        ).fetchone()
        if not shot:
            raise ValueError("השוט שנבחר אינו קיים.")
        project_id = shot["project_id"]

        conn.execute(
            "DELETE FROM continuity_issues WHERE shot_id=? AND resolved=0",
            (shot_id,)
        )

        conn.executemany("""
            INSERT INTO continuity_issues
            (project_id,shot_id,severity,category,message,status)
            VALUES (?,?,?,?,?,?)
        """, [
            (
                project_id,
                shot_id,
                issue.get("severity", "medium"),
                issue.get("category", "general"),
                issue.get("message", ""),
                "פתוח",
            )
            for issue in issues
        ])
        conn.commit()


def resolve_issue(issue_id: int, resolved: bool):
    with closing(get_connection()) as conn:
        cur = conn.execute("""
            UPDATE continuity_issues
            SET resolved=?,
                status=CASE WHEN ?=1 THEN 'נפתר' ELSE 'פתוח' END,
                resolved_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE id=?
        """, (int(resolved), int(resolved), int(resolved), issue_id))
        conn.commit()
    return cur.rowcount > 0


def clear_resolved(project_id: int):
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("הפרויקט שנבחר אינו קיים.")
        cur = conn.execute(
            "DELETE FROM continuity_issues WHERE resolved=1 AND project_id=?",
            (project_id,),
        )
        conn.commit()
    return cur.rowcount


def _related_project_id(conn, table: str, record_id: int | None) -> int | None:
    if record_id is None:
        return None
    row = conn.execute(
        f"SELECT project_id FROM {table} WHERE id=?", (record_id,)
    ).fetchone()
    return row["project_id"] if row else None


def _validate_issue_relationships(
    conn,
    project_id: int,
    shot_id: int | None,
    asset_id: int | None,
):
    if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        raise ValueError("הפרויקט שנבחר אינו קיים.")

    if shot_id is not None:
        shot_project_id = _related_project_id(conn, "shots", shot_id)
        if shot_project_id is None:
            raise ValueError("השוט שנבחר אינו קיים.")
        if shot_project_id != project_id:
            raise ValueError("לא ניתן לשייך בעיית רציפות לשוט מפרויקט אחר.")

    if asset_id is not None:
        asset_project_id = _related_project_id(conn, "assets", asset_id)
        if asset_project_id is None:
            raise ValueError("הנכס שנבחר אינו קיים.")
        if asset_project_id != project_id:
            raise ValueError("לא ניתן לשייך בעיית רציפות לנכס מפרויקט אחר.")


def create_issue(data: dict):
    data = dict(data)
    data["resolved"] = int(data.get("status") == "נפתר")
    with closing(get_connection()) as conn:
        _validate_issue_relationships(
            conn,
            data["project_id"],
            data.get("shot_id"),
            data.get("asset_id"),
        )
        cur = conn.execute("""
            INSERT INTO continuity_issues
            (project_id,shot_id,asset_id,severity,category,message,status,expected,observed,resolution,resolved)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["project_id"], data.get("shot_id"), data.get("asset_id"),
            data.get("severity", "medium"), data["category"], data["message"],
            data.get("status", "פתוח"), data.get("expected", ""),
            data.get("observed", ""), data.get("resolution", ""), data["resolved"],
        ))
        conn.commit()
        row = conn.execute("SELECT * FROM continuity_issues WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def update_issue(issue_id: int, fields: dict):
    fields = dict(fields)
    if "status" in fields:
        fields["resolved"] = int(fields["status"] == "נפתר")
        fields["resolved_at"] = None
    with closing(get_connection()) as conn:
        previous = conn.execute(
            "SELECT * FROM continuity_issues WHERE id=?", (issue_id,)
        ).fetchone()
        if not previous:
            return None

        project_id = fields.get("project_id", previous["project_id"])
        shot_id = fields.get("shot_id", previous["shot_id"])
        asset_id = fields.get("asset_id", previous["asset_id"])
        _validate_issue_relationships(conn, project_id, shot_id, asset_id)

        sets = ", ".join(f"{key}=?" for key in fields)
        conn.execute(
            f"UPDATE continuity_issues SET {sets},updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [*fields.values(), issue_id],
        )
        conn.commit()
        row = conn.execute("SELECT * FROM continuity_issues WHERE id=?", (issue_id,)).fetchone()
    return dict(row)
