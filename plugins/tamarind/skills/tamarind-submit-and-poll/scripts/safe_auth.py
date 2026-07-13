#!/usr/bin/env python3
"""Verify Tamarind CLI auth without printing any credential fragment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


ALLOWED_FIELDS = ("hasKey", "verified")
AUTH_TIMEOUT_SECONDS = 130


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cli",
        default=os.environ.get("TAMARIND_CLI", "tamarind"),
        help="Tamarind executable (default: TAMARIND_CLI or tamarind)",
    )
    args = parser.parse_args(argv)

    try:
        process = subprocess.run(
            [args.cli, "--json", "auth", "status"],
            text=True,
            capture_output=True,
            check=False,
            timeout=AUTH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(
            f"error: auth verification exceeded {AUTH_TIMEOUT_SECONDS}s",
            file=sys.stderr,
        )
        return 7
    except OSError as exc:
        print(f"error: could not run Tamarind CLI: {exc}", file=sys.stderr)
        return 127

    if process.stderr:
        sys.stderr.write(process.stderr)
    if process.returncode:
        return process.returncode

    try:
        payload = json.loads(process.stdout)
    except (TypeError, json.JSONDecodeError):
        print(
            "error: Tamarind CLI auth status succeeded without valid JSON output",
            file=sys.stderr,
        )
        return 1
    if not isinstance(payload, dict):
        print(
            "error: Tamarind CLI auth status returned an unexpected JSON shape",
            file=sys.stderr,
        )
        return 1

    safe = {key: payload[key] for key in ALLOWED_FIELDS if key in payload}
    print(json.dumps(safe, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
