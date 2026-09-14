from __future__ import annotations

import json
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
LAST_VERIFIED_CLI_MINOR = (0, 4)


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
    # Hard floor: the Custom Tool skill depends on the 0.4.0 lifecycle commands.
    assert version_tuple >= (0, 4, 0), (
        f"plugin requires tamarind-cli >= 0.4.0, found {version.stdout.strip()}"
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


# Commands the skills teach that are newer than the CLI floor. Their help rows skip
# when the installed CLI lacks the command — the skills tell agents to fall back for
# such a CLI — and run like every other row once it has it.
COMMANDS_NEWER_THAN_FLOOR = {
    "finetune": "added after tamarind-cli 0.4.3; the finetune skills fall back to `submit` without it",
}


def _lacks_command(result: subprocess.CompletedProcess[str]) -> bool:
    """The CLI's typed answer for a command it does not have: exit 2 with a
    structured `NoSuchCommand` error. Any other failure is a real contract break."""
    if result.returncode != 2:
        return False
    try:
        error = json.loads(result.stderr)["error"]
    except (ValueError, KeyError, TypeError):
        return False
    return isinstance(error, dict) and error.get("type") == "NoSuchCommand"


@pytest.mark.skipif(not CLI, reason="tamarind CLI is not installed")
@pytest.mark.parametrize(
    ("args", "tokens"),
    [
        (("wait", "--help"), ("--timeout", "--poll-interval")),
        (("submit", "--help"), ("--input", "--name")),
        (("finetune", "--help"), ("--input", "--name")),
        (("results", "--help"), ("--download", "--file", "--show-url")),
        (("batch", "--help"), ("--input", "--name", "--prevalidate")),
        (("files", "upload", "--help"), ("--name",)),
        (("custom-tools", "build", "--help"), ("--idempotency-key", "--wait", "--timeout", "--poll-interval")),
        (("custom-tools", "version", "--help"), ("--wait", "--timeout", "--poll-interval")),
        (("custom-tools", "delete", "--help"), ("--yes",)),
    ],
)
def test_documented_cli_flags_exist(args: tuple[str, ...], tokens: tuple[str, ...]) -> None:
    result = _run(*args)
    if args[0] in COMMANDS_NEWER_THAN_FLOOR and _lacks_command(result):
        pytest.skip(f"installed tamarind-cli has no `{args[0]}` command ({COMMANDS_NEWER_THAN_FLOOR[args[0]]})")
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


@pytest.mark.parametrize(
    ("returncode", "stderr", "lacks"),
    [
        (2, '{"error": {"type": "NoSuchCommand", "message": "No such command \'finetune\'.", "exitCode": 2}}', True),
        # a present command that breaks is a contract failure, never a skip
        (2, '{"error": {"type": "NoSuchOption", "message": "No such option: --input", "exitCode": 2}}', False),
        (1, '{"error": {"type": "NoSuchCommand", "message": "No such command \'finetune\'.", "exitCode": 1}}', False),
        (2, "Traceback (most recent call last): ...", False),
        (0, "", False),
    ],
)
def test_only_a_typed_missing_command_skips_a_help_row(returncode: int, stderr: str, lacks: bool) -> None:
    result = subprocess.CompletedProcess(["tamarind"], returncode, stdout="", stderr=stderr)
    assert _lacks_command(result) is lacks
