"""Build a read-only snapshot of one production from persistent project data."""

from contextlib import closing

from app.database.connection import get_connection
from app.database.query import execute_query


def build_production_snapshot(project_id: int):
    with closing(get_connection()) as conn:
        project = execute_query(
            conn,
            "SELECT * FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
        if not project:
            return None

        scenes = execute_query(
            conn,
            "SELECT * FROM scenes WHERE project_id=? ORDER BY scene_number, id",
            (project_id,),
        ).fetchall()
        shots = execute_query(
            conn,
            "SELECT * FROM shots WHERE project_id=? ORDER BY scene_id, shot_number, id",
            (project_id,),
        ).fetchall()
        assets = execute_query(
            conn,
            "SELECT * FROM assets WHERE project_id=? ORDER BY asset_type, name, id",
            (project_id,),
        ).fetchall()
        shot_asset_rows = execute_query(
            conn,
            """
            SELECT sa.shot_id, sa.asset_id
            FROM shot_assets sa
            JOIN shots s ON s.id=sa.shot_id
            WHERE s.project_id=?
            ORDER BY sa.shot_id, sa.asset_id
            """,
            (project_id,),
        ).fetchall()
        media_rows = execute_query(
            conn,
            """
            SELECT mr.*
            FROM media_results mr
            JOIN shots s ON s.id=mr.shot_id
            WHERE s.project_id=?
            ORDER BY mr.shot_id, mr.media_type, mr.version DESC
            """,
            (project_id,),
        ).fetchall()
        issue_rows = execute_query(
            conn,
            "SELECT * FROM continuity_issues WHERE project_id=? ORDER BY resolved, severity, id",
            (project_id,),
        ).fetchall()

    asset_ids_by_shot = {}
    for row in shot_asset_rows:
        asset_ids_by_shot.setdefault(row["shot_id"], []).append(row["asset_id"])

    media_by_shot = {}
    approved_image_by_shot = {}
    for row in media_rows:
        item = dict(row)
        media_by_shot.setdefault(row["shot_id"], []).append(item)
        if row["media_type"] == "image" and row["status"] in {"מאושר", "approved"}:
            approved_image_by_shot.setdefault(row["shot_id"], row["id"])

    serialized_shots = []
    for row in shots:
        item = dict(row)
        item["asset_ids"] = asset_ids_by_shot.get(row["id"], [])
        item["approved_image_id"] = approved_image_by_shot.get(row["id"])
        item["media_results"] = media_by_shot.get(row["id"], [])
        serialized_shots.append(item)

    return {
        "project": dict(project),
        "scenes": [dict(row) for row in scenes],
        "shots": serialized_shots,
        "assets": [dict(row) for row in assets],
        "continuity_issues": [dict(row) for row in issue_rows],
        "read_only": True,
    }
