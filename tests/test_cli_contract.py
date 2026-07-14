from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest


CLI = os.environ.get("TAMARIND_CLI") or shutil.which("tamarind")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# The last tamarind-cli minor this plugin's contract was verified against. CI installs
# the latest published release, so when the CLI moves past this minor the version test
# skips (a "re-verify the contract and bump" nudge) instead of hard-failing on a crossed
# version literal. Behavioral help-token checks below still run and fail honestly if a
# real flag/command actually changed.
LAST_VERIFIED_CLI_MINOR = (0, 2)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    assert CLI
    return subprocess.run([CLI, *args], text=True, capture_output=True, check=False)


def _plain(text: str) -> str:
    """Remove terminal styling before asserting semantic help content."""
    return ANSI_ESCAPE.sub("", text)


@pytest.mark.skipif(not CLI, reason="tamarind CLI is not installed")
def test_supported_cli_version_and_root_options() -> None:
    version = _run("--version")
    assert version.returncode == 0
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version.stdout)
    assert match
    version_tuple = tuple(map(int, match.groups()))
    # Hard floor: the plugin's skills depend on the 0.2.0 agent contract.
    assert version_tuple >= (0, 2, 0), (
        f"plugin requires tamarind-cli >= 0.2.0, found {version.stdout.strip()}"
    )

    help_result = _run("--help")
    assert help_result.returncode == 0
    help_text = _plain(help_result.stdout)
    for token in ("--json", "--no-json", "--profile", "auth", "validate", "submit", "wait"):
        assert token in help_text

    # Soft ceiling: a newer minor may have changed the contract, but because README and
    # CI install the latest release, a new tamarind-cli must not turn every run red on a
    # crossed version literal alone. Once the CLI moves past the last verified minor,
    # skip here (re-verify + bump LAST_VERIFIED_CLI_MINOR) rather than hard-failing.
    if version_tuple[:2] > LAST_VERIFIED_CLI_MINOR:
        pytest.skip(
            f"tamarind-cli {version_tuple[0]}.{version_tuple[1]} is newer than the last "
            f"contract-verified minor {LAST_VERIFIED_CLI_MINOR[0]}.{LAST_VERIFIED_CLI_MINOR[1]}; "
            "re-verify the plugin contract against it and bump LAST_VERIFIED_CLI_MINOR."
        )


@pytest.mark.skipif(not CLI, reason="tamarind CLI is not installed")
@pytest.mark.parametrize(
    ("args", "tokens"),
    [
        (("wait", "--help"), ("--timeout", "--poll-interval")),
        (("submit", "--help"), ("--input", "--name")),
        (("results", "--help"), ("--download", "--file", "--show-url")),
        (("batch", "--help"), ("--input", "--name", "--prevalidate")),
        (("files", "upload", "--help"), ("--name",)),
    ],
)
def test_documented_cli_flags_exist(args: tuple[str, ...], tokens: tuple[str, ...]) -> None:
    result = _run(*args)
    assert result.returncode == 0, result.stderr
    help_text = _plain(result.stdout)
    for token in tokens:
        assert token in help_text


@pytest.mark.skipif(not CLI, reason="tamarind CLI is not installed")
def test_cli_02_results_has_explicit_url_escape_hatch() -> None:
    result = _run("results", "--help")
    assert result.returncode == 0
    assert "--show-url" in _plain(result.stdout)


@pytest.mark.skipif(not CLI, reason="tamarind CLI is not installed")
def test_cli_02_batch_has_final_row_prevalidation() -> None:
    result = _run("batch", "--help")
    assert result.returncode == 0
    assert "--prevalidate" in _plain(result.stdout)
