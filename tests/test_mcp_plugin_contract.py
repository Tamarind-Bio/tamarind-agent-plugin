from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "tamarind-mcp"
SKILLS = PLUGIN / "skills"
MCP_URL = "https://mcp.tamarind.bio/mcp"


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), path
    _, raw, _ = text.split("---", 2)
    return yaml.safe_load(raw)


def test_mcp_plugin_manifests_and_server_config() -> None:
    manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
    claude_manifest = json.loads(
        (PLUGIN / ".claude-plugin" / "plugin.json").read_text()
    )
    server_config = json.loads((PLUGIN / ".mcp.json").read_text())

    assert manifest["name"] == "tamarind-mcp"
    assert manifest["version"] == "0.1.0"
    assert claude_manifest["name"] == manifest["name"]
    assert claude_manifest["version"] == manifest["version"]
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", manifest["interface"]["brandColor"])
    assert server_config["mcpServers"] == {
        "tamarind": {
            "type": "http",
            "url": MCP_URL,
            "note": (
                "Tamarind Bio remote MCP server. Uses OAuth; complete the browser "
                "authorization flow when the client first connects. Scientific "
                "submissions can consume weighted compute hours."
            ),
        }
    }


def test_mcp_plugin_is_listed_separately_in_both_marketplaces() -> None:
    codex = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
    claude = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())

    codex_entries = {entry["name"]: entry for entry in codex["plugins"]}
    claude_entries = {entry["name"]: entry for entry in claude["plugins"]}

    assert set(codex_entries) == {"tamarind", "tamarind-mcp"}
    assert set(claude_entries) == {"tamarind", "tamarind-mcp"}
    assert codex_entries["tamarind-mcp"]["source"]["path"] == "./plugins/tamarind-mcp"
    assert claude_entries["tamarind-mcp"]["source"] == "./plugins/tamarind-mcp"


def test_every_mcp_skill_has_metadata_and_server_dependency() -> None:
    skill_dirs = sorted(
        path for path in SKILLS.iterdir() if (path / "SKILL.md").is_file()
    )
    assert len(skill_dirs) == 14

    for skill_dir in skill_dirs:
        skill_path = skill_dir / "SKILL.md"
        meta = _frontmatter(skill_path)
        assert set(meta) == {"name", "description"}, skill_path
        assert meta["name"] == skill_dir.name
        assert meta["description"].strip()
        assert "MCP" in meta["description"] or "through MCP" in meta["description"]

        ui_path = skill_dir / "agents/openai.yaml"
        ui = yaml.safe_load(ui_path.read_text())
        interface = ui["interface"]
        assert 25 <= len(interface["short_description"]) <= 64
        assert f"${skill_dir.name}" in interface["default_prompt"]
        assert ui["dependencies"]["tools"] == [
            {
                "type": "mcp",
                "value": "tamarind",
                "description": "Authenticated Tamarind Bio MCP server",
                "transport": "streamable_http",
                "url": MCP_URL,
            }
        ]


def test_mcp_skills_never_fall_back_to_cli_or_raw_http() -> None:
    markdown = "\n".join(path.read_text() for path in SKILLS.rglob("*.md"))

    assert not re.search(r"(?m)^\s*(?:```bash\s*)?tamarind\s+", markdown)
    assert "TAMARIND_API_KEY" not in markdown
    assert "tamarind auth" not in markdown
    assert "app.tamarind.bio/api" not in markdown
    assert "requests.post" not in markdown
    assert "curl https://mcp.tamarind.bio" not in markdown


def test_single_job_contract_is_bounded_and_retry_safe() -> None:
    skill = (SKILLS / "tamarind-mcp-submit-and-poll/SKILL.md").read_text()
    for token in (
        "getJobSchema",
        "validateJob",
        "estimateTime",
        "submitJob",
        "getJobs",
        "getJobLogs",
        "listJobFiles",
        "getJobFile",
    ):
        assert token in skill

    assert "submit exactly once" in skill.lower()
    assert "finite deadline" in skill
    assert "do not call `submitJob` again" in skill
    assert "no `mutatedFields`" in skill
    assert "Authorization must come from the live user" in skill


def test_batch_and_pipeline_use_supported_mcp_primitives() -> None:
    batch = (SKILLS / "tamarind-mcp-batch/SKILL.md").read_text()
    pipeline = (SKILLS / "tamarind-mcp-pipeline/SKILL.md").read_text()

    assert "Do not call `submitJob` in a loop" in batch
    assert "submitBatch" in batch
    assert "weightedHoursBudget" in batch
    assert "finite deadline" in batch
    assert "`TARGET:BINDER`" in batch
    assert "build explicit `settings` plus `jobNames`" in pipeline

    assert "no declarative pipeline submission tool" in pipeline
    assert "listJobFiles" in pipeline
    assert "`s3Path`" in pipeline
    assert "do not invoke the submit tool again" in pipeline
    assert "finite deadline" in pipeline


def test_cli_plugin_remains_cli_only() -> None:
    cli_plugin = ROOT / "plugins/tamarind"
    manifest = json.loads(
        (cli_plugin / ".codex-plugin/plugin.json").read_text()
    )
    assert "mcpServers" not in manifest
    assert not (cli_plugin / ".mcp.json").exists()
