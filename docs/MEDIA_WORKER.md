# AI Film OS Media Worker

The media worker executes durable jobs from the `media_jobs` queue outside the FastAPI web request.

## Run locally

```bash
python -m app.worker
```

## Render background worker

Create a **Background Worker** service from the same repository and branch/deploy source as the web service.

Use this start command:

```bash
python -m app.worker
```

Configure the same secrets and persistent database path used by the web service:

- `MAGNIFIC_API_KEY`
- `OPENAI_API_KEY` when prompt refinement is used
- `DATABASE_PATH`
- `MAGNIFIC_API_BASE` when customized

Optional worker settings:

- `MEDIA_WORKER_ID` — explicit worker name
- `MEDIA_WORKER_POLL_INTERVAL` — provider polling interval in seconds, default `3`
- `MEDIA_WORKER_TASK_TIMEOUT` — maximum image task polling time, default `600`
- `MEDIA_WORKER_IDLE_SLEEP` — sleep when the queue is empty, default `2`

## Current capability

- claims one queued/retrying job atomically
- submits image generation to Magnific
- polls until completion
- validates the returned image
- creates a versioned image media result
- advances the shot to `תמונת טיוטה`
- records the provider task id and queue job id
- retries temporary failures within the job retry budget
- terminally fails invalid configuration and unsupported video jobs

Video execution will be added after a video provider/model is selected.
