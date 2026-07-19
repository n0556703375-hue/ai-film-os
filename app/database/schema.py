SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    visual_style TEXT NOT NULL DEFAULT '',
    rules TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    scene_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    story_goal TEXT NOT NULL DEFAULT '',
    emotion TEXT NOT NULL DEFAULT '',
    conflict TEXT NOT NULL DEFAULT '',
    beginning TEXT NOT NULL DEFAULT '',
    ending TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS shots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    scene_id INTEGER,
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
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(scene_id) REFERENCES scenes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    asset_type TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    visual_rules TEXT NOT NULL DEFAULT '',
    master_prompt TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    reference_url TEXT NOT NULL DEFAULT '',
    approved INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS shot_assets (
    shot_id INTEGER NOT NULL,
    asset_id INTEGER NOT NULL,
    PRIMARY KEY(shot_id, asset_id),
    FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS continuity_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    shot_id INTEGER,
    asset_id INTEGER,
    severity TEXT NOT NULL DEFAULT 'medium',
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shot_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS media_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shot_id INTEGER NOT NULL,
    media_type TEXT NOT NULL CHECK(media_type IN ('image', 'video')),
    version INTEGER NOT NULL,
    url TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prompt_version_id INTEGER,
    status TEXT NOT NULL DEFAULT 'טיוטה',
    notes TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(shot_id, media_type, version),
    FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE,
    FOREIGN KEY(prompt_version_id) REFERENCES prompt_versions(id) ON DELETE SET NULL
);
"""
