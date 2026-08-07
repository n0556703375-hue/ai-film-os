"""Scoped lookups for media_results rows.

The Sync.so lip-sync path must never act on a client-supplied audio URL.
It resolves an audio media record server-side instead, and every invariant
the caller depends on is expressed as a constraint inside the SQL WHERE
clause. Nothing is fetched by primary key and validated afterwards: a row
that fails any invariant simply does not come back, so there is no window
in which an unverified record is in hand.

Audio media type note
---------------------
``media_results.media_type`` is currently constrained by the schema to
``('image', 'video')``. ``AUDIO_MEDIA_TYPE`` is therefore not yet storable,
and this resolver returns None for every input until a future migration
adds it. That is the intended fail-closed behaviour: Sync stays disabled
rather than running on unverified audio. This module deliberately does not
change the schema.
"""

from contextlib import closing

from app.database.connection import get_connection
from app.repositories.approvals import APPROVED

AUDIO_MEDIA_TYPE = "audio"

# Re-exported so callers assert against the repository's own approved
# status rather than restating the literal.
APPROVED_STATUS = APPROVED


def get_approved_audio_for_shot(
    media_result_id: int,
    shot_id: int,
    project_id: int,
) -> dict | None:
    """Return an approved audio media record owned by this shot and project.

    Every invariant is a WHERE-clause constraint, so a mismatch on any of
    them yields None rather than a row the caller must re-check:

      * the record exists (``mr.id``)
      * it belongs to the given shot (``mr.shot_id``)
      * that shot belongs to the given project (``s.project_id``)
      * it is audio (``mr.media_type``)
      * it is approved (``mr.status``)

    The project join is explicit rather than inferred from the shot match,
    so a job row carrying a mismatched shot/project pair cannot widen access.

    Returns None for any non-positive or non-integer identifier.
    """
    try:
        media_result_id = int(media_result_id)
        shot_id = int(shot_id)
        project_id = int(project_id)
    except (TypeError, ValueError):
        return None
    if media_result_id < 1 or shot_id < 1 or project_id < 1:
        return None

    with closing(get_connection()) as conn:
        row = conn.execute(
            """
            SELECT mr.id, mr.shot_id, mr.media_type, mr.status, mr.url
            FROM media_results mr
            JOIN shots s ON s.id = mr.shot_id
            WHERE mr.id = ?
              AND mr.shot_id = ?
              AND s.project_id = ?
              AND mr.media_type = ?
              AND mr.status = ?
            """,
            (
                media_result_id,
                shot_id,
                project_id,
                AUDIO_MEDIA_TYPE,
                APPROVED_STATUS,
            ),
        ).fetchone()
    return dict(row) if row else None
