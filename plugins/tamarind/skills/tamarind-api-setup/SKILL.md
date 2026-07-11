---
name: tamarind-api-setup
description: Install, upgrade, authenticate, or troubleshoot the Tamarind CLI before running Tamarind Bio jobs. Use when `tamarind` is missing or incompatible, authentication is absent or rejected, endpoints/profiles need configuration, or a safe no-spend connectivity check is needed. Not for submitting compute jobs or selecting a scientific tool.
---

# Set up the Tamarind CLI

Use the CLI as the only execution transport for this plugin. Do not recreate API calls with curl, Python, or a vendored client.

## 1. Check the executable and version

Run:

```bash
command -v tamarind
tamarind --version
```

This plugin supports `tamarind-cli>=0.1.4,<0.2`. If the command is missing, prefer an isolated tool install:

```bash
uv tool install 'tamarind-cli>=0.1.4,<0.2'
```

If `uv` is unavailable, use:

```bash
pipx install 'tamarind-cli>=0.1.4,<0.2'
```

Upgrade an existing isolated installation with `uv tool upgrade tamarind-cli` or `pipx upgrade tamarind-cli`, then run `tamarind --version` again and require `>=0.1.4,<0.2`. If an upgrade moves outside that supported range, reinstall the explicit range with the same tool. Do not run a remote `curl | sh` installer without the user's explicit approval. Do not mutate the system Python or use `--break-system-packages`.

In a sandboxed agent, even `uv tool list` or `uv tool upgrade` can create temporary files under uv's cache and `~/.local/share/uv/tools`. Request narrowly scoped write access to those directories, or give the exact command to the user instead of repeatedly retrying a denied install.

## 2. Authenticate without exposing the key

For agents and CI, prefer `TAMARIND_API_KEY`. For an interactive local profile, run:

```bash
tamarind auth login
```

Never put a key in chat, logs, source files, or a command-line `--api-key` argument. Verify the active credential:

```bash
tamarind --json auth status
```

Require both `hasKey: true` and `verified: true`. The command may exit 0 with `verified: false`, so inspect the JSON rather than trusting the process status.

Global flags must precede the subcommand. Use `tamarind --json auth status`, not `tamarind auth status --json`.

## 3. Run a no-spend smoke test

Use live discovery, schema lookup, and validation only:

```bash
tamarind --json tools --search boltz
tamarind --json schema boltz
tamarind --json validate boltz \
  --name plugin-smoke \
  --set inputFormat=sequence \
  --set sequence=GYAGYAGYAGYAGYAGYAGYAGYA
```

Success requires a tool result, a schema, and `valid: true`. Do not call `submit` as part of setup or smoke testing.

## 4. Handle errors by contract

CLI 0.1 emits JSON for successful commands, but errors and usage failures are plain text on stderr. Branch on the exit code and read stderr as text:

| Exit | Meaning | Action |
|---|---|---|
| 0 | Command completed | Inspect returned fields such as `verified` or job status |
| 2 | Usage or safety confirmation | Fix argument placement or provide an explicitly authorized `--yes` |
| 3 | Authentication, or any HTTP 403 on CLI 0.1.4 | Inspect stderr first. Re-authenticate only for credential failures; a message about budget, quota, credits, or weighted hours is a spend-limit failure and must not trigger re-authentication or resubmission |
| 4 | Not found | Re-check the tool, job, file, or profile name |
| 5 | Validation | Fix settings against the live schema |
| 6 | Rate limit | Back off; do not duplicate a submission |
| 7 | Wait timeout | Reattach with `status` or another bounded `wait` |
| 8 | Budget or quota (newer compatible CLI) | Stop and surface the limit; do not retry or resubmit |

CLI 0.1.4 maps every HTTP 403 to exit 3. Newer compatible CLI releases distinguish budget/quota failures as exit 8. Therefore branch on both the exit code and the error message; never assume that a 403 means the key is bad. Treat network/transfer tracebacks as failures even if they are not wrapped in structured JSON.

## Profiles and endpoints

Use `--profile` before the command or `TAMARIND_PROFILE` for a named profile. Use `TAMARIND_API_BASE` and `TAMARIND_CATALOG_BASE` only for an explicitly requested staging or custom environment. Do not silently redirect a production workflow.

After setup succeeds, use `tamarind-tool-discovery` to select a tool or `tamarind-submit-and-poll` to run a known tool.
