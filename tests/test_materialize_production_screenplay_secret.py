import base64
import tempfile
import unittest
from pathlib import Path

from scripts.deployment_smoke import SmokeFailure
from scripts.materialize_production_screenplay_secret import (
    decode_screenplay,
    main,
    materialize_screenplay,
    resolve_encoded_screenplay,
)

SCREENPLAY_TEXT = "סצנה 1 - פנים - משרד - יום\n\nתיאור קצר של הסצנה." * 5
ENCODED = base64.b64encode(SCREENPLAY_TEXT.encode("utf-8")).decode("ascii")


class ResolveEncodedScreenplayTests(unittest.TestCase):
    def test_single_secret_path_is_used_exactly_as_today(self):
        result = resolve_encoded_screenplay({"SCREENPLAY_B64": ENCODED})
        self.assertEqual(result, ENCODED)

    def test_single_secret_takes_priority_over_split_parts(self):
        # If both are somehow present, the existing single-secret behavior
        # must remain unchanged rather than silently switching paths.
        half = len(ENCODED) // 2
        result = resolve_encoded_screenplay({
            "SCREENPLAY_B64": ENCODED,
            "SCREENPLAY_B64_PART1": ENCODED[:half],
            "SCREENPLAY_B64_PART2": ENCODED[half:],
        })
        self.assertEqual(result, ENCODED)

    def test_split_secret_path_concatenates_part1_then_part2(self):
        half = len(ENCODED) // 2
        result = resolve_encoded_screenplay({
            "SCREENPLAY_B64_PART1": ENCODED[:half],
            "SCREENPLAY_B64_PART2": ENCODED[half:],
        })
        self.assertEqual(result, ENCODED)

    def test_missing_all_secrets_fails_with_a_clear_message(self):
        with self.assertRaises(SmokeFailure) as ctx:
            resolve_encoded_screenplay({})
        self.assertIn("PRODUCTION_SMOKE_SCREENPLAY_B64", str(ctx.exception))
        self.assertIn("PART1", str(ctx.exception))
        self.assertIn("PART2", str(ctx.exception))

    def test_only_part1_present_fails_like_missing_secret(self):
        with self.assertRaises(SmokeFailure):
            resolve_encoded_screenplay({"SCREENPLAY_B64_PART1": ENCODED})

    def test_only_part2_present_fails_like_missing_secret(self):
        with self.assertRaises(SmokeFailure):
            resolve_encoded_screenplay({"SCREENPLAY_B64_PART2": ENCODED})

    def test_blank_values_are_treated_as_unset(self):
        with self.assertRaises(SmokeFailure):
            resolve_encoded_screenplay({
                "SCREENPLAY_B64": "   ",
                "SCREENPLAY_B64_PART1": "",
                "SCREENPLAY_B64_PART2": "",
            })


class DecodeScreenplayTests(unittest.TestCase):
    def test_decodes_valid_base64(self):
        self.assertEqual(decode_screenplay(ENCODED), SCREENPLAY_TEXT.encode("utf-8"))

    def test_rejects_invalid_base64(self):
        with self.assertRaisesRegex(SmokeFailure, "not valid base64"):
            decode_screenplay("not-valid-base64!!!")

    def test_rejects_empty_decoded_content(self):
        empty_encoded = base64.b64encode(b"   ").decode("ascii")
        with self.assertRaisesRegex(SmokeFailure, "Decoded screenplay is empty"):
            decode_screenplay(empty_encoded)


class MaterializeScreenplayTests(unittest.TestCase):
    def test_single_secret_path_writes_the_decoded_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "screenplay.txt"
            materialize_screenplay({"SCREENPLAY_B64": ENCODED}, output)
            self.assertEqual(output.read_text(encoding="utf-8"), SCREENPLAY_TEXT)

    def test_split_secret_path_writes_the_same_decoded_file(self):
        half = len(ENCODED) // 2
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "screenplay.txt"
            materialize_screenplay(
                {
                    "SCREENPLAY_B64_PART1": ENCODED[:half],
                    "SCREENPLAY_B64_PART2": ENCODED[half:],
                },
                output,
            )
            self.assertEqual(output.read_text(encoding="utf-8"), SCREENPLAY_TEXT)

    def test_missing_secrets_does_not_write_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "screenplay.txt"
            with self.assertRaises(SmokeFailure):
                materialize_screenplay({}, output)
            self.assertFalse(output.exists())


class MainCliTests(unittest.TestCase):
    def test_exits_zero_and_writes_file_for_single_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "screenplay.txt"
            import os
            from unittest.mock import patch

            with patch.dict(os.environ, {"SCREENPLAY_B64": ENCODED}, clear=True):
                exit_code = main(["--output", str(output)])
            self.assertEqual(exit_code, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), SCREENPLAY_TEXT)

    def test_exits_zero_and_writes_file_for_split_secret(self):
        half = len(ENCODED) // 2
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "screenplay.txt"
            import os
            from unittest.mock import patch

            env = {"SCREENPLAY_B64_PART1": ENCODED[:half], "SCREENPLAY_B64_PART2": ENCODED[half:]}
            with patch.dict(os.environ, env, clear=True):
                exit_code = main(["--output", str(output)])
            self.assertEqual(exit_code, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), SCREENPLAY_TEXT)

    def test_exits_non_zero_and_writes_nothing_when_secrets_are_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "screenplay.txt"
            import os
            from unittest.mock import patch

            with patch.dict(os.environ, {}, clear=True):
                exit_code = main(["--output", str(output)])
            self.assertEqual(exit_code, 1)
            self.assertFalse(output.exists())

    def test_error_output_never_contains_screenplay_or_secret_content(self):
        import os
        import io
        import contextlib
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "screenplay.txt"
            captured = io.StringIO()
            with patch.dict(os.environ, {"SCREENPLAY_B64": "not-valid-base64!!!"}, clear=True):
                with contextlib.redirect_stderr(captured):
                    exit_code = main(["--output", str(output)])
            self.assertEqual(exit_code, 1)
            self.assertNotIn(SCREENPLAY_TEXT, captured.getvalue())
            self.assertNotIn("not-valid-base64", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
