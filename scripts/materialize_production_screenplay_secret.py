#!/usr/bin/env python3
"""Reconstruct and decode the production screenplay smoke secret without logging it.

GitHub repository secrets have a size limit that a full-length screenplay's
base64 encoding can exceed ("Value is too large."). This script supports two
configurations, checked in this order:

1. A single secret, ``PRODUCTION_SMOKE_SCREENPLAY_B64`` (existing behavior,
   used exactly as before when present).
2. Two split secrets, ``PRODUCTION_SMOKE_SCREENPLAY_B64_PART1`` and
   ``PRODUCTION_SMOKE_SCREENPLAY_B64_PART2``, concatenated as PART1 + PART2
   before decoding, for payloads too large for a single secret.

Decoding, empty-result validation, and error messages are unchanged from the
original single-secret implementation. This script never prints screenplay
content, decoded bytes, or secret values - only generic error messages that
describe what went wrong, matching the no-credential/no-content-leak
discipline used by the rest of the deployment tooling in this directory.
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

from scripts.deployment_smoke import SmokeFailure


def resolve_encoded_screenplay(env: dict[str, str]) -> str:
    """Return the reconstructed base64 payload from whichever secret(s) are set.

    Prefers the single secret exactly as today; falls back to concatenating
    the two split parts. Raises SmokeFailure if neither is fully configured.
    """
    single = env.get("SCREENPLAY_B64", "").strip()
    if single:
        return single

    part1 = env.get("SCREENPLAY_B64_PART1", "").strip()
    part2 = env.get("SCREENPLAY_B64_PART2", "").strip()
    if part1 and part2:
        return part1 + part2

    raise SmokeFailure(
        "Missing required secret: set PRODUCTION_SMOKE_SCREENPLAY_B64, or both "
        "PRODUCTION_SMOKE_SCREENPLAY_B64_PART1 and PRODUCTION_SMOKE_SCREENPLAY_B64_PART2."
    )


def decode_screenplay(encoded: str) -> bytes:
    """Decode and validate the reconstructed base64 payload. Unchanged from
    the original single-secret validation: same error conditions, same
    messages, decode happens only after the full payload is reconstructed."""
    try:
        screenplay = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise SmokeFailure(f"screenplay secret is not valid base64: {exc}") from None
    if not screenplay.strip():
        raise SmokeFailure("Decoded screenplay is empty")
    return screenplay


def materialize_screenplay(env: dict[str, str], output_path: Path) -> None:
    """Resolve, decode, and write the screenplay. Never logs its content."""
    encoded = resolve_encoded_screenplay(env)
    screenplay = decode_screenplay(encoded)
    output_path.write_bytes(screenplay)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        materialize_screenplay(dict(os.environ), args.output)
    except SmokeFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
