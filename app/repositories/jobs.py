import json
from contextlib import closing

from app.database.connection import get_connection

ACTIVE_STATUSES = {"queued", "running", "retrying"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def enqueue_job(project_id: int, shot_id: int, job_type: str, payload: dict, idempotency_key: str, max_attempts: int = 3, estimated_cost_usd: float = 0):
    if job_type not in {"image", "video"}:
        raise ValueError("סוג משימת המדיה אינו תקין.")
    if max_attempts < 1:
        raise ValueError("מספר הניסיונות חייב להיות לפחות 1.")
    if estimated_cost_usd < 0:
        raise ValueError("עלות משוערת אינה יכולה להיות שלילית.")
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM shots WHERE id=? AND project_id=?", (shot_id, project_id)).fetchone():
            raise ValueError("השוט אינו שייך לפרויקט.")
        existing = conn.execute(
            "SELECT * FROM media_jobs WHERE idempotency_key=? ORDER BY id DESC LIMIT 1",
            (idempotency_key,),
        ).fetchone()
        if existing and existing["status"] in ACTIVE_STATUSES | {"completed"}:
            return _decode(existing), False
        encoded_payload = json.dumps(payload, ensure_ascii=False)
        if existing:
            conn.execute(
                """
                UPDATE media_jobs
                SET project_id=?,shot_id=?,job_type=?,status='queued',payload_json=?,result_json='{}',
                    max_attempts=?,attempts=0,worker_id='',last_error='',estimated_cost_usd=?,actual_cost_usd=0,
                    started_at=NULL,finished_at=NULL,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (project_id, shot_id, job_type, encoded_payload, max_attempts, estimated_cost_usd, existing["id"]),
            )
            conn.commit()
            return get_job(existing["id"]), True
        cur = conn.execute(
            """
            INSERT INTO media_jobs
            (project_id,shot_id,job_type,status,payload_json,idempotency_key,max_attempts,estimated_cost_usd)
            VALUES (?,?,?,'queued',?,?,?,?)
            """,
            (project_id, shot_id, job_type, encoded_payload, idempotency_key, max_attempts, estimated_cost_usd),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM media_jobs WHERE id=?", (cur.lastrowid,)).fetchone()
    return _decode(row), True


def claim_next_job(worker_id: str):
    with closing(get_connection()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT * FROM media_jobs
            WHERE status IN ('queued','retrying') AND attempts < max_attempts
            ORDER BY priority DESC,id ASC LIMIT 1
            """
        ).fetchone()
        if not row:
            conn.commit()
            return None
        conn.execute(
            """
            UPDATE media_jobs SET status='running',attempts=attempts+1,worker_id=?,
                started_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (worker_id, row["id"]),
        )
        conn.commit()
    return get_job(row["id"])


def complete_job(job_id: int, result: dict, actual_cost_usd: float = 0):
    if actual_cost_usd < 0:
        raise ValueError("עלות בפועל אינה יכולה להיות שלילית.")
    return _finish(job_id, "completed", result=result, actual_cost_usd=actual_cost_usd)


def fail_job(job_id: int, error: str, retryable: bool = True):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM media_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        status = "retrying" if retryable and row["attempts"] < row["max_attempts"] else "failed"
        conn.execute(
            """
            UPDATE media_jobs SET status=?,last_error=?,worker_id='',
                finished_at=CASE WHEN ?='failed' THEN CURRENT_TIMESTAMP ELSE NULL END,
                updated_at=CURRENT_TIMESTAMP WHERE id=?
            """,
            (status, error, status, job_id),
        )
        conn.commit()
    return get_job(job_id)


def _finish(job_id: int, status: str, result: dict | None = None, actual_cost_usd: float = 0):
    with closing(get_connection()) as conn:
        if not conn.execute("SELECT 1 FROM media_jobs WHERE id=?", (job_id,)).fetchone():
            return None
        conn.execute(
            """
            UPDATE media_jobs SET status=?,result_json=?,actual_cost_usd=?,last_error='',
                finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?
            """,
            (status, json.dumps(result or {}, ensure_ascii=False), actual_cost_usd, job_id),
        )
        conn.commit()
    return get_job(job_id)


def get_job(job_id: int):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM media_jobs WHERE id=?", (job_id,)).fetchone()
    return _decode(row) if row else None


def list_jobs(project_id: int | None = None, shot_id: int | None = None):
    query = "SELECT * FROM media_jobs WHERE 1=1"
    params = []
    if project_id is not None:
        query += " AND project_id=?"
        params.append(project_id)
    if shot_id is not None:
        query += " AND shot_id=?"
        params.append(shot_id)
    query += " ORDER BY id DESC"
    with closing(get_connection()) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_decode(row) for row in rows]


def get_cost_summary(project_id: int):
    with closing(get_connection()) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS job_count,
                   COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
                   COALESCE(SUM(actual_cost_usd), 0) AS actual_cost_usd
            FROM media_jobs WHERE project_id=?
            """,
            (project_id,),
        ).fetchone()
    return dict(row)


def _decode(row):
    data = dict(row)
    data["payload"] = json.loads(data.pop("payload_json") or "{}")
    data["result"] = json.loads(data.pop("result_json") or "{}")
    return data
