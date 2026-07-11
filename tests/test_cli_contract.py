from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest


CLI = os.environ.get("TAMARIND_CLI") or shutil.which("tamarind")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    assert CLI
    return subprocess.run([CLI, *args], text=True, capture_output=True, check=False)


@pytest.mark.skipif(not CLI, reason="tamarind CLI is not installed")
def test_supported_cli_version_and_root_options() -> None:
    version = _run("--version")
    assert version.returncode == 0
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version.stdout)
    assert match
    assert (0, 1, 4) <= tuple(map(int, match.groups())) < (0, 2, 0)

    help_result = _run("--help")
    assert help_result.returncode == 0
    for token in ("--json", "--no-json", "--profile", "auth", "validate", "submit", "wait"):
        assert token in help_result.stdout


@pytest.mark.skipif(not CLI, reason="tamarind CLI is not installed")
@pytest.mark.parametrize(
    ("args", "tokens"),
    [
        (("wait", "--help"), ("--timeout", "--poll-interval")),
        (("submit", "--help"), ("--input", "--name")),
        (("results", "--help"), ("--download", "--file")),
        (("batch", "--help"), ("--input", "--name")),
        (("files", "upload", "--help"), ("--name",)),
    ],
)
def test_documented_cli_flags_exist(args: tuple[str, ...], tokens: tuple[str, ...]) -> None:
    result = _run(*args)
    assert result.returncode == 0, result.stderr
    for token in tokens:
        assert token in result.stdout
