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


def test_build_is_idempotent_bounded_and_reattachable() -> None:
    text = (SKILL / "SKILL.md").read_text()
    assert "--idempotency-key RELEASE_KEY --wait --timeout 1800 --poll-interval 10" in text
    assert "Never automatically repeat an ambiguous build command" in text
    assert "versionId" in text
    assert "Exit 7" in text
    assert "version.name" in text and "display-only" in text


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
