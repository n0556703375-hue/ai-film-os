"""Unit tests for app/services/chunked_screenplay_upload.py — the
transport-only workaround for networks that block a large single POST
body but pass small ones through (see the module docstring: an Israeli
ISP/organizational content filter observed in production doing exactly
this, at more than one size threshold). Chunks are inert text fragments
here; nothing in this module parses or interprets them. Pieces are
appended in arrival order and finalized via an explicit `is_final` flag
rather than a pre-declared chunk count, since the client adapts chunk
size on the fly and can't know the final count up front.
"""

import unittest

from app.services import chunked_screenplay_upload as chunk_service


class ChunkedScreenplayUploadTests(unittest.TestCase):
    def setUp(self):
        chunk_service._pending.clear()

    def tearDown(self):
        chunk_service._pending.clear()

    def test_single_final_chunk_completes_immediately(self):
        result = chunk_service.receive_chunk(
            upload_id="u1", chunk_text="hello", is_final=True,
            project_id=1, import_run_id=None,
        )
        self.assertTrue(result["completed"])
        self.assertEqual(result["screenplay_text"], "hello")

    def test_multi_part_upload_reassembles_in_arrival_order(self):
        chunk_service.receive_chunk(
            upload_id="u2", chunk_text="AAA", is_final=False,
            project_id=1, import_run_id=None,
        )
        second = chunk_service.receive_chunk(
            upload_id="u2", chunk_text="BBB", is_final=False,
            project_id=1, import_run_id=None,
        )
        self.assertFalse(second["completed"])
        self.assertEqual(second["received_chars"], 6)

        third = chunk_service.receive_chunk(
            upload_id="u2", chunk_text="CCC", is_final=True,
            project_id=1, import_run_id=None,
        )
        self.assertTrue(third["completed"])
        self.assertEqual(third["screenplay_text"], "AAABBBCCC")

    def test_upload_is_removed_once_completed(self):
        chunk_service.receive_chunk(
            upload_id="u4", chunk_text="x", is_final=True,
            project_id=1, import_run_id=None,
        )
        self.assertNotIn("u4", chunk_service._pending)

    def test_a_piece_retried_after_a_network_failure_would_duplicate_content(self):
        # This documents a known limitation rather than asserting desired
        # behavior: the accumulator has no way to distinguish "the client
        # retried this exact piece" from "the client sent new content" —
        # dedup is intentionally not attempted here, because the evidence
        # from production (an identical, static-sized block page on every
        # blocked attempt) is that the filter intercepts the *request*
        # before it reaches this code at all, so a blocked piece never
        # actually arrives here in the first place. If that assumption
        # ever turns out wrong, this is the test to revisit.
        chunk_service.receive_chunk(
            upload_id="u5", chunk_text="AAA", is_final=False,
            project_id=1, import_run_id=None,
        )
        chunk_service.receive_chunk(
            upload_id="u5", chunk_text="AAA", is_final=False,
            project_id=1, import_run_id=None,
        )
        result = chunk_service.receive_chunk(
            upload_id="u5", chunk_text="BBB", is_final=True,
            project_id=1, import_run_id=None,
        )
        self.assertEqual(result["screenplay_text"], "AAAAAABBB")

    def test_oversized_chunk_is_rejected(self):
        with self.assertRaises(chunk_service.ChunkedUploadError) as ctx:
            chunk_service.receive_chunk(
                upload_id="u8", chunk_text="x" * (chunk_service.MAX_CHUNK_CHARS + 1),
                is_final=True, project_id=1, import_run_id=None,
            )
        self.assertEqual(ctx.exception.category, "chunk_too_large")

    def test_mismatched_project_id_mid_upload_is_rejected(self):
        chunk_service.receive_chunk(
            upload_id="u10", chunk_text="AAA", is_final=False,
            project_id=1, import_run_id=None,
        )
        with self.assertRaises(chunk_service.ChunkedUploadError) as ctx:
            chunk_service.receive_chunk(
                upload_id="u10", chunk_text="BBB", is_final=True,
                project_id=2, import_run_id=None,
            )
        self.assertEqual(ctx.exception.category, "upload_mismatch")

    def test_mismatched_import_run_id_mid_upload_is_rejected(self):
        chunk_service.receive_chunk(
            upload_id="u11", chunk_text="AAA", is_final=False,
            project_id=1, import_run_id=7,
        )
        with self.assertRaises(chunk_service.ChunkedUploadError) as ctx:
            chunk_service.receive_chunk(
                upload_id="u11", chunk_text="BBB", is_final=True,
                project_id=1, import_run_id=8,
            )
        self.assertEqual(ctx.exception.category, "upload_mismatch")

    def test_too_many_parts_is_rejected(self):
        original_limit = chunk_service.MAX_PARTS_PER_UPLOAD
        chunk_service.MAX_PARTS_PER_UPLOAD = 2
        try:
            chunk_service.receive_chunk(
                upload_id="u13", chunk_text="A", is_final=False,
                project_id=1, import_run_id=None,
            )
            chunk_service.receive_chunk(
                upload_id="u13", chunk_text="B", is_final=False,
                project_id=1, import_run_id=None,
            )
            with self.assertRaises(chunk_service.ChunkedUploadError) as ctx:
                chunk_service.receive_chunk(
                    upload_id="u13", chunk_text="C", is_final=True,
                    project_id=1, import_run_id=None,
                )
            self.assertEqual(ctx.exception.category, "too_many_chunks")
        finally:
            chunk_service.MAX_PARTS_PER_UPLOAD = original_limit

    def test_expired_pending_upload_is_swept_and_starts_fresh(self):
        chunk_service.receive_chunk(
            upload_id="u12", chunk_text="AAA", is_final=False,
            project_id=1, import_run_id=None,
        )
        # Simulate the TTL having elapsed without waiting real time.
        chunk_service._pending["u12"].created_at -= (chunk_service.UPLOAD_TTL_SECONDS + 1)

        # A fresh piece for the same id now starts a brand new upload
        # rather than appending to (or being rejected against) the
        # abandoned one.
        result = chunk_service.receive_chunk(
            upload_id="u12", chunk_text="fresh", is_final=True,
            project_id=1, import_run_id=None,
        )
        self.assertTrue(result["completed"])
        self.assertEqual(result["screenplay_text"], "fresh")


if __name__ == "__main__":
    unittest.main()
