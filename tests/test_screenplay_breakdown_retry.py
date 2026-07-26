import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.screenplay_breakdown import (
    MAX_PROVIDER_ATTEMPTS,
    PROVIDER_TIMEOUT_SECONDS,
    _request_breakdown,
)


class _TransientProviderError(Exception):
    pass


class ScreenplayBreakdownRetryTests(unittest.TestCase):
    @patch(
        "app.services.screenplay_breakdown.TRANSIENT_PROVIDER_ERRORS",
        (_TransientProviderError,),
    )
    @patch("app.services.screenplay_breakdown._openai_client")
    def test_retries_one_transient_failure_and_keeps_each_attempt_bounded(
        self, client_factory
    ):
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise _TransientProviderError("temporary timeout")
            return SimpleNamespace(output_text='[{"title":"א"}]')

        client_factory.return_value = SimpleNamespace(
            responses=SimpleNamespace(create=create)
        )

        response = _request_breakdown("prompt")

        self.assertEqual(response.output_text, '[{"title":"א"}]')
        self.assertEqual(MAX_PROVIDER_ATTEMPTS, 2)
        self.assertEqual(len(calls), 2)
        self.assertTrue(
            all(call["timeout"] == PROVIDER_TIMEOUT_SECONDS for call in calls)
        )
        self.assertLessEqual(
            PROVIDER_TIMEOUT_SECONDS * MAX_PROVIDER_ATTEMPTS,
            40.0,
        )

    @patch(
        "app.services.screenplay_breakdown.TRANSIENT_PROVIDER_ERRORS",
        (_TransientProviderError,),
    )
    @patch("app.services.screenplay_breakdown._openai_client")
    def test_stops_after_the_bounded_retry_budget(self, client_factory):
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            raise _TransientProviderError("still unavailable")

        client_factory.return_value = SimpleNamespace(
            responses=SimpleNamespace(create=create)
        )

        with self.assertRaisesRegex(_TransientProviderError, "still unavailable"):
            _request_breakdown("prompt")

        self.assertEqual(len(calls), MAX_PROVIDER_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
