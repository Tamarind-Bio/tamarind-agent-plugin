# Tamarind Bio agent plugin

Run [Tamarind Bio](https://www.tamarind.bio) from Codex or Claude Code. The plugin adds workflow and scientific guidance for structure prediction, docking, binder and antibody design, developability, fine-tuning, batch jobs, and multi-stage campaigns.

## Architecture

Version 0.2 is CLI-first:

- The independently versioned [`tamarind-cli`](https://github.com/Tamarind-Bio/tamarind-cli) owns authentication, live catalog/schema lookup, validation, API calls, job state, polling, files, and downloads.
- The plugin owns intent routing, scientific workflow guidance, spend confirmation, recovery rules, and local result analysis.
- Local helper scripts only parse downloaded scientific results. The plugin no longer vendors a second HTTP client or MCP transport.

This mirrors the CLI-first separation in the [Boltz agent plugin](https://github.com/boltz-bio/boltz-api-skills): one tested machine interface underneath thin, intent-specific skills. It removes the plugin's duplicated transport implementation and makes cross-surface drift testable; it does not make compatibility testing unnecessary.

## Upgrading from 0.1

Version 0.2 changes the plugin's execution boundary. Version 0.1 bundled an MCP connection for discovery and validation and copied a small REST client into multiple skills for job execution. Version 0.2 removes both bundled transports and delegates the complete execution lifecycle to `tamarind-cli`.

Existing users should:

1. Install or upgrade to `tamarind-cli>=0.1.4,<0.2` using the commands below.
2. Authenticate with `TAMARIND_API_KEY` or `tamarind auth login`, then verify with `tamarind --json auth status`.
3. Update or reinstall the plugin and start a new agent task so the new skills are loaded.

The hosted Tamarind MCP service remains a separate integration, but it is no longer configured or required by this plugin. MCP-specific host configuration is not migrated into the CLI; an existing `TAMARIND_API_KEY` environment variable continues to work.

## Install

Install the CLI first. During the 0.1 series the plugin supports `tamarind-cli>=0.1.4,<0.2`:

```bash
uv tool install 'tamarind-cli>=0.1.4,<0.2'
# or
pipx install 'tamarind-cli>=0.1.4,<0.2'
```

For an existing tool installation:

```bash
uv tool upgrade tamarind-cli
# or
pipx upgrade tamarind-cli
tamarind --version
```

Re-check that the reported version remains in `>=0.1.4,<0.2`; if it does not, reinstall the supported range explicitly.

Then install the plugin.

### Codex

```bash
codex plugin marketplace add Tamarind-Bio/tamarind-agent-plugin
codex plugin add tamarind@tamarind-agent-plugin
```

For local development, point Codex at a checkout:

```bash
codex plugin marketplace add /absolute/path/to/tamarind-agent-plugin
codex plugin add tamarind@tamarind-agent-plugin
```

Start a new task after installation or update so Codex loads the new skills.

### Claude Code

```bash
claude plugin marketplace add Tamarind-Bio/tamarind-agent-plugin
claude plugin install tamarind@tamarind-agent-plugin
```

### Skills-only install

```bash
npx skills add Tamarind-Bio/tamarind-agent-plugin -a codex -a claude-code
```

## Authenticate

For agents and CI, prefer the environment variable:

```bash
export TAMARIND_API_KEY="your_api_key"
```

For an interactive local profile:

```bash
tamarind auth login
```

Verify the active profile without printing the secret:

```bash
tamarind --json auth status
```

Global CLI flags must precede the subcommand. Use `tamarind --json jobs`, not `tamarind jobs --json`.

## Safe no-spend smoke test

These commands exercise authentication, the live catalog, the live schema, and server-side validation without submitting a compute job:

```bash
tamarind --version
tamarind --json auth status
tamarind --json tools --search boltz
tamarind --json schema boltz
tamarind --json validate boltz \
  --name plugin-smoke \
  --set inputFormat=sequence \
  --set sequence=GYAGYAGYAGYAGYAGYAGYAGYA
```

Do not add `submit` to a smoke test. Tamarind jobs can consume weighted hours.

## Skills

Setup and core:

- `tamarind-api-setup`: install/version-check the CLI, authenticate, and run a no-spend self-check.
- `tamarind-tool-discovery`: select a tool from the live CLI catalog and confirm its schema.
- `tamarind-submit-and-poll`: validate, confirm consequential choices, submit one job, wait with a timeout, inspect terminal status, and download.
- `tamarind-results-analysis`: recover an existing job by name, inspect status/logs/metrics, download results, and run local analysis.

Domain workflows:

- `tamarind-structure-prediction`
- `tamarind-antibody`
- `tamarind-binder-design`
- `tamarind-inverse-folding`
- `tamarind-docking`
- `tamarind-developability`
- `tamarind-finetune`
- `tamarind-more-tools`

Scale and orchestration:

- `tamarind-batch`: one tool across many inputs.
- `tamarind-pipeline`: resumable, imperative multi-tool campaigns through CLI stages.

## Agent contract

The skills intentionally account for current CLI 0.1 behavior:

- Put global flags before the command: `tamarind --json tools`, not `tamarind tools --json`.
- Treat stdout as JSON only on success; parse nonzero-command stderr as text.
- Inspect `JobStatus` or `batchStatus`; a terminal failed/stopped job may still produce process exit 0.
- On CLI 0.1.4, monitor batch parents with bounded one-shot `status` checks because `wait` does not reliably follow `batchStatus`.
- Use standalone `wait --timeout`, not unbounded `submit --wait` or `results --wait`.
- Download with `--no-json` so presigned URLs are not echoed into agent logs.
- Never retry an ambiguous submit. Query the durable job name first.
- Confirm material scope/cost before `submit` or `batch`; `validate` is free and does not authorize spending.

## Development

Run the repository contract tests and the official validators:

```bash
python -m pytest -q
python /path/to/plugin-creator/scripts/validate_plugin.py plugins/tamarind
for skill in plugins/tamarind/skills/*; do
  test -f "$skill/SKILL.md" || continue
  python /path/to/skill-creator/scripts/quick_validate.py "$skill"
done
```

The authenticated smoke test is opt-in and must stop after `validate`.

## Responsible use

These skills submit prediction, design, and characterization jobs for legitimate research. Review inputs, scope, cost, and outputs before acting on generated scientific results.

## License

MIT. See [LICENSE](LICENSE).
