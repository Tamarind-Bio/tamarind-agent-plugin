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
    forbidden_names = {
        "tamarind_client.py",
        "tamarind_job.py",
        "safe_auth.py",
        "safe_status.py",
        "safe_transfer.py",
        "requirements.txt",
    }
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


def test_cli_02_batch_guidance_uses_bounded_parent_wait() -> None:
    batch_docs = "\n".join(path.read_text() for path in (SKILLS / "tamarind-batch").rglob("*.md"))
    assert "tamarind --json wait BATCH_NAME --timeout" in batch_docs
    assert "batchStatus" in batch_docs
    recovery = (SKILLS / "tamarind-results-analysis" / "SKILL.md").read_text()
    assert "tamarind --json wait JOB_NAME --timeout" in recovery
    assert "batchStatus" in recovery
    workflow = (
        SKILLS / "tamarind-submit-and-poll/references/workflows.md"
    ).read_text()
    assert "active JobStatus or batchStatus" in workflow
    assert "not batchStatus" not in workflow
    all_skill_docs = "\n".join(path.read_text() for path in SKILLS.rglob("*.md"))
    for stale_phrase in (
        "use wait only for JobStatus",
        "filtered status probe",
        "filtered bounded wait",
        "filtered download helper",
    ):
        assert stale_phrase not in all_skill_docs


def test_cli_02_job_output_guidance_uses_cli_contract_directly() -> None:
    public_docs = [ROOT / "README.md", *SKILLS.rglob("*.md")]
    markdown = "\n".join(path.read_text() for path in public_docs)
    assert "tamarind --json status" in markdown
    assert "tamarind --json wait" in markdown
    assert "tamarind --json jobs" in markdown
    assert "tamarind --json files upload" in markdown
    assert "tamarind --no-json results" not in markdown
    assert "scripts/safe_" not in markdown
    assert "--show-url" in markdown
    assert "Never use `--show-url` in agent logs" in markdown


def test_cli_02_auth_guidance_uses_redacted_cli_contract() -> None:
    markdown = "\n".join(path.read_text() for path in ROOT.rglob("*.md"))
    assert "tamarind --json auth status" in markdown
    assert "safe_auth.py" not in markdown
    assert "omits credential fragments" in markdown


def test_batch_examples_document_bare_subjob_suffixes() -> None:
    examples = (SKILLS / "tamarind-batch" / "references" / "examples.md").read_text()
    assert "bare, unique suffixes" in examples
    assert "- fold-screen-a" not in examples


def test_batch_submission_examples_require_final_row_prevalidation() -> None:
    markdown = "\n".join(path.read_text() for path in SKILLS.rglob("*.md"))
    commands = [
        line for line in markdown.splitlines()
        if line.startswith("tamarind --json batch ")
    ]
    assert commands
    assert all("--prevalidate" in command for command in commands)
    assert "CLI 0.2" in markdown
    assert "every final row" in markdown


def test_authorized_initial_submit_does_not_require_idempotency_or_estimate() -> None:
    skill = (SKILLS / "tamarind-submit-and-poll" / "SKILL.md").read_text()
    workflow = (
        SKILLS / "tamarind-submit-and-poll/references/workflows.md"
    ).read_text()
    contract = (
        SKILLS / "tamarind-submit-and-poll/references/api_reference.md"
    ).read_text()
    combined = "\n".join((skill, workflow, contract))

    for phrase in (
        "one initial client-side submission attempt",
        "does not block that first attempt",
        "missing pre-submission cost estimate",
        "server-side exactly-once guarantee",
        "job names are not documented as idempotency keys",
    ):
        assert phrase in combined

    assert "“run one small paid job” is sufficient" in skill
    assert "report actual `WeightedHours` afterward" in skill


def test_submit_authorization_edge_cases_keep_stop_boundaries() -> None:
    skill = (SKILLS / "tamarind-submit-and-poll" / "SKILL.md").read_text()
    workflow = (
        SKILLS / "tamarind-submit-and-poll/references/workflows.md"
    ).read_text()

    assert "quote or numeric cost cap" in skill
    assert "Dry run, validation-only request, or setup smoke check" in workflow
    assert "Authorized settings materially change after validation" in workflow
    assert "do not retry the submit command" in workflow
    assert "An explicitly authorized production canary is a real paid run" in skill


def test_ambiguous_submit_never_permits_pipeline_retry() -> None:
    contract = (
        SKILLS / "tamarind-submit-and-poll/references/api_reference.md"
    ).read_text()
    pipeline = (SKILLS / "tamarind-pipeline/SKILL.md").read_text()
    workflow = (
        SKILLS / "tamarind-pipeline/references/workflows.md"
    ).read_text()
    combined = "\n".join((contract, pipeline, workflow))

    assert "do not invoke `submit` or `batch` again" in contract
    assert "do not invoke `submit` again" in pipeline
    assert "recover only from authoritative remote state" in workflow
    assert "before any retry" not in combined
    assert "retry an ambiguous submission" not in combined


def test_batch_initial_attempt_uses_same_authorization_boundary() -> None:
    skill = (SKILLS / "tamarind-batch" / "SKILL.md").read_text()
    examples = (
        SKILLS / "tamarind-batch/references/examples.md"
    ).read_text()
    assert "missing idempotency support" in skill
    assert "missing pre-submission cost estimate" in skill
    assert "authorized initial batch command once" in skill
    assert "numeric cost ceiling" in examples


def test_release_docs_install_latest_cli_and_enforce_minimum_contract() -> None:
    readme = (ROOT / "README.md").read_text()
    workflow = (ROOT / ".github/workflows/validate.yml").read_text()
    setup = (SKILLS / "tamarind-api-setup/SKILL.md").read_text()
    submit = (SKILLS / "tamarind-submit-and-poll/SKILL.md").read_text()
    contract = (
        SKILLS / "tamarind-submit-and-poll/references/api_reference.md"
    ).read_text()
    agents = (ROOT / "AGENTS.md").read_text()
    policy_docs = "\n".join((readme, workflow, setup, submit, contract, agents))

    assert "Upgrading from 0.1" not in readme
    assert "uv tool install tamarind-cli" in readme
    assert "pipx install tamarind-cli" in readme
    assert "latest published CLI" in readme
    assert "latest published Tamarind CLI" in workflow
    assert "tamarind-cli>=0.2.0" in setup
    assert "CLI 0.2.0 or newer" in submit
    assert "tamarind-cli>=0.2.0" in contract
    assert "tamarind-cli>=0.2.0" in agents
    assert "tamarind-cli>=0.2,<0.3" not in policy_docs
    assert "git+https://github.com/Tamarind-Bio/tamarind-cli" not in readme
    assert "git+https://github.com/Tamarind-Bio/tamarind-cli" not in workflow
    assert "Release gate" not in readme
    assert "CLI 0.2.0 is not published yet" not in readme


def test_prodigy_reference_uses_prodigy_schema() -> None:
    tools = (SKILLS / "tamarind-docking/references/tools.md").read_text()
    prodigy = tools.split("## prodigy (PRODIGY)", 1)[1].split("\n---", 1)[0]
    assert "`tamarind --json schema prodigy`" in prodigy
    assert "schema binding-ddg" not in prodigy


def test_cli_02_terminal_failure_exit_is_documented() -> None:
    setup = (SKILLS / "tamarind-api-setup" / "SKILL.md").read_text()
    contract = (
        SKILLS / "tamarind-submit-and-poll" / "references/api_reference.md"
    ).read_text()
    for text in (setup, contract):
        assert "| 1 |" in text
        assert "| 9 |" in text
        assert "remote job" in text.lower()


def test_cli_02_budget_and_generic_403_are_not_treated_as_bad_credentials() -> None:
    setup = (SKILLS / "tamarind-api-setup" / "SKILL.md").read_text()
    contract = (
        SKILLS
        / "tamarind-submit-and-poll"
        / "references"
        / "api_reference.md"
    ).read_text()
    for text in (setup, contract):
        assert "CLI 0.2" in text
        assert "exit 1" in text
        assert "exit 8" in text
        assert "budget" in text.lower()
        assert "re-auth" in text.lower() or "credentials" in text.lower()
        assert "resubmit" in text.lower()


def test_structure_canaries_keep_quality_defaults_and_fast_example_is_fast() -> None:
    skill = (SKILLS / "tamarind-structure-prediction" / "SKILL.md").read_text()
    examples = (
        SKILLS / "tamarind-structure-prediction" / "references/examples.md"
    ).read_text()
    assert "keep the selected model's tuned recycling/diffusion defaults" in skill
    assert '"model": "esmfold2-fast"' in examples
