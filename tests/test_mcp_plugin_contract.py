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
    # Bump on every shipped change: hosts cache the plugin in a version-keyed
    # directory, so an unchanged version can serve a stale `.mcp.json`.
    assert manifest["version"] == "0.1.9"
    assert claude_manifest["name"] == manifest["name"]
    assert claude_manifest["version"] == manifest["version"]
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", manifest["interface"]["brandColor"])
    server = server_config["mcpServers"]["tamarind"]
    assert set(server_config["mcpServers"]) == {"tamarind"}
    assert server["type"] == "http"
    assert server["url"] == MCP_URL
    assert server["note"].strip()

    # Keep this entry to type/url/note ONLY. Both OAuth keys break authorization,
    # each in its own way, and each was shipped and reverted once already:
    #
    #   oauth.client_id  - Codex prefers a pinned id over obtaining its own,
    #                      disabling both DCR and CIMD. It then sends a loopback
    #                      redirect on an ephemeral port that cannot be
    #                      pre-registered against an exact-match allowlist.
    #   oauth_resource   - Codex already sends the RFC 8707 resource parameter
    #                      itself. Pinning it sends the parameter twice
    #                      (measured: 2 vs 1) and Clerk rejects duplicates with
    #                      invalid_request.
    assert set(server) == {"type", "url", "note"}, (
        "unexpected key in the tamarind server entry - oauth.client_id and "
        "oauth_resource both break authorization; see the note in .mcp.json"
    )
    # A public repo must never carry a client secret under any key.
    assert "client_secret" not in json.dumps(server_config)


def test_mcp_plugin_is_listed_separately_in_both_marketplaces() -> None:
    codex = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
    claude = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())

    codex_entries = {entry["name"]: entry for entry in codex["plugins"]}
    claude_entries = {entry["name"]: entry for entry in claude["plugins"]}

    assert set(codex_entries) == {"tamarind-cli", "tamarind-mcp"}
    assert set(claude_entries) == {"tamarind-cli", "tamarind-mcp"}
    assert codex_entries["tamarind-mcp"]["source"]["path"] == "./plugins/tamarind-mcp"
    assert claude_entries["tamarind-mcp"]["source"] == "./plugins/tamarind-mcp"


def test_every_mcp_skill_has_metadata_and_server_dependency() -> None:
    skill_dirs = sorted(
        path for path in SKILLS.iterdir() if (path / "SKILL.md").is_file()
    )
    assert len(skill_dirs) == 16

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
    paths = sorted(SKILLS.rglob("*.md"))
    markdown = "\n".join(path.read_text() for path in paths)

    assert not re.search(r"(?m)^\s*(?:```bash\s*)?tamarind\s+", markdown)
    assert "TAMARIND_API_KEY" not in markdown
    assert "tamarind auth" not in markdown
    assert "requests.post" not in markdown
    assert "curl https://mcp.tamarind.bio" not in markdown

    # The setup skill is the one place that may send the user to the website:
    # connecting the server needs an API key, and the key and the client-by-client
    # instructions both live under /api-docs. Every other skill must stay inside
    # the MCP surface rather than routing work back through the web app.
    workflow_markdown = "\n".join(
        path.read_text()
        for path in paths
        if path.parent.name != "tamarind-mcp-setup"
    )
    assert "app.tamarind.bio/api" not in workflow_markdown


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
    # The pipeline skill used to teach hand-rolled chaining because the MCP surface had no
    # declarative pipeline tool. It now has nine, so these pin the DECLARATIVE contract — and
    # the old assertion (`"no declarative pipeline submission tool" in pipeline`) was removed
    # rather than updated, because it pinned a claim that had become false.
    for tool in (
        "getPipelineSchema",
        "listPipelineTemplates",
        "getPipelineTemplate",
        "validatePipeline",
        "submitPipeline",
        "getPipelineRun",
        "getPipelineRunResults",
        "listPipelineRuns",
        "stopPipelineRun",
    ):
        assert tool in pipeline, tool

    # Validation is the gate in front of spend, and its two measured failure modes.
    assert "only submit on `valid: true`" in pipeline
    assert "`validationUnavailable`" in pipeline
    assert "not a guarantee" in pipeline

    # The residue trap: a non-empty `residueFields` does NOT mean a selection is required, and
    # inventing one silently produces scientifically wrong output.
    assert "residuesByChain" in pipeline
    assert "do not guess" in pipeline

    # Pipeline runs are their own resource — the job-shaped tools do not see or stop them.
    assert "do not appear in `getJobs()`" in pipeline
    assert "Do not use `cancelBatch`" in pipeline

    # Measured against the live MCP surface: `validationUnavailable` is ALSO set on a permanent
    # 403, whose own hint says to retry. Retrying it is wasted — the response is byte-identical.
    # And the org listing (which this skill tells agents to prefer) includes templates that then
    # fail validation with exactly that 403, so the two facts have to be taught together.
    assert "pipeline_permission_denied" in pipeline
    assert "Listed does not mean runnable" in pipeline

    assert "finite deadline" in pipeline

    # Found by running the skill end-to-end against production. Each of these is a shape an
    # agent gets wrong by reasonable inference, and each was measured on a real run.
    #   - the reference group is a SAVE-time rule; stating it flatly sends an inline author
    #     hunting for a group id, which corrupts the saved template (submit never REPLACES a
    #     defaultGroup that is already there).
    #   - residuesByChain has two shapes and ADVANCED is the default for new templates; the
    #     wrong shape against a templateId is a hard 422.
    #   - getPipelineRun says nodeRuns/nodeId, getPipelineRunResults says steps/node, for the
    #     same concept in the same run.
    #   - nodeRuns order is unstable: two consecutive polls returned it in different orders,
    #     with a dependent step ahead of its dependency.
    # Assert against whitespace-normalized prose: these phrases wrap across lines, and a test
    # that fails when a paragraph is re-wrapped pins the formatting rather than the claim.
    flat = " ".join(pipeline.split())
    assert "required only when SAVING a template" in flat
    assert "never replaces one you left in" in flat
    assert "in one of **two shapes**" in flat
    assert "Steps are under **`nodeRuns`**" in flat
    assert "`nodeId` is what `getPipelineRunResults(node=...)` wants" in flat
    assert "The order is not stable and is not topological" in flat

    # The two ways to silently get WRONG SCIENCE out of a successful run, both measured:
    # metadata[tool] is a history list (reading [0] returns another run's numbers), and
    # results do not come back in binding order (zipping positionally mislabels every row).
    assert "scores are keyed by tool name" in flat
    assert "list of every run that ever scored that molecule" in flat
    assert "Results do not come back in binding order" in flat

    # The gap that actually costs GPU money: validation does NOT enforce requiresStructure,
    # so a structure-less binding returns valid:true on a template whose first tool needs a PDB.
    assert "does **not** enforce `requiresStructure`" in flat


def test_cli_plugin_remains_cli_only() -> None:
    cli_plugin = ROOT / "plugins/tamarind-cli"
    manifest = json.loads(
        (cli_plugin / ".codex-plugin/plugin.json").read_text()
    )
    assert "mcpServers" not in manifest
    assert not (cli_plugin / ".mcp.json").exists()
