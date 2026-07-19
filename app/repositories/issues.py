from contextlib import closing
from app.database.connection import get_connection

def list_issues(resolved: bool | None = None):
    query = """
        SELECT ci.*, s.shot_number, s.title AS shot_title, a.name AS asset_name
        FROM continuity_issues ci
        LEFT JOIN shots s ON s.id=ci.shot_id
        LEFT JOIN assets a ON a.id=ci.asset_id
    """
    params = []
    if resolved is not None:
        query += " WHERE ci.resolved=?"
        params.append(int(resolved))
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
        project_id = conn.execute(
            "SELECT project_id FROM shots WHERE id=?", (shot_id,)
        ).fetchone()[0]

        conn.execute(
            "DELETE FROM continuity_issues WHERE shot_id=? AND resolved=0",
            (shot_id,)
        )

        conn.executemany("""
            INSERT INTO continuity_issues
            (project_id,shot_id,severity,category,message)
            VALUES (?,?,?,?,?)
        """, [
            (
                project_id,
                shot_id,
                issue.get("severity", "medium"),
                issue.get("category", "general"),
                issue.get("message", ""),
            )
            for issue in issues
        ])
        conn.commit()

def resolve_issue(issue_id: int, resolved: bool):
    with closing(get_connection()) as conn:
        cur = conn.execute("""
            UPDATE continuity_issues
            SET resolved=?,
                resolved_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE id=?
        """, (int(resolved), int(resolved), issue_id))
        conn.commit()
    return cur.rowcount > 0

def clear_resolved():
    with closing(get_connection()) as conn:
        cur = conn.execute("DELETE FROM continuity_issues WHERE resolved=1")
        conn.commit()
    return cur.rowcount
