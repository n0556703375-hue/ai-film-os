"""Coverage for app.services.video_frame_extraction — turning generated
video bytes into a still-frame data: URI for the identity vision adapter.
Uses a tiny synthetic clip encoded with the imageio-ffmpeg bundled binary,
not a real generated video.
"""

import unittest

import imageio.v3 as iio
import numpy as np

from app.services.video_frame_extraction import (
    VideoFrameExtractionError,
    extract_frame_data_uri,
)


def _make_video_bytes(num_frames: int = 5, size: int = 16) -> bytes:
    import tempfile
    from pathlib import Path

    frames = [np.full((size, size, 3), (i * 40) % 256, dtype=np.uint8) for i in range(num_frames)]
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "clip.mp4"
        iio.imwrite(str(path), frames, fps=5, codec="libx264", plugin="FFMPEG")
        return path.read_bytes()


class VideoFrameExtractionTests(unittest.TestCase):
    def test_empty_bytes_raises(self):
        with self.assertRaises(VideoFrameExtractionError) as ctx:
            extract_frame_data_uri(b"")
        self.assertEqual(ctx.exception.reason, VideoFrameExtractionError.EMPTY_VIDEO)

    def test_garbage_bytes_raise_decode_failed_or_no_frames(self):
        with self.assertRaises(VideoFrameExtractionError) as ctx:
            extract_frame_data_uri(b"this is definitely not a video file" * 10)
        self.assertIn(
            ctx.exception.reason,
            {VideoFrameExtractionError.DECODE_FAILED, VideoFrameExtractionError.NO_FRAMES_DECODED},
        )

    def test_valid_video_returns_png_data_uri(self):
        video_bytes = _make_video_bytes()
        uri = extract_frame_data_uri(video_bytes)
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertGreater(len(uri), len("data:image/png;base64,"))

    def test_extraction_is_deterministic_for_the_same_input(self):
        video_bytes = _make_video_bytes()
        uri_a = extract_frame_data_uri(video_bytes)
        uri_b = extract_frame_data_uri(video_bytes)
        self.assertEqual(uri_a, uri_b)


if __name__ == "__main__":
    unittest.main()
