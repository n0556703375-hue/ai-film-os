# AI Film OS — Full System Architecture

## 1. Product boundary

AI Film OS is a production operating system for AI filmmaking. It manages the complete path from screenplay to approved scene masters while preserving identity, visual continuity, prompt history, media provenance, cost, and production status.

The system is not only a prompt generator. It is the source of truth for:

- projects and screenplay versions
- scenes and dramatic breakdowns
- shots and production specifications
- characters, locations, wardrobe, props and visual rules
- approved reference packs and locks
- prompt versions
- image, video and audio generations
- approvals and rejection notes
- continuity findings
- background jobs, retries and provider costs
- scene assembly and export manifests

## 2. Architectural principles

1. **One source of truth** — production state lives in AI Film OS, not in scattered provider libraries.
2. **Locked assets drive generation** — only approved locked references may flow automatically into production generations.
3. **Everything is versioned** — screenplay, prompt, reference, image, video and approval changes remain traceable.
4. **Providers are replaceable** — OpenAI, Magnific and future providers are adapters behind internal interfaces.
5. **Long work is asynchronous** — screenplay breakdown, batch shot maps, image/video generation and QA run as background jobs.
6. **Human approval remains explicit** — generation does not equal approval.
7. **Additive migrations only** — existing production data is preserved.
8. **Idempotent operations** — retries must not duplicate scenes, shots, prompts, media or costs.

## 3. System layers

### 3.1 Presentation layer

Current server-rendered RTL web application, evolving into focused workspaces:

- Production Dashboard
- Screenplay Workspace
- Story Bible
- Character Lock Workspace
- Location / Wardrobe Lock Workspace
- Scene Workspace
- Shot Workspace
- Generation Queue
- Continuity Center
- Scene Assembly
- Cost and Usage Center
- Settings and Provider Health

The UI communicates only with the internal API and never calls provider APIs directly.

### 3.2 API layer

FastAPI routers grouped by domain:

- `/api/projects`
- `/api/screenplays`
- `/api/scenes`
- `/api/shots`
- `/api/assets`
- `/api/reference-packs`
- `/api/prompts`
- `/api/generations`
- `/api/jobs`
- `/api/approvals`
- `/api/continuity`
- `/api/assemblies`
- `/api/costs`
- `/api/system`

API responsibilities:

- validation and authorization
- orchestration request creation
- returning domain states
- never blocking on long provider work

### 3.3 Domain services

Core services contain production rules and do not depend on HTTP:

- `ScreenplayService`
- `SceneBreakdownService`
- `ShotMapService`
- `AssetLockService`
- `ReferencePackService`
- `PromptComposer`
- `GenerationOrchestrator`
- `ApprovalService`
- `ContinuityDirector`
- `SceneAssemblyService`
- `CostLedgerService`
- `ProviderHealthService`

### 3.4 Provider adapters

Internal contracts isolate external services:

- `TextProvider`
- `ImageProvider`
- `VideoProvider`
- `AudioProvider`
- `StorageProvider`

Initial adapters:

- OpenAI text and reasoning adapter
- Magnific image adapter
- Magnific or another supported image-to-video adapter
- future ElevenLabs audio adapter
- local/generated-media storage adapter, later object storage

Each provider response is normalized into the same internal generation result structure.

### 3.5 Persistence layer

Initial database: SQLite for development and small single-instance deployment.

Production target: PostgreSQL before concurrent workers or multi-user production.

Repositories own database access. Domain services do not build SQL directly.

### 3.6 Background execution layer

Required before full-film generation:

- persistent `jobs` table
- worker process separate from web process
- claim/lease mechanism
- retry policy with exponential backoff
- cancellation
- progress and heartbeat fields
- idempotency keys
- provider task polling
- dead-letter state for repeated failures

A database-backed worker is acceptable first. Redis/Celery or another queue may be introduced only when required by scale.

## 4. Core data model

### 4.1 Production hierarchy

`projects`
- id
- name
- description
- visual_style
- rules
- status
- created_at / updated_at

`screenplay_versions`
- id
- project_id
- version
- source_type
- original_filename
- content
- checksum
- status
- created_at

`scenes`
- id
- project_id
- screenplay_version_id
- scene_number
- title
- source_text
- story_goal
- emotion
- conflict
- beginning
- ending
- estimated_duration_seconds
- status

`shots`
- id
- project_id
- scene_id
- shot_number
- title
- duration_seconds
- shot_type
- camera / angle / lens / movement
- composition / action / lighting / mood / palette
- audio / dialogue
- status
- approved_image_media_id
- approved_video_media_id

### 4.2 Story Bible and lock model

`assets`
- id
- project_id
- asset_type
- name
- description
- visual_rules
- master_prompt
- negative_prompt
- workflow_status: draft | review | locked | retired
- locked_at
- lock_version

`asset_references`
- id
- asset_id
- reference_type: master | portrait | full_body | three_quarter | profile | expression | location_state | wardrobe_state
- label
- media_result_id or external_url
- approved
- is_master
- sort_order
- identity_fingerprint metadata
- created_at

`asset_lock_events`
- id
- asset_id
- action: lock | unlock | replace_master | retire
- previous_lock_version
- new_lock_version
- reason
- actor
- created_at

`shot_assets`
- shot_id
- asset_id
- required_lock_version
- role_in_shot

Generation must fail validation when a required asset is not locked or its requested lock version is unavailable.

### 4.3 Prompt and media provenance

`prompt_versions`
- id
- shot_id
- version
- prompt
- negative_prompt
- source
- structured_input_json
- asset_lock_snapshot_json
- created_at

`generation_jobs`
- id
- project_id
- shot_id
- media_type
- provider
- model
- operation
- status: queued | running | polling | succeeded | failed | cancelled | dead
- idempotency_key
- provider_task_id
- progress
- attempt_count
- max_attempts
- error_code / error_message
- input_json / output_json
- created_at / started_at / completed_at / heartbeat_at

`media_results`
- id
- project_id
- shot_id
- asset_id
- job_id
- media_type
- version
- url / storage_key
- provider
- model
- status: draft | review | approved | rejected | archived
- prompt_version_id
- width / height / duration
- checksum
- metadata_json
- created_at

### 4.4 Approval and continuity

`approval_events`
- id
- entity_type
- entity_id
- action: submit | approve | reject | reopen
- notes
- actor
- created_at

`continuity_issues`
- id
- project_id
- scene_id
- shot_id
- compared_shot_id
- asset_id
- category
- severity
- expected
- observed
- message
- resolution
- status
- created_at / resolved_at

Critical unresolved continuity issues block final shot and scene approval.

### 4.5 Cost ledger

`usage_events`
- id
- project_id
- job_id
- provider
- model
- operation
- quantity
- unit
- estimated_cost
- actual_cost
- currency
- provider_credits
- created_at

Costs are append-only and derived totals are calculated from the ledger.

### 4.6 Scene assembly

`scene_assemblies`
- id
- scene_id
- version
- status
- total_duration_seconds
- manifest_json
- preview_url
- created_at

`scene_assembly_items`
- assembly_id
- shot_id
- media_result_id
- sequence_order
- in_point
- out_point
- audio_media_id

## 5. Main workflows

### 5.1 Screenplay ingestion

1. Upload or paste screenplay.
2. Save immutable screenplay version and checksum.
3. Queue scene breakdown job.
4. Show proposed scene boundaries before destructive replacement.
5. Confirm import.
6. Create scenes transactionally.
7. Queue shot-map jobs scene by scene.
8. Track progress without keeping one HTTP request open.

### 5.2 Character lock

1. Create character asset.
2. Generate or upload candidate references.
3. Review portrait, full body, three-quarter, profiles and expressions.
4. Choose one master identity.
5. Validate minimum reference pack.
6. Lock character and assign lock version.
7. Snapshot that lock version into every later prompt.
8. Unlocking requires a reason and does not rewrite historical generations.

### 5.3 Shot production

1. Shot specification is approved.
2. Resolve required locked assets.
3. Compose structured prompt.
4. Save immutable prompt version and asset-lock snapshot.
5. Queue image generation.
6. Poll provider asynchronously.
7. Save candidate media.
8. Review, reject with notes, or approve.
9. Queue image-to-video from approved image.
10. Approve final video.

### 5.4 Continuity workflow

1. Compare shot with previous, next and scene master state.
2. Check identity, wardrobe, props, lighting, geography, direction, eyeline and time state.
3. Record issues with severity.
4. Suggest correction targets.
5. Block final approval for unresolved critical issues.
6. Re-run checks after a replacement generation.

### 5.5 Scene assembly

1. Select approved video for every shot.
2. Order by shot number.
3. Validate missing media and duration conflicts.
4. Create assembly manifest.
5. Produce preview or export package.
6. Approve scene master.

## 6. State machines

### Asset
`draft → review → locked → retired`

Unlocking creates a new review state and preserves the prior lock version.

### Shot
`planned → spec_ready → prompt_ready → image_generating → image_review → image_approved → video_generating → video_review → video_approved → continuity_passed → final`

Failure and rejection states return to the appropriate earlier stage without deleting history.

### Job
`queued → running → polling → succeeded`

Alternate paths:
- `running/polling → failed → queued` when retryable
- `failed → dead` after maximum attempts
- `queued/running/polling → cancelled`

### Scene
`planned → shots_ready → producing → continuity_review → assembly_ready → approved`

## 7. Generation orchestration

The orchestrator must:

- select provider and model from shot needs and configured policy
- validate locked references
- estimate cost before dispatch
- require explicit confirmation for paid batch generation
- create job and idempotency key first
- submit to provider
- store provider task identifier
- poll outside the web request
- download or proxy results when provider URLs are unstable
- validate media dimensions, type and non-empty content
- save immutable result metadata
- notify the UI through polling initially; WebSocket/SSE may be added later

## 8. Security and data safety

- API keys remain in environment variables or a secrets manager.
- No provider key is returned to the browser.
- External URLs are validated before server-side download.
- File type, size and redirect limits are enforced.
- Destructive replacement requires explicit confirmation and transaction boundaries.
- Audit events record locks, approvals, replacements and project-wide imports.
- Production database backups are mandatory before schema-changing deployment.

## 9. Deployment architecture

### Current stage
- Render web service
- one FastAPI process
- SQLite persistent disk
- generated media proxy/storage

### Required production stage
- Render or equivalent web service
- separate worker service
- PostgreSQL
- persistent object storage for approved media
- health endpoints for web, database, worker and providers
- scheduled cleanup for temporary media only
- deployment migration step
- rollback-capable releases

## 10. Testing strategy

### Unit tests
- state transitions
- lock validation
- prompt composition
- idempotency keys
- retry classification
- cost calculations
- continuity rules

### Repository tests
- additive migrations
- transaction rollback
- cascade behavior
- version numbering

### Provider contract tests
- normalized responses
- queued and polling states
- invalid/blank media rejection
- timeout and retry handling

### API tests
- validation
- approval permissions
- destructive confirmation
- project isolation

### End-to-end production test
A small synthetic project must pass:

`screenplay → scenes → shot maps → locked assets → approved image → approved video → continuity pass → scene assembly`

No film production begins until this test passes reliably.

## 11. Delivery phases and exit gates

### Phase A — Production foundation
Complete when screenplay versions, scene import and shot maps run safely as jobs.

### Phase B — Visual source of truth
Complete when characters, locations and wardrobe can be locked and only locked references reach generation.

### Phase C — Approval pipeline
Complete when prompt, image and video candidates have explicit versioned approvals and batch review.

### Phase D — Video and continuity
Complete when approved images become tracked videos and critical continuity failures block finalization.

### Phase E — Assembly and reliability
Complete when scene previews, retries, costs, worker health and deployment checks are operational.

### Final release gate
AI Film OS is considered ready for the actual film only when:

- all phases above are complete
- automated tests pass
- the end-to-end synthetic production passes
- provider failures recover without duplicate charges or duplicate media records
- approved assets remain reproducible and historically traceable
- production deployment and backup/restore are verified

## 12. Immediate implementation order

1. Character Lock data model, API, UI and tests.
2. Generalize the lock system for locations and wardrobe.
3. Introduce screenplay versions and asynchronous import jobs.
4. Introduce persistent generation jobs and a worker.
5. Complete approval events and shot state machine.
6. Add video provider adapter and image-to-video flow.
7. Build Continuity Director blocking rules.
8. Build scene assembly and export manifest.
9. Add cost ledger, provider health, backups and full end-to-end tests.
