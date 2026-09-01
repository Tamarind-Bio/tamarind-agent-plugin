"""Safety and transport guards for the CLI Custom Tool deployment skill."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/tamarind-cli/skills/tamarind-custom-tool-deploy"


def _docs() -> str:
    return "\n".join(path.read_text() for path in sorted(SKILL.rglob("*.md")))


def test_skill_requires_the_released_custom_tools_cli_contract() -> None:
    text = (SKILL / "SKILL.md").read_text()
    assert "tamarind-cli>=0.4.0" in text
    for command in (
        "custom-tools list",
        "custom-tools create",
        "custom-tools get",
        "custom-tools validate",
        "custom-tools build",
        "custom-tools version",
        "custom-tools logs",
        "custom-tools versions",
        "custom-tools publish",
    ):
        assert command in text


def test_tool_identity_uses_exact_lookup_and_typed_branching() -> None:
    text = (SKILL / "SKILL.md").read_text()
    section = text.split("## Select the exact tool safely", 1)[1].split(
        "## Build once", 1
    )[0]

    assert "custom-tools get TOOL" in section
    assert "custom-tools list" in section
    assert "not the first page" in section
    assert "| `0` |" in section and "do not call `create`" in section
    assert "| `4` |" in section and "Confirm the name is unclaimed" in section
    assert "Any other nonzero value" in section and "Stop and handle the error" in section
    assert section.index("custom-tools get TOOL") < section.index("custom-tools create TOOL")


def test_finite_collections_and_exact_reads_are_distinguished() -> None:
    text = (SKILL / "SKILL.md").read_text()
    for command in ("`custom-tools list`", "`versions`"):
        assert command in text
    assert "`custom-tools list` and `versions` each return one page" in text
    assert "Follow `nextCursor` with `--cursor` until it is `null`" in text
    assert "Use `get TOOL` and `version TOOL VERSION_ID` for exact identity checks" in text


def test_log_tail_defers_monitoring_and_handles_a_stalled_cursor() -> None:
    text = (SKILL / "SKILL.md").read_text()
    log_guidance = text.split("Each logs call reads one page", 1)[1].split(
        "Only `status", 1
    )[0]

    assert "Do not turn `logs` into the build monitor" in log_guidance
    assert "`version --wait` owns bounded polling" in log_guidance
    assert "only when `nextCursor` advances" in log_guidance
    assert "repeated non-null cursor means no new logs" in log_guidance
    assert "do not call `logs` again immediately" in log_guidance
    assert "sleep before reattaching" in log_guidance
    assert "process-level or CI deadline" in log_guidance
    assert "null cursor on a terminal Version" in log_guidance


def test_build_is_idempotent_bounded_and_reattachable() -> None:
    text = (SKILL / "SKILL.md").read_text()
    assert "--idempotency-key RELEASE_KEY --wait --timeout 1800 --poll-interval 10" in text
    assert "never issue a build with a new key" in text
    assert "same idempotency key" in text
    assert "timeout starts after the initial Tool and Version reads" in text
    assert "bound monitoring only, not the full process" in text
    assert "process-level or CI deadline" in text
    assert "Exit 7 means only that monitoring timed out" in text
    assert "version.name" in text and "display-only" in text


def test_wait_error_context_matches_each_phase() -> None:
    text = (SKILL / "SKILL.md").read_text()
    build_phase = text.split("Once build admission returns a Version", 1)[1].split(
        "For `version --wait`", 1
    )[0]
    reattach_phase = text.split("For `version --wait`", 1)[1].split(
        "Exit 7", 1
    )[0]

    for field in ("`toolName`", "`versionId`", "`versionName`", "`action`"):
        assert field in build_phase
    for field in ("`toolName`", "`versionId`", "`versionName`"):
        assert field in reattach_phase
    assert "no `action`" in reattach_phase
    assert "Until build admission returns a Version, a failure cannot carry" in text


def test_mutations_keep_confirmation_and_opaque_identity_boundaries() -> None:
    text = (SKILL / "SKILL.md").read_text()
    assert "custom-tools cancel TOOL VERSION_ID --yes" in text
    assert "custom-tools delete TOOL --yes" in text
    assert "custom-tools publish TOOL VERSION_ID" in text
    assert "Only `status == \"Complete\"` with `error: null` is success" in text
    assert "older `Complete` version" in text


def test_cli_skill_does_not_mix_transports_or_depend_on_github_connection() -> None:
    text = _docs()
    assert not re.search(r"\b(?:deployCustomTool|getCustomTool|submitJob|validateJob)\s*\(", text)
    assert "x-api-key" not in text.lower()
    assert "https://app.tamarind.bio/api" not in text
    assert "GitHub connection and push-to-deploy are outside this skill" in text


def test_local_validation_and_runtime_contract_are_explicit() -> None:
    text = _docs()
    assert "This command is local and does not upload source" in text
    assert "run_script_missing" in text
    assert "/app/inputs/" in text
    assert "/app/out/" in text
    assert "Runtime network access is blocked" in text
