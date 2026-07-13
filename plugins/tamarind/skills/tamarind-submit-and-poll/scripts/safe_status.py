#!/usr/bin/env python3
"""Run one Tamarind CLI status probe without leaking transfer URLs.

This is a CLI 0.1 compatibility filter, not an API client. It launches the
official executable without a shell, preserves its nonzero exit code and
stderr, and only parses/redacts stdout after a successful status response.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


BLOCKED_KEYS = {
    "resulturl",
    "downloadurl",
    "presignedurl",
    "uploadurl",
    "headurl",
}
STATUS_TIMEOUT_SECONDS = 130


def scrub(value):
    """Recursively remove credential-bearing URL fields from CLI output."""
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if not isinstance(value, dict):
        return value

    cleaned = {}
    removed = []
    for key, item in value.items():
        if str(key).lower() in BLOCKED_KEYS:
            removed.append(str(key))
            continue
        cleaned[key] = scrub(item)
    if removed:
        cleaned["redactedFields"] = sorted(removed)
    return cleaned


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_name", help="Durable Tamarind job or batch name")
    parser.add_argument(
        "--cli",
        default=os.environ.get("TAMARIND_CLI", "tamarind"),
        help="Tamarind executable (default: TAMARIND_CLI or tamarind)",
    )
    args = parser.parse_args(argv)

    try:
        process = subprocess.run(
            [args.cli, "--json", "status", args.job_name],
            text=True,
            capture_output=True,
            check=False,
            timeout=STATUS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(
            f"error: status probe exceeded {STATUS_TIMEOUT_SECONDS}s; "
            "the remote job may still be running",
            file=sys.stderr,
        )
        return 7
    except OSError as exc:
        print(f"error: could not run Tamarind CLI: {exc}", file=sys.stderr)
        return 127

    if process.stderr:
        sys.stderr.write(process.stderr)
    if process.returncode:
        # Do not parse empty stdout or echo a partial/sensitive response.
        return process.returncode

    try:
        payload = json.loads(process.stdout)
    except (TypeError, json.JSONDecodeError):
        print(
            "error: Tamarind CLI status succeeded without valid JSON output",
            file=sys.stderr,
        )
        return 1

    try:
        rendered = json.dumps(scrub(payload), indent=2, allow_nan=False)
    except (TypeError, ValueError):
        print(
            "error: Tamarind CLI status returned unsupported JSON values",
            file=sys.stderr,
        )
        return 1

    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
