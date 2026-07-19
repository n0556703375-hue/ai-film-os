# Video Generation Workspace

The Shot Workspace exposes validated image-to-video controls while keeping paid provider execution behind the durable media worker.

## Operator flow

1. Approve an image result for the shot.
2. Open the shot and select **יצירת וידאו**.
3. Set duration, aspect ratio, camera motion, audio mode, model preference and optional instructions.
4. Confirm the credit warning.
5. The request is stored as a durable video job and continues outside the browser session.
6. The workspace polls job state and displays the completed video when available.

## Safety behavior

- the API rejects video enqueueing without an approved image
- duplicate requests reuse the same idempotent job
- closing the browser does not cancel the job
- the default provider is disabled and performs no paid request
- credentials stay in environment variables

## Provider boundary

A concrete provider is selected only through `app/services/video_provider.py`. UI, queue, approvals and media version storage remain provider-neutral.
