"""Unit tests for app/services/chunked_screenplay_upload.py — the
transport-only workaround for networks that block a large single POST
body but pass small ones through (see the module docstring: an Israeli
ISP/organizational content filter observed in production doing exactly
this). Chunks are inert text fragments here; nothing in this module
parses or interprets them.
"""

import unittest

from app.services import chunked_screenplay_upload as chunk_service


class ChunkedScreenplayUploadTests(unittest.TestCase):
    def setUp(self):
        chunk_service._pending.clear()

    def tearDown(self):
        chunk_service._pending.clear()

    def test_single_chunk_upload_completes_immediately(self):
        result = chunk_service.receive_chunk(
            upload_id="u1", chunk_index=0, total_chunks=1, chunk_text="hello",
            project_id=1, import_run_id=None,
        )
        self.assertTrue(result["completed"])
        self.assertEqual(result["screenplay_text"], "hello")

    def test_multi_chunk_upload_reassembles_in_order(self):
        chunk_service.receive_chunk(
            upload_id="u2", chunk_index=0, total_chunks=3, chunk_text="AAA",
            project_id=1, import_run_id=None,
        )
        second = chunk_service.receive_chunk(
            upload_id="u2", chunk_index=1, total_chunks=3, chunk_text="BBB",
            project_id=1, import_run_id=None,
        )
        self.assertFalse(second["completed"])
        self.assertEqual(second["received_chunks"], 2)
        self.assertEqual(second["total_chunks"], 3)

        third = chunk_service.receive_chunk(
            upload_id="u2", chunk_index=2, total_chunks=3, chunk_text="CCC",
            project_id=1, import_run_id=None,
        )
        self.assertTrue(third["completed"])
        self.assertEqual(third["screenplay_text"], "AAABBBCCC")

    def test_chunks_can_arrive_out_of_order(self):
        chunk_service.receive_chunk(
            upload_id="u3", chunk_index=2, total_chunks=3, chunk_text="CCC",
            project_id=1, import_run_id=None,
        )
        chunk_service.receive_chunk(
            upload_id="u3", chunk_index=0, total_chunks=3, chunk_text="AAA",
            project_id=1, import_run_id=None,
        )
        result = chunk_service.receive_chunk(
            upload_id="u3", chunk_index=1, total_chunks=3, chunk_text="BBB",
            project_id=1, import_run_id=None,
        )
        self.assertTrue(result["completed"])
        self.assertEqual(result["screenplay_text"], "AAABBBCCC")

    def test_upload_is_removed_once_completed(self):
        chunk_service.receive_chunk(
            upload_id="u4", chunk_index=0, total_chunks=1, chunk_text="x",
            project_id=1, import_run_id=None,
        )
        self.assertNotIn("u4", chunk_service._pending)

    def test_resending_the_same_chunk_index_does_not_duplicate_content(self):
        chunk_service.receive_chunk(
            upload_id="u5", chunk_index=0, total_chunks=2, chunk_text="AAA",
            project_id=1, import_run_id=None,
        )
        chunk_service.receive_chunk(
            upload_id="u5", chunk_index=0, total_chunks=2, chunk_text="AAA",
            project_id=1, import_run_id=None,
        )
        result = chunk_service.receive_chunk(
            upload_id="u5", chunk_index=1, total_chunks=2, chunk_text="BBB",
            project_id=1, import_run_id=None,
        )
        self.assertEqual(result["screenplay_text"], "AAABBB")

    def test_invalid_total_chunks_is_rejected(self):
        with self.assertRaises(chunk_service.ChunkedUploadError) as ctx:
            chunk_service.receive_chunk(
                upload_id="u6", chunk_index=0, total_chunks=0, chunk_text="x",
                project_id=1, import_run_id=None,
            )
        self.assertEqual(ctx.exception.category, "invalid_chunk_count")

    def test_chunk_index_out_of_range_is_rejected(self):
        with self.assertRaises(chunk_service.ChunkedUploadError) as ctx:
            chunk_service.receive_chunk(
                upload_id="u7", chunk_index=5, total_chunks=3, chunk_text="x",
                project_id=1, import_run_id=None,
            )
        self.assertEqual(ctx.exception.category, "invalid_chunk_index")

    def test_oversized_chunk_is_rejected(self):
        with self.assertRaises(chunk_service.ChunkedUploadError) as ctx:
            chunk_service.receive_chunk(
                upload_id="u8", chunk_index=0, total_chunks=1,
                chunk_text="x" * (chunk_service.MAX_CHUNK_CHARS + 1),
                project_id=1, import_run_id=None,
            )
        self.assertEqual(ctx.exception.category, "chunk_too_large")

    def test_mismatched_total_chunks_mid_upload_is_rejected(self):
        chunk_service.receive_chunk(
            upload_id="u9", chunk_index=0, total_chunks=3, chunk_text="AAA",
            project_id=1, import_run_id=None,
        )
        with self.assertRaises(chunk_service.ChunkedUploadError) as ctx:
            chunk_service.receive_chunk(
                upload_id="u9", chunk_index=1, total_chunks=5, chunk_text="BBB",
                project_id=1, import_run_id=None,
            )
        self.assertEqual(ctx.exception.category, "upload_mismatch")

    def test_mismatched_project_id_mid_upload_is_rejected(self):
        chunk_service.receive_chunk(
            upload_id="u10", chunk_index=0, total_chunks=2, chunk_text="AAA",
            project_id=1, import_run_id=None,
        )
        with self.assertRaises(chunk_service.ChunkedUploadError) as ctx:
            chunk_service.receive_chunk(
                upload_id="u10", chunk_index=1, total_chunks=2, chunk_text="BBB",
                project_id=2, import_run_id=None,
            )
        self.assertEqual(ctx.exception.category, "upload_mismatch")

    def test_mismatched_import_run_id_mid_upload_is_rejected(self):
        chunk_service.receive_chunk(
            upload_id="u11", chunk_index=0, total_chunks=2, chunk_text="AAA",
            project_id=1, import_run_id=7,
        )
        with self.assertRaises(chunk_service.ChunkedUploadError) as ctx:
            chunk_service.receive_chunk(
                upload_id="u11", chunk_index=1, total_chunks=2, chunk_text="BBB",
                project_id=1, import_run_id=8,
            )
        self.assertEqual(ctx.exception.category, "upload_mismatch")

    def test_expired_pending_upload_is_swept_and_starts_fresh(self):
        chunk_service.receive_chunk(
            upload_id="u12", chunk_index=0, total_chunks=2, chunk_text="AAA",
            project_id=1, import_run_id=None,
        )
        # Simulate the TTL having elapsed without waiting real time.
        chunk_service._pending["u12"].created_at -= (chunk_service.UPLOAD_TTL_SECONDS + 1)

        # A fresh chunk_index=0 for the same id now starts a brand new
        # upload rather than being rejected as inconsistent with the
        # abandoned one.
        result = chunk_service.receive_chunk(
            upload_id="u12", chunk_index=0, total_chunks=1, chunk_text="fresh",
            project_id=1, import_run_id=None,
        )
        self.assertTrue(result["completed"])
        self.assertEqual(result["screenplay_text"], "fresh")


if __name__ == "__main__":
    unittest.main()
