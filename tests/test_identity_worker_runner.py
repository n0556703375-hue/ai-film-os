import unittest
from unittest.mock import Mock, patch

from app.services.identity_worker_runner import (
    build_identity_vision_adapter,
    process_next_identity_assessment,
)
from app.services.openai_identity_vision import OpenAIIdentityVisionAdapter


class IdentityWorkerRunnerTests(unittest.TestCase):
    def test_factory_builds_openai_adapter(self):
        adapter = build_identity_vision_adapter("openai")
        self.assertIsInstance(adapter, OpenAIIdentityVisionAdapter)

    def test_factory_rejects_unknown_provider(self):
        with self.assertRaisesRegex(ValueError, "Unsupported identity vision provider"):
            build_identity_vision_adapter("unknown")

    @patch("app.services.identity_worker_runner.list_pending_identity_drift")
    def test_empty_queue_returns_without_building_adapter(self, list_pending):
        list_pending.return_value = {"items": [], "count": 0}

        result = process_next_identity_assessment(worker_id="worker-1")

        self.assertEqual(
            result,
            {"processed": False, "reason": "no_pending_identity_assessments"},
        )
        list_pending.assert_called_once_with(limit=1)

    @patch("app.services.identity_worker_runner.process_identity_assessment")
    @patch("app.services.identity_worker_runner.list_pending_identity_drift")
    def test_processes_oldest_pending_item_with_supplied_adapter(
        self,
        list_pending,
        process_identity,
    ):
        adapter = Mock()
        list_pending.return_value = {
            "items": [{"shot_id": 7, "media_id": 12, "url": "https://example.test/image.png"}],
            "count": 1,
        }
        process_identity.return_value = {
            "shot_id": 7,
            "media_id": 12,
            "worker_id": "worker-1",
            "identity_drift": {"status": "passed", "passed": True},
        }

        result = process_next_identity_assessment(
            worker_id=" worker-1 ",
            adapter=adapter,
        )

        self.assertTrue(result["processed"])
        process_identity.assert_called_once_with(
            shot_id=7,
            media_id=12,
            worker_id="worker-1",
            adapter=adapter,
        )

    def test_requires_non_empty_worker_id(self):
        with self.assertRaisesRegex(ValueError, "worker_id is required"):
            process_next_identity_assessment(worker_id="   ")


if __name__ == "__main__":
    unittest.main()
