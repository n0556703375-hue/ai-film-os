"""Extract one representative frame from a generated shot video, as a data:
URI OpenAI's vision API can read directly — no public hosting needed for the
extracted frame itself.

Used only by app.services.video_identity_vision, which then hands that data
URI to the exact same identity-comparison path the image flow already uses
(app.services.identity_vision.evaluate_shot_identity) — this module's only
job is turning video bytes into one still image.
"""

from __future__ import annotations

import base64
import io
import tempfile
from pathlib import Path

import imageio.v3 as iio
from PIL import Image

# Bounds how many frames are decoded before picking the middle one — cheap
# for this app's shot clips (a few seconds at ~24fps), and caps memory/time
# on a pathological or corrupt file rather than iterating indefinitely.
_MAX_FRAMES_SCANNED = 1000


class VideoFrameExtractionError(RuntimeError):
    """A stable, sanitized reason a frame could not be extracted.

    Never wraps raw decoder output in the message — codec/container details
    are not guaranteed safe to log or persist.
    """

    EMPTY_VIDEO = "empty_video"
    NO_FRAMES_DECODED = "no_frames_decoded"
    DECODE_FAILED = "decode_failed"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"video_frame_extraction_error: {reason}")


def _pick_middle_frame(video_path: str):
    frames = []
    try:
        for frame in iio.imiter(video_path, plugin="FFMPEG"):
            frames.append(frame)
            if len(frames) >= _MAX_FRAMES_SCANNED:
                break
    except Exception as exc:
        raise VideoFrameExtractionError(VideoFrameExtractionError.DECODE_FAILED) from exc
    if not frames:
        raise VideoFrameExtractionError(VideoFrameExtractionError.NO_FRAMES_DECODED)
    return frames[len(frames) // 2]


def extract_frame_data_uri(video_bytes: bytes) -> str:
    """Decode a representative (middle) frame and return it as a PNG data: URI."""
    if not video_bytes:
        raise VideoFrameExtractionError(VideoFrameExtractionError.EMPTY_VIDEO)

    with tempfile.TemporaryDirectory() as tmp_dir:
        video_path = Path(tmp_dir) / "input.mp4"
        video_path.write_bytes(video_bytes)
        frame = _pick_middle_frame(str(video_path))

    buffer = io.BytesIO()
    Image.fromarray(frame).convert("RGB").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
