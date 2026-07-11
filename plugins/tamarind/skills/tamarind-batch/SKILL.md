---
name: tamarind-batch
description: Run one Tamarind Bio tool across many independent inputs as a tracked batch, then monitor the parent, inspect subjobs, download aggregation, and rank completed results. Use for libraries and screens. Not for one input, multiple dependent tool stages, or an unbounded loop of individual submissions.
---

# Run one tool across many inputs

A batch multiplies both throughput and possible weighted-hour spend. Keep one tool and one scientific settings policy across the batch.

## Prepare the input document

`tamarind batch` accepts either a YAML/JSON list of per-job settings or an object with `batchName`, `type`, `settings`, and optional `jobNames`.

Confirm the live tool schema:

```bash
tamarind --json schema TOOL
```

CLI 0.1 does not prevalidate a batch. Validate every distinct conditional shape, and validate every row for small/medium batches:

```bash
tamarind --json validate TOOL --input one-settings.yaml --name BATCH-probe-001
```

Check duplicate job names, input count, file availability, per-input sampling, and total expected scope. Obtain explicit confirmation for the multiplied spend before submission.

## Submit and recover the parent

```bash
tamarind --json batch TOOL --input batch.yaml --name BATCH_NAME
tamarind --json status BATCH_NAME | python3 -c 'import json,sys; blocked={"resulturl","downloadurl","presignedurl","uploadurl","headurl"}; scrub=lambda v: [scrub(x) for x in v] if isinstance(v,list) else {k:scrub(x) for k,x in v.items() if k.lower() not in blocked} if isinstance(v,dict) else v; print(json.dumps(scrub(json.load(sys.stdin))))'
```

Do not retry an ambiguous batch submit. Query `BATCH_NAME` first. CLI 0.1.4's `wait` command reads single-job `JobStatus` and cannot reliably terminate on a batch parent's `batchStatus`, so do not use it for batch parents. Schedule bounded, one-shot `status` checks through the agent host at a sensible cadence (normally 20-60 seconds), with a clear elapsed-time deadline. Stop on batch `Complete`, `AggregationFailed`, or `Stopped`; never implement an unbounded shell loop. A deadline means "report still running and reattach later," not "resubmit."

Inspect authoritative subjob rows:

```bash
tamarind --json jobs --batch BATCH_NAME --include-subjobs --all > /absolute/path/to/subjobs.json
```

Read the saved JSON and report completed, running, queued, and stopped counts. A partially successful batch must not hide failed subjobs.

## Download and rank

For a successful aggregated parent:

```bash
tamarind --no-json results BATCH_NAME --download /absolute/path/to/results
SKILL_DIR="/absolute/path/to/the/tamarind-batch-skill"
python3 "$SKILL_DIR/scripts/rank_batch.py" /absolute/path/to/subjobs.json --metric METRIC --json
```

Resolve `SKILL_DIR` to the directory containing this `SKILL.md`; do not assume the shell is running from the skill directory. Pass either saved JSON emitted by `tamarind --json jobs --batch BATCH_NAME --include-subjobs --all`, a directory containing that output as `subjobs.json`, or a downloaded batch directory. A downloaded directory alone has no authoritative job statuses, so its rows remain explicitly unranked until status-bearing JSON is supplied.

Use `--ascending` for lower-better metrics such as energy or PAE. The helper ranks completed rows only; incomplete, unknown-status, or unscored rows are returned separately as `unranked`.

Read [references/workflows.md](references/workflows.md) and [references/examples.md](references/examples.md) for batch-document patterns. The CLI does not currently expose every server-side batch convenience; do not invent unsupported flags.
