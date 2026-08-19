"""Coverage for app.services.visual_continuity_vision — the pure AI visual
continuity comparison, and app.services.openai_identity_vision-style OpenAI
adapter it ships with.
"""

import unittest
from unittest.mock import Mock

import httpx

from app.services.visual_continuity_vision import (
    OpenAIVisualContinuityAdapter,
    assess_visual_continuity,
)

_REAL_HTTPX_CLIENT = httpx.Client


def _mock_transport(handler):
    return httpx.MockTransport(handler)


class AssessVisualContinuityTests(unittest.TestCase):
    def test_high_score_no_flags_returns_no_issues(self):
        adapter = Mock()
        adapter.compare_continuity.return_value = {
            "continuity_score": 0.95, "flags": [], "evidence": {}, "provider": "openai", "model": "m",
        }
        issues = assess_visual_continuity(
            current_url="https://example.com/a.png", neighbor_url="https://example.com/b.png",
            adapter=adapter, relation="הקודם", neighbor_shot_id=1, neighbor_shot_number=1,
        )
        self.assertEqual(issues, [])

    def test_low_score_returns_high_severity_issue(self):
        adapter = Mock()
        adapter.compare_continuity.return_value = {
            "continuity_score": 0.2, "flags": ["wardrobe_changed"], "evidence": {"summary": "x"},
            "provider": "openai", "model": "m",
        }
        issues = assess_visual_continuity(
            current_url="https://example.com/a.png", neighbor_url="https://example.com/b.png",
            adapter=adapter, relation="הבא", neighbor_shot_id=2, neighbor_shot_number=3,
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "high")
        self.assertEqual(issues[0]["category"], "ai_visual_continuity")
        self.assertEqual(issues[0]["neighbor_shot_id"], 2)
        self.assertIn("wardrobe_changed", issues[0]["flags"])

    def test_uncertain_flag_with_high_score_is_low_severity(self):
        adapter = Mock()
        adapter.compare_continuity.return_value = {
            "continuity_score": 0.9, "flags": ["uncertain_comparison"], "evidence": {},
            "provider": "openai", "model": "m",
        }
        issues = assess_visual_continuity(
            current_url="https://example.com/a.png", neighbor_url="https://example.com/b.png",
            adapter=adapter, relation="הקודם", neighbor_shot_id=5, neighbor_shot_number=5,
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "low")


class OpenAIVisualContinuityAdapterTests(unittest.TestCase):
    def _adapter(self, handler):
        client = _REAL_HTTPX_CLIENT(transport=_mock_transport(handler))
        return OpenAIVisualContinuityAdapter(api_key="sk-test", model="m", client=client)

    def test_missing_api_key_raises(self):
        adapter = OpenAIVisualContinuityAdapter(api_key="")
        with self.assertRaises(RuntimeError):
            adapter.compare_continuity(current_url="a", neighbor_url="b")

    def test_empty_urls_raise(self):
        adapter = self._adapter(lambda r: httpx.Response(200))
        with self.assertRaises(ValueError):
            adapter.compare_continuity(current_url="", neighbor_url="b")

    def test_parses_valid_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "output_text": '{"continuity_score": 0.4, "flags": ["lighting_changed"], "evidence": {"summary": "s"}}'
            })

        adapter = self._adapter(handler)
        result = adapter.compare_continuity(current_url="https://a", neighbor_url="https://b")
        self.assertEqual(result["continuity_score"], 0.4)
        self.assertEqual(result["flags"], ["lighting_changed"])
        self.assertEqual(result["provider"], "openai")

    def test_out_of_range_score_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"output_text": '{"continuity_score": 1.5, "flags": []}'})

        adapter = self._adapter(handler)
        with self.assertRaises(ValueError):
            adapter.compare_continuity(current_url="https://a", neighbor_url="https://b")


if __name__ == "__main__":
    unittest.main()
