---
name: tamarind-results-analysis
description: "Recover and analyze an existing Tamarind Bio job by name: check or wait for status, inspect logs and metrics, download results, rank scientific outputs, and prepare a downstream input. Use after submission, across sessions, or when a previous command was interrupted. Not for starting a new job or choosing a tool."
---

# Recover and analyze Tamarind results

Treat the durable job name as the recovery key. Never start a replacement job merely because the local process ended.

## Recover remote state

```bash
tamarind --json status JOB_NAME
tamarind --json jobs --status Running --limit 50
tamarind --json jobs --batch BATCH_NAME --include-subjobs --all
```

Branch on the first status document. If it carries an active `JobStatus` or `batchStatus`, use a bounded wait:

```bash
tamarind --json wait JOB_NAME --timeout 1800 --poll-interval 15
```

Exit 7 is a local timeout, not a remote failure. Exit 9 means an unsuccessful terminal job or batch and leaves final status on stdout. For a stopped or failed job or batch:

```bash
tamarind --json logs JOB_NAME --max-lines 200
```

Report the failure and propose a corrected payload; do not resubmit without authorization.

## Cancel or delete a job

Both actions are consequential and target a durable job name. Confirm the exact name against `tamarind --json jobs` (or `--batch NAME --include-subjobs`) before acting; never act on a name the user only described.

Cancel a running or queued job so it stops consuming compute:

```bash
tamarind --json cancel JOB_NAME
tamarind --json cancel --batch BATCH_NAME
```

Cancel is scope-sensitive: a batch or pipeline is cancelled with `--batch`, a single job by positional name. If the named job is not found, do not cancel a similarly named one; surface the mismatch and ask.

Delete permanently removes a job and, for a batch, its subjobs. It is irreversible with no restore:

```bash
tamarind --json delete JOB_NAME
```

`delete` prompts for confirmation unless `-y` is passed. For a bulk cleanup there is no wildcard: list, filter to the exact names, show that list to the user for approval, then loop `delete -y` only over the approved set. Exclude any job not in a terminal state unless the user explicitly includes it.

## Read metrics

The `status` response contains tool-specific metadata and may carry `Score` as a JSON-encoded string. Parse it defensively and report only fields present. Common families include pLDDT, pTM, ipTM, ipSAE, pDockQ, affinity/energy, design filters, and `WeightedHours`.

Do not compare unrelated metrics on one scale. Explain whether higher or lower is better and distinguish model confidence from experimental validation.

## Download safely

Only download a successful terminal job:

```bash
tamarind --json results JOB_NAME --download /absolute/path/to/results
```

CLI 0.2 suppresses presigned URLs from normal download output and sanitizes transfer failures. Verify the bundle exists; extract it before running directory-based helpers. Never use `--show-url` in agent logs.

## Run local scientific analysis

Use the helper local to this skill on an extracted result directory:

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-results-analysis-skill"
python3 "$SKILL_DIR/scripts/parse_boltz_confidence.py" /absolute/path/to/run --json
python3 "$SKILL_DIR/scripts/extract_docking_poses.py" /absolute/path/to/run --top 5 --json
python3 "$SKILL_DIR/scripts/summarize_binder_metrics.py" /absolute/path/to/run --json
python3 "$SKILL_DIR/scripts/rank_batch.py" /absolute/path/to/subjobs.json --metric iptm --json
```

Resolve `SKILL_DIR` to the directory containing this `SKILL.md`; do not assume the shell is running from the skill directory. Choose only the helper matching the tool family. These scripts process local artifacts and make no network calls. For structure outputs, reject or manually inspect every `geometry_failures` entry and independently validate every `geometry_unchecked` entry before recommending a candidate; the adjacent-C-alpha PDB check is a gross continuity screen, not full structural validation. For batch ranking, prefer saved JSON from `tamarind --json jobs --batch BATCH_NAME --include-subjobs --all` so every ranked row has an authoritative terminal status.

## Prepare a downstream stage

CLI 0.2 does not expose a general result-file listing command. Prefer this explicit path:

1. Download and extract the successful result.
2. Select the exact artifact by inspecting the bundle, not by assuming a filename.
3. Upload it with `tamarind --json files upload /absolute/path/artifact`.
4. Use the returned bare `filename` in the downstream tool's validated settings.

If a live schema explicitly accepts a prior-job path and the exact path is known, it may be used; otherwise download and re-upload rather than guessing.

Read [references/results.md](references/results.md) for metric interpretation and [references/examples.md](references/examples.md) for result-family examples.
