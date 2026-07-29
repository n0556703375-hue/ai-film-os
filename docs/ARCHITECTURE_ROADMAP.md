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

### 0. Multi-production safety — IN PROGRESS
- **DONE** Project, scene, shot, asset, issue and media-job records are project-aware.
- **DONE** Project switching and project-scoped list filters.
- **DONE** Cross-project shot/scene and shot/asset relationship guards.
- **DONE** Automated two-project end-to-end isolation test (PR #160).
- **NEXT** Audit remaining write endpoints for common-project ownership checks.
- **NEXT** Confirm that generation, approvals, continuity and scene assembly never mix project data.
- **BLOCKED** Multi-user or multi-client access requires authentication, authorization and workspace ownership decisions.

**Exit gate:** two independent productions can run in one deployment without reads, writes, jobs, references or approvals crossing project boundaries.

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
- **NEXT** Validate one complete image-to-video flow against the configured production provider.
- **NEXT** Model selection by shot requirements.
- **NEXT** Duration, camera-motion and audio controls in the operator workflow.
- **NEXT** Project-isolation regression coverage for video jobs and results.

**Exit gate:** an approved image can produce a stored, reviewable video version through the deployed system without blocking the web request.

### 6. Continuity Director — IN PROGRESS
- **DONE** Stored continuity issues and severity levels.
- **DONE** Critical unresolved issues block final approval.
- **IN PROGRESS** Shot context and previous-shot comparisons.
- **NEXT** Compare each shot with both previous and next shots.
- **NEXT** Strengthen character, wardrobe, prop, lighting, geography and eyeline checks.
- **NEXT** Add project-isolation and regression tests for continuity results.

### 7. Scene assembly — IN PROGRESS
- **DONE** Shot ordering and duration fields.
- **DONE** Preview export manifest foundation.
- **IN PROGRESS** Scene-level assembly data.
- **NEXT** Validate timeline ordering and duration totals end to end.
- **NEXT** Audio and dialogue tracking.
- **NEXT** Export-ready scene manifest containing only approved media.

### 8. Production reliability — IN PROGRESS
- **DONE** Durable media-job table with idempotency keys, attempts and cost fields.
- **DONE** Retry foundations and automated CI checks.
- **NEXT** Run long generation and breakdown work in a real separate worker process.
- **NEXT** Add deployment smoke checks for health, screenplay import and job polling.
- **NEXT** Complete cost and credit tracking in operator-visible workflows.
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
