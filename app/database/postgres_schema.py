"""PostgreSQL schema contract for pre-cutover validation.

This module is intentionally not wired into runtime initialization yet. It lets
CI and temporary PostgreSQL environments validate dialect compatibility before
any production database switch or data migration is attempted.
"""

POSTGRES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    visual_style TEXT NOT NULL DEFAULT '',
    rules TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scenes (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    scene_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    story_goal TEXT NOT NULL DEFAULT '',
    emotion TEXT NOT NULL DEFAULT '',
    conflict TEXT NOT NULL DEFAULT '',
    beginning TEXT NOT NULL DEFAULT '',
    ending TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'מתוכנן',
    updated_at TEXT NOT NULL DEFAULT '',
    original_heading TEXT NOT NULL DEFAULT '',
    normalized_heading TEXT NOT NULL DEFAULT '',
    int_ext TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    time_of_day TEXT NOT NULL DEFAULT '',
    raw_scene_text TEXT NOT NULL DEFAULT '',
    synopsis TEXT NOT NULL DEFAULT '',
    import_run_id BIGINT,
    recommended_shot_count INTEGER,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS shots (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    scene_id BIGINT,
    shot_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    shot_type TEXT NOT NULL DEFAULT 'רגיל',
    status TEXT NOT NULL DEFAULT 'מתוכנן',
    notes TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    camera TEXT NOT NULL DEFAULT '',
    lens TEXT NOT NULL DEFAULT '',
    lighting TEXT NOT NULL DEFAULT '',
    movement TEXT NOT NULL DEFAULT '',
    mood TEXT NOT NULL DEFAULT '',
    dialogue TEXT NOT NULL DEFAULT '',
    duration_seconds DOUBLE PRECISION,
    camera_angle TEXT NOT NULL DEFAULT '',
    composition TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT '',
    color_palette TEXT NOT NULL DEFAULT '',
    audio TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(scene_id) REFERENCES scenes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    asset_type TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    visual_rules TEXT NOT NULL DEFAULT '',
    master_prompt TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    reference_url TEXT NOT NULL DEFAULT '',
    approved INTEGER NOT NULL DEFAULT 0,
    lock_status TEXT NOT NULL DEFAULT 'draft',
    master_reference_id BIGINT,
    locked_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS shot_assets (
    shot_id BIGINT NOT NULL,
    asset_id BIGINT NOT NULL,
    PRIMARY KEY(shot_id, asset_id),
    FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS asset_reference_images (
    id BIGSERIAL PRIMARY KEY,
    asset_id BIGINT NOT NULL,
    view_type TEXT NOT NULL,
    url TEXT NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT 'Magnific',
    model TEXT NOT NULL DEFAULT 'Nano Banana Pro',
    approved INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS continuity_issues (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    shot_id BIGINT,
    asset_id BIGINT,
    severity TEXT NOT NULL DEFAULT 'medium',
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'פתוח',
    expected TEXT NOT NULL DEFAULT '',
    observed TEXT NOT NULL DEFAULT '',
    resolution TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id BIGSERIAL PRIMARY KEY,
    shot_id BIGINT NOT NULL,
    version INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    negative_prompt TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS media_results (
    id BIGSERIAL PRIMARY KEY,
    shot_id BIGINT NOT NULL,
    media_type TEXT NOT NULL CHECK(media_type IN ('image', 'video')),
    version INTEGER NOT NULL,
    url TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prompt_version_id BIGINT,
    status TEXT NOT NULL DEFAULT 'טיוטה',
    notes TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(shot_id, media_type, version),
    FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE,
    FOREIGN KEY(prompt_version_id) REFERENCES prompt_versions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS approval_events (
    id BIGSERIAL PRIMARY KEY,
    shot_id BIGINT NOT NULL,
    media_result_id BIGINT,
    event_type TEXT NOT NULL,
    from_status TEXT NOT NULL DEFAULT '',
    to_status TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE,
    FOREIGN KEY(media_result_id) REFERENCES media_results(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS media_jobs (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    shot_id BIGINT NOT NULL,
    job_type TEXT NOT NULL CHECK(job_type IN ('image','video')),
    status TEXT NOT NULL DEFAULT 'queued',
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT NOT NULL UNIQUE,
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    worker_id TEXT NOT NULL DEFAULT '',
    provider_task_id TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    actual_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS import_runs (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'paste',
    source_filename TEXT NOT NULL DEFAULT '',
    source_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'review_required',
    parser_version TEXT NOT NULL DEFAULT '1',
    screenplay_text TEXT NOT NULL DEFAULT '',
    breakdown_json TEXT NOT NULL DEFAULT '{}',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    scene_count INTEGER NOT NULL DEFAULT 0,
    character_count INTEGER NOT NULL DEFAULT 0,
    location_count INTEGER NOT NULL DEFAULT 0,
    prop_count INTEGER NOT NULL DEFAULT 0,
    error_category TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMPTZ,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scene_content_blocks (
    id BIGSERIAL PRIMARY KEY,
    scene_id BIGINT NOT NULL,
    block_order INTEGER NOT NULL,
    block_type TEXT NOT NULL,
    character_name TEXT NOT NULL DEFAULT '',
    parenthetical TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'high',
    FOREIGN KEY(scene_id) REFERENCES scenes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS screenplay_characters (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    canonical_name TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    first_appearance_scene_number INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, canonical_name),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS screenplay_locations (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    canonical_name TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    first_appearance_scene_number INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, canonical_name),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scene_characters (
    scene_id BIGINT NOT NULL,
    screenplay_character_id BIGINT NOT NULL,
    PRIMARY KEY(scene_id, screenplay_character_id),
    FOREIGN KEY(scene_id) REFERENCES scenes(id) ON DELETE CASCADE,
    FOREIGN KEY(screenplay_character_id) REFERENCES screenplay_characters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scene_asset_variants (
    id BIGSERIAL PRIMARY KEY,
    scene_id BIGINT NOT NULL,
    asset_id BIGINT NOT NULL,
    state_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    reference_url TEXT NOT NULL DEFAULT '',
    visual_rules TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scene_id, asset_id),
    FOREIGN KEY(scene_id) REFERENCES scenes(id) ON DELETE CASCADE,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);
"""
