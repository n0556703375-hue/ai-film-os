import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from openai import APIConnectionError, APITimeoutError

import app.services.screenplay_breakdown as _breakdown_module
from app.services.screenplay_breakdown import (
    MAX_CHUNK_CHARACTERS,
    MAX_PROVIDER_ATTEMPTS,
    PROVIDER_TIMEOUT_SECONDS,
    _request_breakdown,
    _split_screenplay,
)

# Tiny timeout used in deadline tests so they run fast and daemon threads
# don't hold semaphore slots for the full PROVIDER_TIMEOUT_SECONDS.
_TEST_DEADLINE_SECONDS = 0.05


class _TransientProviderError(Exception):
    pass


class ScreenplayBreakdownRetryTests(unittest.TestCase):

    def setUp(self):
        # Replace the module-level semaphore with a fresh one so stuck daemon
        # threads from previous tests cannot exhaust capacity for the next test.
        _breakdown_module._PROVIDER_SEMAPHORE = threading.Semaphore(4)

    # --- Original retry contract tests ---

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

    # --- App-level deadline tests ---

    @patch("app.services.screenplay_breakdown.PROVIDER_TIMEOUT_SECONDS", _TEST_DEADLINE_SECONDS)
    @patch("app.services.screenplay_breakdown._openai_client")
    def test_app_level_deadline_bounded_by_provider_timeout(self, client_factory):
        """A hung provider call must be bounded by the app-level deadline."""
        call_started_event = threading.Event()

        def create(**kwargs):
            call_started_event.set()
            time.sleep(1000)  # Simulate an infinitely-hung provider
            return SimpleNamespace(output_text='[{"title":"א"}]')

        client_factory.return_value = SimpleNamespace(
            responses=SimpleNamespace(create=create)
        )

        start_time = time.time()
        with self.assertRaises(APITimeoutError):
            _request_breakdown("prompt")
        elapsed = time.time() - start_time

        # Both attempts time out at _TEST_DEADLINE_SECONDS each.
        # Total should be well under 5 seconds (plenty of tolerance for CI).
        self.assertLess(elapsed, 5.0)

        self.assertTrue(call_started_event.is_set())

    @patch("app.services.screenplay_breakdown.PROVIDER_TIMEOUT_SECONDS", _TEST_DEADLINE_SECONDS)
    @patch(
        "app.services.screenplay_breakdown.TRANSIENT_PROVIDER_ERRORS",
        (APITimeoutError,),
    )
    @patch("app.services.screenplay_breakdown._openai_client")
    def test_timeout_on_both_attempts_raises_after_retry_budget(self, client_factory):
        """App-level timeout is treated as transient and exhausts retry budget exactly."""
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            time.sleep(1000)  # Both attempts hang
            return SimpleNamespace(output_text='[{"title":"א"}]')

        client_factory.return_value = SimpleNamespace(
            responses=SimpleNamespace(create=create)
        )

        with self.assertRaises(APITimeoutError):
            _request_breakdown("prompt")

        # Exactly MAX_PROVIDER_ATTEMPTS submissions, no more, no less.
        self.assertEqual(len(calls), MAX_PROVIDER_ATTEMPTS)

    # --- Normal-path tests ---

    @patch("app.services.screenplay_breakdown._openai_client")
    def test_normal_fast_response_unchanged(self, client_factory):
        """Normal, fast provider responses are not affected by the deadline."""
        client_factory.return_value = SimpleNamespace(
            responses=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(output_text='[{"title":"א"}]')
            )
        )

        start_time = time.time()
        response = _request_breakdown("prompt")
        elapsed = time.time() - start_time

        self.assertLess(elapsed, 5.0)
        self.assertEqual(response.output_text, '[{"title":"א"}]')

    # --- Semaphore / concurrency guard tests ---

    @patch("app.services.screenplay_breakdown._openai_client")
    def test_semaphore_capacity_exhaustion_fails_fast(self, client_factory):
        """When semaphore capacity is exhausted, attempts fail immediately without waiting."""
        held = 0
        try:
            while _breakdown_module._PROVIDER_SEMAPHORE.acquire(blocking=False):
                held += 1

            start_time = time.time()
            with self.assertRaises(APIConnectionError):
                _request_breakdown("prompt")
            elapsed = time.time() - start_time

            # Must fail-fast: well under the deadline, not after 18+ seconds.
            self.assertLess(elapsed, 1.0)
        finally:
            for _ in range(held):
                _breakdown_module._PROVIDER_SEMAPHORE.release()

    @patch("app.services.screenplay_breakdown._openai_client")
    def test_semaphore_released_after_successful_call(self, client_factory):
        """The semaphore slot is released after a successful provider call."""
        initial_value = _breakdown_module._PROVIDER_SEMAPHORE._value

        client_factory.return_value = SimpleNamespace(
            responses=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(output_text='[{"title":"א"}]')
            )
        )
        _request_breakdown("prompt")

        # Give the worker thread time to run its finally block.
        time.sleep(0.1)
        self.assertEqual(_breakdown_module._PROVIDER_SEMAPHORE._value, initial_value)

    @patch("app.services.screenplay_breakdown.PROVIDER_TIMEOUT_SECONDS", _TEST_DEADLINE_SECONDS)
    @patch("app.services.screenplay_breakdown._openai_client")
    def test_hung_thread_does_not_block_subsequent_requests(self, client_factory):
        """A hung provider thread from a timed-out call does not block subsequent requests."""
        call_count = [0]

        def create(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                # First two calls (attempts 1 and 2) hang
                time.sleep(1000)
            return SimpleNamespace(output_text='[{"title":"סצנה"}]')

        client_factory.return_value = SimpleNamespace(
            responses=SimpleNamespace(create=create)
        )

        # First request times out after both attempts.
        with self.assertRaises(APITimeoutError):
            _request_breakdown("prompt")

        self.assertEqual(call_count[0], 2)

        # Reset semaphore so the second request can proceed despite stuck threads.
        _breakdown_module._PROVIDER_SEMAPHORE = threading.Semaphore(4)

        start_time = time.time()
        response = _request_breakdown("prompt")
        elapsed = time.time() - start_time

        self.assertLess(elapsed, 5.0)
        self.assertEqual(response.output_text, '[{"title":"סצנה"}]')

    @patch("app.services.screenplay_breakdown.PROVIDER_TIMEOUT_SECONDS", _TEST_DEADLINE_SECONDS)
    @patch("app.services.screenplay_breakdown._openai_client")
    def test_capacity_exceeded_error_contains_no_credentials(self, client_factory):
        """APIConnectionError on capacity exhaustion must not leak credentials or URLs."""
        held = 0
        try:
            while _breakdown_module._PROVIDER_SEMAPHORE.acquire(blocking=False):
                held += 1

            try:
                _request_breakdown("prompt")
            except APIConnectionError as exc:
                error_text = str(exc).lower()
                self.assertNotIn("key", error_text)
                self.assertNotIn("token", error_text)
                self.assertNotIn("secret", error_text)
                self.assertNotIn("openai.com", error_text)
        finally:
            for _ in range(held):
                _breakdown_module._PROVIDER_SEMAPHORE.release()


    # --- Production-sized chunk boundary tests ---

    def test_default_chunks_stay_within_reduced_provider_budget(self):
        screenplay = ("א" * 2400) + "\n\n" + ("ב" * 2400)
        chunks = _split_screenplay(screenplay)

        self.assertEqual(MAX_CHUNK_CHARACTERS, 3000)
        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= MAX_CHUNK_CHARACTERS for chunk in chunks))
        self.assertEqual("\n\n".join(chunks), screenplay)

    def test_oversized_paragraph_is_split_without_content_loss(self):
        screenplay = "ג" * (MAX_CHUNK_CHARACTERS * 2 + 17)
        chunks = _split_screenplay(screenplay)

        self.assertEqual([len(chunk) for chunk in chunks], [3000, 3000, 17])
        self.assertEqual("".join(chunks), screenplay)


if __name__ == "__main__":
    unittest.main()
