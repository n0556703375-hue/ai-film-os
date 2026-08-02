# AI Film OS — Architecture Roadmap

## Product goal
A production operating system that turns a complete screenplay into approved, continuity-safe image, video and audio assets, organized by project, scene and shot.

## Status legend
- **DONE** — implemented, tested and merged.
- **IN PROGRESS** — active focused work or awaiting validation.
- **NEXT** — next safe implementation step.
- **BLOCKED** — requires a material product or infrastructure decision.
- **LATER** — intentionally deferred until the current production flow is stable.

## Current execution order

### 0. Multi-production safety — DONE
- **DONE** Project, scene, shot, asset, issue and media-job records are project-aware.
- **DONE** Project switching and project-scoped list filters.
- **DONE** Cross-project shot/scene and shot/asset relationship guards.
- **DONE** Automated two-project end-to-end isolation test (PR #160).
- **DONE** Continuity issue update endpoint scoped to its owning project (PR #172).
- **DONE** Approval decision, shot finalize, and all three batch approval/finalize endpoints scoped to their owning project (PR #184).
- **DONE** Write-endpoint audit: remaining single-ID endpoints (job claim/complete/fail, identity-drift claim/record/evaluate, generation queue/refine) resolve `project_id` server-side from the record itself rather than trusting client input, so they cannot mix project data by construction. Multi-ID endpoints (`shot_id`+asset list, `scene_id`+`asset_id`) already reject cross-project pairs.
- **BLOCKED** Multi-user or multi-client access requires authentication, authorization and workspace ownership decisions.

**Exit gate:** two independent productions can run in one deployment without reads, writes, jobs, references or approvals crossing project boundaries. Met — see Milestone A coverage below.

### 1. Production foundation — IN PROGRESS
- **DONE** Full screenplay import flow and scene persistence.
- **DONE** Scene breakdown.
- **DONE** Automatic shot maps.
- **DONE** Prompt and media versioning.
- **DONE** Project-wide progress totals.
- **DONE** Safe parsing for empty, HTML, malformed and structured API responses.
- **DONE** Structured partial-progress reporting.
- **DONE** User-triggered retry of the failed import stage with duplicate guards.
- **NEXT** Production smoke test of screenplay import on Render after deploy.
- **NEXT** Close issue #87 only after the production test succeeds.

**Exit gate:** a complete screenplay can be imported on the deployed service, and temporary failures can be retried without replacing or duplicating persisted scenes or shots.

### 2. Character Lock — DONE
- **DONE** One approved master identity per character.
- **DONE** Approved reference gallery by view and expression.
- **DONE** Draft / review / locked status.
- **DONE** Only locked references flow into shot generation.
- **DONE** Identity drift checks and approval blocking.

### 3. Location and wardrobe lock — DONE
- **DONE** Master location and wardrobe references.
- **DONE** Scene-level state variants.
- **DONE** Automatic reference propagation into generation.

### 4. Shot approval pipeline — DONE
- **DONE** Planned → prompt ready → image draft → image approved → video draft → video approved → final.
- **DONE** Batch actions and pipeline filters.
- **DONE** Explicit approval history.
- **DONE** Final approval gates and continuity blockers.

### 5. Video production — IN PROGRESS
- **DONE** Provider-neutral video jobs.
- **DONE** Image-to-video job creation.
- **DONE** Polling and completed media-version storage.
- **DONE** Confirmed bounded retry for failed video jobs.
- **DONE** Model selection by shot requirements, with the queue-time estimate and the worker's actual provider request guaranteed consistent (PR #186).
- **DONE** Duration, camera-motion and audio controls in the operator workflow (job-queue-ui.js) and API (`VideoQueueRequest`).
- **DONE** Project-isolation regression coverage for video jobs and results (`test_video_job_project_isolation.py`, `test_video_result_ingestion.py`).
- **NEXT** Validate one complete image-to-video flow against the configured production provider. Requires a live deployment with real provider credentials — cannot be verified from a local/CI checkout.

**Exit gate:** an approved image can produce a stored, reviewable video version through the deployed system without blocking the web request.

### 6. Continuity Director — DONE
- **DONE** Stored continuity issues and severity levels.
- **DONE** Critical unresolved issues block final approval.
- **DONE** Each shot is compared against both its previous and next shot in the scene (`continuity_preview`).
- **DONE** Character, wardrobe and prop checks (asset presence/absence diff), lighting/mood/camera/composition/color-palette checks (`TRACKED_FIELDS`), screen-direction (geography) and eyeline-direction checks.
- **DONE** Project-isolation regression coverage (`test_continuity_preview.py::test_preview_never_uses_neighbors_from_another_project`).

### 7. Scene assembly — DONE
- **DONE** Shot ordering and duration fields.
- **DONE** Preview export manifest, validated end to end for timeline ordering and duration totals (`test_scene_preview_manifest.py`).
- **DONE** Audio and dialogue tracking (`audio_notes`/`dialogue`/`has_audio_notes`/`has_dialogue` in the manifest timeline).
- **DONE** Manifest surfaces only approved media (`_approved_media`) and excludes shots/media from other projects.

### 8. Production reliability — IN PROGRESS
- **DONE** Durable media-job table with idempotency keys, attempts and cost fields.
- **DONE** Retry foundations and automated CI checks.
- **DONE** Deployment smoke checks for health, screenplay import and video-job polling (`scripts/deployment_smoke.py`).
- **DONE** Operator-visible cost dashboard: estimated/actual USD, status breakdown and variance from existing read-only endpoints (`cost-tracking-ui.js`).
- **NEXT** Run long generation and breakdown work in a real separate worker process.
- **BLOCKED** Production database and storage decision: persistent SQLite disk versus Postgres.
- **BLOCKED** Render topology decision: web service plus separate worker and persistent storage.

**Exit gate:** deploys do not lose production data, long jobs do not block the web process, and retries are idempotent and observable.

## Validation milestones

### Milestone A — Two-production readiness
1. Create two projects.
2. Import a screenplay into each.
3. Create distinct scenes, shots and assets.
4. Attempt deliberate cross-project links and verify rejection without mutation.
5. Generate prompts/media for both projects.
6. Confirm lists, jobs, approvals, continuity issues and manifests remain isolated.

### Milestone B — Deployed production flow
1. Import a real screenplay on Render.
2. Generate a shot map.
3. Create and approve an image.
4. Generate and approve a video.
5. Run continuity checks.
6. Finalize a shot.
7. Build the scene preview manifest.

### Milestone C — Scale decision
After Milestones A and B pass, decide whether the next target is:
- multiple productions for one internal team, or
- a multi-client product with users, roles, workspaces and tenant-level authorization.

## Automatic continuation policy
Continue without asking for approval when the change is:
- additive, focused and reversible;
- covered by tests;
- free of schema/data destruction;
- passing CI;
- free of unresolved review blockers.

Stop for a material decision when the change includes:
- database migration strategy or production data movement;
- Render service topology, paid infrastructure or persistent storage;
- authentication, authorization, organizations or billing;
- destructive replacement or cleanup of production data;
- provider changes that affect cost, credentials or output behavior.

## Engineering rules
- Never develop directly on `main`.
- One focused branch and pull request per capability.
- Preserve existing project data through additive migrations.
- Require explicit confirmation before destructive replacement.
- Keep provider credentials in environment variables only.
- Merge only after tests and review checks pass.
- Treat project ownership as a required invariant on every relationship write.
