# Tamarind Bio agent plugin

Run [Tamarind Bio](https://www.tamarind.bio) from Codex or Claude Code. This repository provides two separate transport-specific plugins with parallel scientific workflows:

- `tamarind`: use the independently installed Tamarind CLI.
- `tamarind-mcp`: use the authenticated remote Tamarind MCP server with no CLI installation.

Install one or both. Their skill names are distinct, and neither plugin modifies or wraps the other.

## Architecture

The repository keeps the transports isolated:

- In `plugins/tamarind`, the independently versioned [`tamarind-cli`](https://github.com/Tamarind-Bio/tamarind-cli) owns authentication, catalog/schema lookup, validation, API calls, polling, files, and downloads.
- In `plugins/tamarind-mcp`, the remote MCP server owns OAuth, discovery, validation, estimates, submissions, job state, files, and results.
- Both plugins own intent routing, scientific workflow guidance, spend confirmation, recovery rules, and result interpretation.
- The CLI plugin contains no MCP configuration. The MCP plugin contains no CLI commands or installation guidance.

Keeping the transports in different plugin folders prevents one surface from silently falling back to the other and lets each contract be tested independently.

## Install

### CLI plugin

Install the latest published CLI. The `tamarind` plugin requires version 0.2.0 or newer:

```bash
uv tool install tamarind-cli
# or
pipx install tamarind-cli
```

For an existing tool installation:

```bash
uv tool upgrade tamarind-cli
# or
pipx upgrade tamarind-cli
tamarind --version
```

Verify that the reported version is 0.2.0 or newer. Plugin CI tests every change against the latest published CLI.

Then install the CLI plugin.

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

### MCP plugin

The `tamarind-mcp` plugin needs no CLI or API key. It configures `https://mcp.tamarind.bio/mcp`; the client prompts for OAuth on first connection.

Codex:

```bash
codex plugin marketplace add Tamarind-Bio/tamarind-agent-plugin
codex plugin add tamarind-mcp@tamarind-agent-plugin
```

Claude Code:

```bash
claude plugin marketplace add Tamarind-Bio/tamarind-agent-plugin
claude plugin install tamarind-mcp@tamarind-agent-plugin
```

Start a new task after installation so the client discovers the MCP server and the new skills. Complete OAuth in the browser when prompted. Never paste OAuth tokens or client secrets into chat.

### Skills-only install

```bash
npx skills add Tamarind-Bio/tamarind-agent-plugin -a codex -a claude-code
```

## Authenticate

### CLI authentication

For CLI agents and CI, prefer the environment variable:

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

### MCP authentication

Install or enable `tamarind-mcp`, then complete the MCP client's OAuth flow. The MCP plugin does not use `TAMARIND_API_KEY` and has no separate auth-status command. A successful account-scoped `listModalities`, `listTags`, or filtered `getAvailableTools` call verifies the connection without spending compute.

Global CLI flags must precede the subcommand. For example, use `tamarind --json schema TOOL`, not `tamarind schema TOOL --json`.

## Safe no-spend smoke test

For the CLI plugin, these commands exercise authentication, the live catalog, the live schema, and server-side validation without submitting a compute job:

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

For the MCP plugin, call `listModalities`, `listTags`, a filtered `getAvailableTools`, and `getJobSchema`. Do not call `submitJob` or `submitBatch` as a smoke test.

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

The MCP plugin provides the parallel `tamarind-mcp-*` set:

- Core: `tamarind-mcp-setup`, `tamarind-mcp-tool-discovery`, `tamarind-mcp-submit-and-poll`, and `tamarind-mcp-results-analysis`.
- Domains: `tamarind-mcp-structure-prediction`, `tamarind-mcp-antibody`, `tamarind-mcp-binder-design`, `tamarind-mcp-inverse-folding`, `tamarind-mcp-docking`, `tamarind-mcp-developability`, `tamarind-mcp-finetune`, and `tamarind-mcp-more-tools`.
- Scale: `tamarind-mcp-batch` and `tamarind-mcp-pipeline`.

## Agent contract

The CLI skills require the machine-readable agent contract introduced in CLI 0.2.0:

- Put global flags before the command: `tamarind --json tools`, not `tamarind tools --json`.
- Parse result JSON from stdout and structured error JSON from stderr after checking the exit code.
- Inspect `JobStatus` or `batchStatus`; unsuccessful terminal jobs return dedicated exit 9 with the final status on stdout.
- Put a deadline on `wait`, including batch parents; exit 7 means the remote job may still be running.
- Download with `tamarind --json results JOB_NAME --download DIR`; CLI 0.2 does not print a presigned URL unless `--show-url` is explicitly requested.
- Never retry an ambiguous submit. Query the durable job name first.
- Confirm material scope/cost before `submit` or `batch`; `validate` is free and does not authorize spending.
- Once the validated scope is authorized, missing idempotency support or a missing pre-submission cost estimate does not block the first submit attempt. It only constrains retries or cost-capped requests.

The MCP skills require the live remote contract declared in `plugins/tamarind-mcp/.mcp.json`:

- Discover with `listModalities`, `listTags`, filtered `getAvailableTools`, and `getJobSchema`; do not hardcode the catalog.
- Require `validateJob` to return `valid: true` without `mutatedFields`, then call `estimateTime` before paid work.
- Confirm material scope and spend before `submitJob` or `submitBatch`.
- Submit once. If the result is ambiguous, recover by durable job or batch name with `getJobs`; never retry blindly.
- Poll `getJobs` with a finite deadline. A local deadline does not imply remote failure and never authorizes resubmission.
- Use one `submitBatch` for repeated inputs rather than looping over `submitJob`.
- Chain successful stages with exact `s3Path` values from `listJobFiles`; never invent result paths.
- Prefer targeted `getJobFile` calls. Treat any presigned URL returned by `getResult` as sensitive and do not repeat it in the final response.

## Development

Run the repository contract tests and the official validators:

```bash
python -m pytest -q
python /path/to/plugin-creator/scripts/validate_plugin.py plugins/tamarind
python /path/to/plugin-creator/scripts/validate_plugin.py plugins/tamarind-mcp
for plugin in plugins/tamarind plugins/tamarind-mcp; do
  for skill in "$plugin"/skills/*; do
    test -f "$skill/SKILL.md" || continue
    python /path/to/skill-creator/scripts/quick_validate.py "$skill"
  done
done
```

The authenticated smoke test is opt-in and must stop after `validate`.

## Responsible use

These skills submit prediction, design, and characterization jobs for legitimate research. Review inputs, scope, cost, and outputs before acting on generated scientific results.

## License

MIT. See [LICENSE](LICENSE).
