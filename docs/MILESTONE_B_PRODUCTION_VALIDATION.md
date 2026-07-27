# Milestone B — Deployed production flow validation

## Purpose

Prove that one real scene from **כתובת אפס** can move through the deployed Render system from screenplay text to an export-ready, continuity-checked, approved-media-only scene manifest without manual data patching.

This runbook is evidence-oriented. Do not mark a step complete from local tests alone.

## Scope guard

Included:
- production screenplay import smoke test
- real provider image-to-video validation
- continuity validation
- scene assembly and approved-media-only manifest validation
- deploy/retry/redeploy persistence checks
- two-project isolation evidence

Explicitly excluded until Milestone B passes:
- multi-user authentication or authorization
- billing, organizations or workspaces
- Render topology changes
- production database/storage migration

## Evidence record

Record the following for every run without secrets or raw provider payloads:
- UTC timestamp
- deployed commit SHA
- Render service URL or service identifier
- project ID and scene ID
- request/job IDs
- persisted record counts before and after retry/redeploy
- sanitized status/result summaries
- links to CI, issue or PR evidence

Never commit screenplay text, credentials, signed media URLs or raw provider errors.

## Gate 1 — Screenplay import on Render

1. Deploy current `main`.
2. Create or select the dedicated **כתובת אפס** production.
3. Capture baseline scene and shot counts.
4. Submit the full screenplay through the deployed import workflow.
5. Confirm imported scenes and generated shots are scoped to the selected project.
6. Trigger the supported retry path once after a simulated or naturally retryable stage failure.
7. Confirm persisted scenes and shots are not duplicated or replaced.
8. Redeploy the same commit and confirm counts and project relationships remain unchanged.

Pass criteria:
- import completes or safely resumes
- no duplicate scenes or shots
- no destructive replacement
- records remain after redeploy
- Issue #87 receives production evidence before closure

## Gate 2 — Real image-to-video provider flow

1. Select one shot with an approved source image.
2. Record its duration, camera-motion, dialogue/audio and identity requirements.
3. Submit one video generation job through the deployed operator workflow.
4. Confirm the stored model-selection profile and reason match shot requirements.
5. Poll through queued/running/terminal status using the deployed endpoint.
6. Confirm exactly one draft video media version is persisted with job, prompt and source-image lineage.
7. Repeat the completion callback or poll completion path and confirm idempotency.
8. Confirm a second project's concurrent job cannot be read, completed or attached to the first project.

Pass criteria:
- submit → poll → result storage completes against the configured provider
- no web-request blocking behavior is observed
- no duplicate result media
- no cross-project job/result leakage

## Gate 3 — Continuity Director

For the validated scene:
1. Run continuity checks for every shot.
2. Verify each shot is compared with both previous and next neighbors where present.
3. Review character, wardrobe, prop, lighting, geography and eyeline findings.
4. Confirm continuity results belong only to the current production.
5. Resolve or explicitly accept all blocking findings before final approval.

Pass criteria:
- neighbor comparisons are bidirectional
- defined continuity categories produce persisted, reviewable results
- critical unresolved findings block finalization
- results do not cross projects

## Gate 4 — Scene assembly and manifest

1. Confirm timeline order matches shot order.
2. Recalculate cumulative duration from persisted shots and compare with assembly totals.
3. Confirm dialogue and audio tracking are present for relevant shots.
4. Approve the selected image and generated video through the normal workflow.
5. Build the scene export manifest.
6. Confirm the manifest contains only approved media and retains project, scene, shot, duration, dialogue/audio and continuity references.

Pass criteria:
- deterministic ordering
- correct cumulative duration
- approved-media-only output
- no draft/rejected media included
- manifest is usable without manual edits

## Gate 5 — Reliability after deploy

After the successful scene run:
1. Redeploy current `main`.
2. Verify health endpoint.
3. Verify screenplay import status/read path.
4. Verify video job polling and stored result remain accessible.
5. Confirm project/scene/shot/media/continuity/manifest counts are unchanged.
6. Review operator-visible cost and credit fields for the provider job.

Pass criteria:
- deployed health and polling work
- persisted output survives redeploy
- retries remain bounded and idempotent
- cost/credit information is visible without exposing provider secrets

## Milestone B completion record

Milestone B is complete only when all gates have production evidence and one scene from **כתובת אפס** has reached:

`screenplay text → persisted scene/shot map → approved image → stored approved video → continuity checks → finalized shot → approved-media-only scene manifest`

Do not close Issue #87 until Gate 1 passes on Render. Do not begin Milestone C product expansion until all gates pass.