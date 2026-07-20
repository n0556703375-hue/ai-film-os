import unittest
from unittest.mock import Mock

from app.services.openai_identity_vision import OpenAIIdentityVisionAdapter


class OpenAIIdentityVisionAdapterTests(unittest.TestCase):
    def _client_with_body(self, body):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = body
        client = Mock()
        client.post.return_value = response
        return client

    def test_compares_two_images_and_normalizes_result(self):
        client = self._client_with_body({
            "output": [{
                "content": [{
                    "type": "output_text",
                    "text": '{"identity_similarity":0.91,"flags":["hair_changed","hair_changed"],"evidence":{"summary":"same identity"}}',
                }]
            }]
        })
        adapter = OpenAIIdentityVisionAdapter(
            api_key="test-key",
            model="vision-test",
            api_base="https://api.example.test/v1",
            client=client,
        )

        result = adapter.compare_identity(
            reference_url="https://example.test/master.jpg",
            candidate_url="https://example.test/shot.jpg",
        )

        self.assertEqual(result["identity_similarity"], 0.91)
        self.assertEqual(result["flags"], ["hair_changed"])
        self.assertEqual(result["provider"], "openai")
        self.assertEqual(result["model"], "vision-test")
        request = client.post.call_args
        self.assertEqual(request.args[0], "https://api.example.test/v1/responses")
        self.assertEqual(request.kwargs["headers"]["Authorization"], "Bearer test-key")
        content = request.kwargs["json"]["input"][0]["content"]
        self.assertEqual(content[1]["image_url"], "https://example.test/master.jpg")
        self.assertEqual(content[2]["image_url"], "https://example.test/shot.jpg")

    def test_requires_api_key_without_making_request(self):
        client = Mock()
        adapter = OpenAIIdentityVisionAdapter(api_key="", client=client)

        with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
            adapter.compare_identity(
                reference_url="https://example.test/master.jpg",
                candidate_url="https://example.test/shot.jpg",
            )
        client.post.assert_not_called()

    def test_rejects_invalid_score(self):
        client = self._client_with_body({"output_text": '{"identity_similarity":1.2,"flags":[]}'})
        adapter = OpenAIIdentityVisionAdapter(api_key="test-key", client=client)

        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            adapter.compare_identity(
                reference_url="https://example.test/master.jpg",
                candidate_url="https://example.test/shot.jpg",
            )

    def test_rejects_non_json_provider_output(self):
        client = self._client_with_body({"output_text": "not-json"})
        adapter = OpenAIIdentityVisionAdapter(api_key="test-key", client=client)

        with self.assertRaisesRegex(ValueError, "valid JSON"):
            adapter.compare_identity(
                reference_url="https://example.test/master.jpg",
                candidate_url="https://example.test/shot.jpg",
            )


if __name__ == "__main__":
    unittest.main()
