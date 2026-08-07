import json
from contextlib import closing

from app.database.connection import get_connection


def create_import_run(
    project_id: int,
    *,
    source_type: str,
    source_filename: str,
    source_hash: str,
    screenplay_text: str,
    breakdown: dict,
    warnings: list,
    scene_count: int,
    character_count: int,
    location_count: int,
    prop_count: int = 0,
    status: str = "review_required",
) -> dict:
    with closing(get_connection()) as conn:
        cur = conn.execute(
            """
            INSERT INTO import_runs (
                project_id, source_type, source_filename, source_hash, status,
                screenplay_text, breakdown_json, warnings_json,
                scene_count, character_count, location_count, prop_count
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                project_id, source_type, source_filename, source_hash, status,
                screenplay_text, json.dumps(breakdown, ensure_ascii=False),
                json.dumps(warnings, ensure_ascii=False),
                scene_count, character_count, location_count, prop_count,
            ),
        )
        conn.commit()
        run_id = cur.lastrowid
    return get_import_run(run_id)


def update_import_run(import_run_id: int, fields: dict) -> dict | None:
    if not fields:
        return get_import_run(import_run_id)
    encoded = dict(fields)
    if "breakdown" in encoded:
        encoded["breakdown_json"] = json.dumps(encoded.pop("breakdown"), ensure_ascii=False)
    if "warnings" in encoded:
        encoded["warnings_json"] = json.dumps(encoded.pop("warnings"), ensure_ascii=False)
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM import_runs WHERE id=?", (import_run_id,)).fetchone():
            return None
        sets = ", ".join(f"{key}=?" for key in encoded)
        conn.execute(
            f"UPDATE import_runs SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [*encoded.values(), import_run_id],
        )
        conn.commit()
    return get_import_run(import_run_id)


def mark_approved(import_run_id: int) -> dict | None:
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM import_runs WHERE id=?", (import_run_id,)).fetchone():
            return None
        conn.execute(
            """
            UPDATE import_runs SET status='approved', approved_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP WHERE id=?
            """,
            (import_run_id,),
        )
        conn.commit()
    return get_import_run(import_run_id)


def supersede_other_approved_runs(project_id: int, keep_import_run_id: int) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            """
            UPDATE import_runs SET status='superseded', updated_at=CURRENT_TIMESTAMP
            WHERE project_id=? AND status='approved' AND id<>?
            """,
            (project_id, keep_import_run_id),
        )
        conn.commit()


def get_import_run(import_run_id: int) -> dict | None:
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM import_runs WHERE id=?", (import_run_id,)).fetchone()
    return _decode(row) if row else None


def find_approved_run_by_hash(project_id: int, source_hash: str) -> dict | None:
    with closing(get_connection()) as conn:
        row = conn.execute(
            """
            SELECT * FROM import_runs
            WHERE project_id=? AND source_hash=? AND status='approved'
            ORDER BY id DESC LIMIT 1
            """,
            (project_id, source_hash),
        ).fetchone()
    return _decode(row) if row else None


def list_import_runs(project_id: int) -> list[dict]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM import_runs WHERE project_id=? ORDER BY id DESC",
            (project_id,),
        ).fetchall()
    return [_decode(row) for row in rows]


def _decode(row) -> dict:
    data = dict(row)
    data["breakdown"] = json.loads(data.pop("breakdown_json") or "{}")
    data["warnings"] = json.loads(data.pop("warnings_json") or "[]")
    return data
