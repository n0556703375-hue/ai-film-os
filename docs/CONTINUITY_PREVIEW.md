# Continuity neighbor preview

`GET /api/issues/shots/{shot_id}/continuity-preview` compares a shot with the previous and next shots in the same scene.

The preview checks linked production assets and structured visual fields such as lighting, mood, camera angle, composition, color palette, and camera movement. It returns issues, neighboring shot identifiers, a blocking issue count, and a provisional `can_finalize` flag.

This endpoint is intentionally non-destructive: it does not create, replace, resolve, or delete continuity issue records. Persisting reviewed findings remains a separate operator action.
