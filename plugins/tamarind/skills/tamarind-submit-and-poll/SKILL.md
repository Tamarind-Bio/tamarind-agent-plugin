---
name: tamarind-submit-and-poll
description: "Run one known Tamarind Bio tool end to end through the Tamarind CLI: validate settings, confirm consequential choices and spend, submit once, wait with a timeout, inspect terminal status, and download results. Also use to reattach to one already-submitted job. Not for tool selection, batch submission, or multi-tool orchestration."
---

# Run one Tamarind job

Use this lifecycle for every single-tool job. The domain skill chooses the science; this skill owns safe execution.

## 1. Verify the CLI and auth

```bash
tamarind --version
tamarind --json auth status
```

Require CLI `>=0.1.4,<0.2` and `verified: true`. Otherwise use `tamarind-api-setup`.

## 2. Confirm the live schema

```bash
tamarind --json schema TOOL
```

Build a small `settings.yaml` or `settings.json` containing only user inputs and intentional overrides. Prefer a file over a long shell command so nested values and quoting remain reviewable.

For local file inputs, upload first and use the returned `filename` exactly:

```bash
tamarind --json files upload /absolute/path/input.pdb
tamarind --json files list --search input.pdb
```

Do not use email-prefixed object keys, `s3://` URLs, or shell-expanded secrets.

## 3. Validate without spending

Choose a durable, unique job name and run:

```bash
tamarind --json validate TOOL --input settings.yaml --name JOB_NAME
```

Require `valid: true`. Submit the original settings file, not the validator's `normalized` echo, because normalized output may contain server-managed defaults.

## 4. Confirm consequential choices

Before a material run, surface the few choices that change scientific meaning, runtime, or weighted-hour cost: model/version, samples/designs, recycles, MSA, library size, batch count, GPU tier when exposed, and optional scoring stages.

If the user has not already authorized the exact scope, obtain confirmation before `submit`. Validation is free and is not spending authorization. Never perform a paid compute submission as a smoke test.

## 5. Submit once

```bash
tamarind --json submit TOOL --input settings.yaml --name JOB_NAME
```

Record `JOB_NAME` immediately. Do not use `--wait`; it is unbounded in CLI 0.1. If the command times out or the response is ambiguous, do not retry. First run the filtered status probe in step 6.

Job-name idempotency is not documented, so an automatic retry may create or collide with duplicate work.

## 6. Classify the returned row, then wait with a bound

Some nominally single-tool settings fan out into a batch parent. Probe the durable name once before choosing a waiter. CLI 0.1.4 can expose a completed parent's presigned `resultUrl` in raw status JSON, so use the local compatibility helper to remove credential-bearing URL fields before output returns to the agent:

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-submit-and-poll-skill"
python3 "$SKILL_DIR/scripts/safe_status.py" JOB_NAME
```

Resolve `SKILL_DIR` to the directory containing this `SKILL.md`. This helper still executes the official `tamarind` CLI; it is not an API client. It parses and redacts stdout only after exit 0, while preserving native nonzero exit codes and stderr.

If the filtered document carries `batchStatus`, do not call CLI 0.1.4's single-job waiter. Schedule the same bounded, safe one-shot status helper through the agent host and stop on batch `Complete`, `AggregationFailed`, or `Stopped`. If it carries active `JobStatus`, run the wait in the agent runtime's foreground/session mechanism, never shell `&` or `nohup`:

```bash
tamarind --json wait JOB_NAME --timeout 3600 --poll-interval 15
```

Exit 7 means the local deadline elapsed; the remote job may still be running. Reattach with the filtered status probe or another bounded single-job `wait`.

After exit 0, inspect `JobStatus`. CLI 0.1 can return process exit 0 for terminal `Stopped`, `Failed`, `Cancelled`, or `Error`; only the platform success status authorizes result download. For failures:

```bash
tamarind --json logs JOB_NAME --max-lines 200
```

Do not resubmit automatically.

## 7. Download without exposing the presigned URL

Use an absolute output directory and human output mode:

```bash
tamarind --no-json results JOB_NAME --download /absolute/path/to/results
```

CLI 0.1 includes the presigned URL in JSON download output, so `--no-json` is intentional. Treat transfer tracebacks as failures and verify the downloaded file exists before analysis.

## Output report

Return the tool, durable job name, validated settings path or concise settings summary, terminal status, weighted hours when present, result path, and the main metrics. State clearly when a job remains queued/running or when only validation was performed.

Read [references/workflows.md](references/workflows.md) for CLI recipes and [references/examples.md](references/examples.md) for input shapes. Treat the live schema as authoritative when examples drift.
