# Video Generation Modes — Product and Architecture Plan

Status: design-only. This document intentionally does not change Script Import code or behavior.

## Why this change is required

The current video generation path is hard-wired to image-to-video:

- `VideoGenerationRequest.image_url` is mandatory.
- `/api/video-generation/shots/{shot_id}/readiness` requires an approved image and public image reachability.
- `/api/video-generation/shots/{shot_id}/queue` rejects the request if there is no approved image.
- Seedance model configuration defaults only to `.../image-to-video` model IDs.
- the Shot Workspace disables Generate Video when there is no approved image.

That is correct for the stabilized Image-to-Video vertical slice, but it is not the correct product model for AI Film OS.

A shot may be generated directly from text, from an approved image, from an existing video, or from start/end frames depending on the selected provider/model.

## Canonical generation modes

Use one explicit `generation_mode` value for every video job:

- `text_to_video`
- `image_to_video`
- `video_to_video`
- `start_end_frames`

Do not infer the mode only from whether an image happens to exist.

### Mode requirements

| Mode | Required source inputs | Optional source inputs |
|---|---|---|
| `text_to_video` | usable prompt | references supported by provider |
| `image_to_video` | approved source image + public reachability | prompt, camera motion |
| `video_to_video` | approved source video + provider-compatible reachability | prompt/instructions |
| `start_end_frames` | approved start frame; end frame only if required by selected model | prompt, motion |

Provider/model capability must be checked before submission.

## Request model

Replace the assumption that a video request always has `image_url` with a mode-aware request contract.

Suggested API-level request:

```text
VideoQueueRequest
- generation_mode
- duration_seconds
- camera_motion
- audio_mode
- aspect_ratio
- model_hint
- instructions
- source_image_media_id?          # image_to_video
- source_video_media_id?          # video_to_video
- start_frame_media_id?           # start_end_frames
- end_frame_media_id?             # start_end_frames
```

The backend must resolve media IDs itself and must never trust a client-provided arbitrary source URL as the canonical source.

The provider adapter request should be equally mode-aware:

```text
VideoGenerationRequest
- generation_mode
- prompt
- duration_seconds
- camera_motion
- audio_mode
- aspect_ratio
- model_profile
- image_url?
- video_url?
- start_frame_url?
- end_frame_url?
```

Fields that are irrelevant to the selected mode should be `None`/empty and must not be sent to a provider.

## Capability registry

Do not spread provider capability checks through UI conditionals.

Introduce one backend capability source of truth, for example:

```text
VideoModelCapability
- provider
- model_id
- generation_modes
- supports_audio
- supported_aspect_ratios
- min_duration
- max_duration
- requires_end_frame
- supports_reference_images
```

The provider selector should select only a model that supports the chosen mode.

If no configured provider/model supports that mode, readiness should fail with a stable reason such as:

`mode_not_supported`

## Readiness redesign

Current readiness is image-specific. Replace it with mode-aware readiness.

Suggested endpoint:

`GET /api/video-generation/shots/{shot_id}/readiness?generation_mode=image_to_video`

Response should remain non-billing and structured:

```json
{
  "ready": true,
  "generation_mode": "image_to_video",
  "provider_configured": true,
  "mode_supported": true,
  "worker_alive": true,
  "prompt_ready": true,
  "required_inputs": {
    "source_image": {"required": true, "present": true, "accessible": true},
    "source_video": {"required": false, "present": false},
    "start_frame": {"required": false, "present": false},
    "end_frame": {"required": false, "present": false}
  },
  "reasons": []
}
```

Readiness rules:

### text_to_video

Ready when:
- a usable prompt exists
- selected/configured provider supports text-to-video
- worker is alive

No approved image requirement.

### image_to_video

Ready when:
- an approved image exists
- its source URL is publicly accessible to the provider
- selected/configured provider supports image-to-video
- worker is alive

### video_to_video

Ready when:
- an approved source video exists
- source video is provider-accessible
- provider supports video-to-video
- worker is alive

### start_end_frames

Ready when:
- approved start frame exists
- approved end frame exists only if the selected model requires one
- required frames are provider-accessible
- provider supports the mode
- worker is alive

## Queue endpoint rules

`POST /api/video-generation/shots/{shot_id}/queue` must validate the same mode-aware requirements again at click time.

Readiness is UX protection; queue-time validation is the billing/safety boundary.

Never rely only on the browser readiness result.

## Idempotency / duplicate billing

The existing resumable provider-task protection must be preserved for every mode.

The job key must include:

- shot ID
- generation mode
- all selected source media IDs
- prompt or prompt-version identity
- duration
- aspect ratio
- camera motion
- model hint/profile
- generation instructions

Different generation modes must never collide into the same idempotency key.

Retry after provider submission must reuse the same provider task ID exactly as the current stabilized Image-to-Video path does.

## Media persistence

All successful provider results must continue through the existing server-side persistence layer:

provider result URL
→ server download
→ `/generated/videos/shot-{id}/{uuid}.mp4`
→ local media_result URL
→ browser playback

No generation mode may expose a temporary provider CDN URL as the final media result.

## Shot Workspace UX

Do not disable the global Generate Video button merely because no image exists.

Recommended flow:

1. User clicks `יצירת וידאו`.
2. UI shows generation method options supported by current configured providers:
   - Text to Video
   - Image to Video
   - Video to Video
   - Start / End Frames
3. Select mode.
4. Show only fields/inputs relevant to that mode.
5. Run readiness for that mode.
6. Show a mode-specific checklist.
7. Submit only when ready.

If only one mode is supported by the configured provider, the UI may preselect it, but the backend data model should still persist the explicit mode.

### Example checklist — text_to_video

- ✓ Prompt ready
- ✓ Provider supports Text-to-Video
- ✓ Worker active

No image checklist row.

### Example checklist — image_to_video

- ✓ Approved source image
- ✓ Image publicly accessible
- ✓ Provider supports Image-to-Video
- ✓ Worker active

## Source selection

When multiple approved images/videos exist, do not silently use the first record forever.

The UI should allow explicit source selection, and the selected media ID must be persisted in the video job payload.

For backward compatibility, the first implementation may auto-select the latest approved source when there is exactly one valid candidate.

## Provider architecture

The current Seedance adapter is image-to-video-specific and sends `image_url` unconditionally. Do not add mode conditionals endlessly to the same payload builder.

Preferred shape:

```text
SeedanceProvider
  submit(request)
    -> dispatch by generation_mode
       -> build_text_to_video_payload()
       -> build_image_to_video_payload()
       -> build_start_end_frames_payload()
```

Only implement a mode when the actual configured fal.ai/Seedance endpoint is verified to support it. Unsupported modes should fail before billing.

Do not invent provider endpoint IDs.

## Model configuration

Current configuration names are mode-specific in behavior but not in structure:

- `FAL_SEEDANCE_MODEL`
- `FAL_SEEDANCE_FAST_MODEL`

They currently point to image-to-video endpoints.

Before adding text-to-video support, introduce explicit model config or a model registry so a text-to-video request cannot accidentally be sent to an image-to-video endpoint.

Possible explicit env naming:

- `FAL_SEEDANCE_I2V_MODEL`
- `FAL_SEEDANCE_I2V_FAST_MODEL`
- `FAL_SEEDANCE_T2V_MODEL`
- `FAL_SEEDANCE_T2V_FAST_MODEL`

Keep backward compatibility with the existing image-to-video env names during migration if needed.

## Stable error/readiness categories

Add mode-aware safe categories, for example:

- `generation_mode_required`
- `mode_not_supported`
- `prompt_required`
- `no_approved_image`
- `source_image_unreachable`
- `no_approved_video`
- `source_video_unreachable`
- `no_start_frame`
- `no_end_frame`
- `source_frame_unreachable`
- `provider_not_configured`
- `worker_not_alive`
- `invalid_mode_input`

Raw provider text must not be shown or persisted.

## Database / persistence

Persist `generation_mode` as first-class job data. A dedicated column is preferable if jobs will be queried/filtered by mode; otherwise the first safe iteration can keep it in structured payload with tests pinning the contract.

Do not change Script Import schema in this work.

## Migration strategy

### Phase A — architecture without new paid mode

1. Add `generation_mode` with default `image_to_video` for backwards compatibility.
2. Make `VideoGenerationRequest` optional-source/mode-aware.
3. Make readiness mode-aware.
4. Make job key mode-aware.
5. Keep current Image-to-Video provider behavior unchanged.
6. Update UI so Generate Video opens a mode selector, with unsupported modes clearly unavailable.
7. Run existing Image-to-Video production smoke test again.

This phase should introduce no new provider billing behavior.

### Phase B — Text-to-Video

Only after verifying the current fal.ai/Seedance text-to-video endpoint and schema:

1. register T2V capability/model
2. implement provider payload builder
3. add provider contract tests using mocked fal-client
4. add readiness tests proving no image requirement
5. run one controlled production T2V smoke test
6. verify local persistence and redeploy survival

### Phase C — remaining modes

Add Video-to-Video and Start/End Frames one provider/model at a time with the same contract.

## Tests required

At minimum:

- image_to_video remains backwards compatible
- text_to_video readiness does not require an image
- image_to_video still requires approved/reachable image
- video_to_video requires approved video
- start_end_frames requirements follow capability metadata
- unsupported mode fails before provider submission
- queue endpoint revalidates readiness
- job keys differ by mode/source media
- retry reuses provider task ID
- successful output is persisted locally for every implemented mode
- browser/API receives local `/generated/videos/...` URL only
- no provider URL or credential leak

## Definition of done for the first implementation

The architecture is ready when:

1. `generation_mode` is explicit from UI through job payload through provider request.
2. Image-to-Video still passes all existing tests and production behavior.
3. Text-to-Video can be selected without any image requirement once a verified provider endpoint is configured.
4. Readiness checks requirements for the selected mode, not a universal image rule.
5. Unsupported modes fail before any paid submission.
6. Retry/idempotency/persistence guarantees from the stabilized vertical slice remain intact.

## Non-goals for this work

Do not modify:

- Script Import / Breakdown
- AI Director / Shot Design
- Magnific image generation
- Audio or Lip-sync
- scene parsing
- screenplay schema

This change should be isolated to the video-generation contract, provider capability layer, readiness, job payload/idempotency, and Shot Workspace video-generation UI.
