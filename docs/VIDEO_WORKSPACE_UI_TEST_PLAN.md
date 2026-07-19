# Video Workspace UI Verification

Run before merging:

```bash
python -m compileall -q app
python -m unittest discover -s tests -v
```

Manual smoke checks:

- opening a shot shows one **יצירת וידאו** button
- the form includes duration, aspect ratio, audio, model, camera motion and instructions
- cancel returns to the shot
- enqueue requires explicit confirmation
- a missing approved image returns the server validation message
- queued, running, retrying, completed and failed states render without exposing credentials
- completed video renders with browser controls
