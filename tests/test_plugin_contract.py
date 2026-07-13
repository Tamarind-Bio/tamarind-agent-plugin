from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "tamarind"
SKILLS = PLUGIN / "skills"


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), path
    _, raw, _ = text.split("---", 2)
    return yaml.safe_load(raw)


def test_manifest_is_cli_first_and_valid_shape() -> None:
    manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
    claude_manifest = json.loads(
        (PLUGIN / ".claude-plugin" / "plugin.json").read_text()
    )
    claude_marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text()
    )
    assert manifest["name"] == "tamarind"
    assert manifest["version"] == "0.2.0"
    assert claude_manifest["version"] == manifest["version"]
    assert claude_marketplace["metadata"]["version"] == manifest["version"]
    assert manifest["skills"] == "./skills/"
    assert "mcpServers" not in manifest
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", manifest["interface"]["brandColor"])
    assert not (PLUGIN / ".mcp.json").exists()


def test_every_skill_has_minimal_frontmatter_and_ui_metadata() -> None:
    skill_dirs = sorted(
        path for path in SKILLS.iterdir() if (path / "SKILL.md").is_file()
    )
    assert len(skill_dirs) == 14
    for skill_dir in skill_dirs:
        skill_path = skill_dir / "SKILL.md"
        assert skill_path.is_file(), skill_dir
        meta = _frontmatter(skill_path)
        assert set(meta) == {"name", "description"}, skill_path
        assert meta["name"] == skill_dir.name
        assert meta["description"].strip()
        assert "<" not in meta["description"] and ">" not in meta["description"]

        ui_path = skill_dir / "agents" / "openai.yaml"
        ui = yaml.safe_load(ui_path.read_text())["interface"]
        short = ui["short_description"]
        assert 25 <= len(short) <= 64, (ui_path, len(short))
        assert f"${skill_dir.name}" in ui["default_prompt"]


def test_removed_transport_is_not_reintroduced() -> None:
    forbidden_names = {"tamarind_client.py", "tamarind_job.py", "requirements.txt"}
    assert not [path for path in SKILLS.rglob("*") if path.name in forbidden_names]

    markdown = "\n".join(path.read_text() for path in ROOT.rglob("*.md"))
    assert not re.search(r"pip(?:3|ython3 -m pip)? install[^\n]*--break-system-packages", markdown)
    assert "scripts/tamarind_job.py" not in markdown
    assert "from tamarind_client import" not in markdown


def test_reference_guidance_has_no_actionable_direct_transport_calls() -> None:
    """References may discuss architecture, but execution must go through the CLI."""
    reference_files = sorted(SKILLS.glob("*/references/*.md"))
    assert reference_files

    forbidden = {
        "MCP tool invocation": re.compile(
            r"\b(?:getAvailableTools|getJobSchema|validateJob|submitJob|submitBatch|"
            r"listJobFiles|uploadFile|getResult|getJobs|getJob|getJobLogs)\s*\("
        ),
        "Python HTTP call": re.compile(
            r"\brequests\s*\.\s*(?:get|post|put|patch|delete)\s*\("
        ),
        "raw Tamarind API URL": re.compile(
            r"https?://app\.tamarind\.bio/api(?:/|\b)", re.IGNORECASE
        ),
        "raw Tamarind auth header": re.compile(r"\bx-api-key\b", re.IGNORECASE),
        "raw REST route": re.compile(
            r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+/(?:api/)?"
            r"(?:tools|jobs|result|files)(?:\b|[/?])"
        ),
        "direct API curl/wget": re.compile(
            r"\b(?:curl|wget)\b[^\n]*(?:app\.tamarind\.bio/api|"
            r"mcp\.tamarind\.bio)",
            re.IGNORECASE,
        ),
    }

    offenders = []
    for path in reference_files:
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            for label, pattern in forbidden.items():
                if pattern.search(line):
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{line_no}: {label}"
                    )

    assert not offenders, offenders


def test_helper_invocations_are_not_cwd_relative() -> None:
    offenders = []
    for path in ROOT.rglob("*.md"):
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"(?:python3\s+|[` ])scripts/[A-Za-z0-9_-]+\.py", line):
                offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
    assert not offenders, offenders


def test_global_cli_flags_precede_subcommands() -> None:
    bad = re.compile(r"\btamarind\s+(?!--)(?:auth|files|tools|modalities|functions|schema|"
                     r"validate|submit|batch|jobs|status|wait|results|logs)\b[^\n`]*\s--json\b")
    offenders = []
    for path in ROOT.rglob("*.md"):
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            if bad.search(line) and "not " not in line:
                offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
    assert not offenders, offenders


def test_cli_014_batch_guidance_does_not_use_single_job_waiter() -> None:
    all_docs = "\n".join(path.read_text() for path in ROOT.rglob("*.md"))
    batch_docs = "\n".join(path.read_text() for path in (SKILLS / "tamarind-batch").rglob("*.md"))
    assert not re.search(
        r"\btamarind\s+--json\s+wait\s+(?:[^\s]*batch[^\s]*|[A-Z_]*BATCH[A-Z_]*)",
        all_docs,
        re.IGNORECASE,
    )
    assert "batchStatus" in batch_docs
    recovery = (SKILLS / "tamarind-results-analysis" / "SKILL.md").read_text()
    assert "do not call the single-job waiter" in recovery
    assert recovery.index("batchStatus") < recovery.index("tamarind --json wait JOB_NAME")


def test_cli_014_status_guidance_uses_safe_helper_before_wait() -> None:
    markdown = "\n".join(path.read_text() for path in ROOT.rglob("*.md"))
    assert "tamarind --json status" not in markdown
    assert markdown.count('python3 "$SKILL_DIR/scripts/safe_status.py"') >= 10

    lifecycle = (SKILLS / "tamarind-submit-and-poll" / "SKILL.md").read_text()
    assert lifecycle.index("safe_status.py") < lifecycle.index(
        "tamarind --json wait JOB_NAME"
    )
    assert "preserving native nonzero exit codes and stderr" in lifecycle
    assert "batchStatus" in lifecycle


def test_batch_examples_document_bare_subjob_suffixes() -> None:
    examples = (SKILLS / "tamarind-batch" / "references" / "examples.md").read_text()
    assert "bare, unique suffixes" in examples
    assert "- fold-screen-a" not in examples


def test_cli_014_budget_403_is_not_treated_as_bad_credentials() -> None:
    setup = (SKILLS / "tamarind-api-setup" / "SKILL.md").read_text()
    contract = (
        SKILLS
        / "tamarind-submit-and-poll"
        / "references"
        / "api_reference.md"
    ).read_text()
    for text in (setup, contract):
        assert "CLI 0.1.4" in text
        assert "HTTP 403" in text
        assert "budget" in text.lower()
        assert "re-auth" in text.lower() or "credentials" in text.lower()
        assert "resubmit" in text.lower()
