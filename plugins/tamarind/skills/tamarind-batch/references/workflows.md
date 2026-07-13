# Batch workflow recipes

CLI 0.1 accepts a list of settings or an object containing `settings`. It does not prevalidate the batch.

## Validate representative rows

Write each distinct conditional settings shape to its own file and run:

```bash
tamarind --json validate TOOL --input probe.yaml --name BATCH-probe
```

For a small batch, validate every row. For a large homogeneous batch, validate all conditionally distinct shapes and audit the generated document for missing/duplicate values.

## Submit and monitor

```bash
tamarind --json batch TOOL --input batch.yaml --name BATCH_NAME
SKILL_DIR="/absolute/path/to/the/tamarind-batch-skill"
python3 "$SKILL_DIR/scripts/safe_status.py" BATCH_NAME
tamarind --json jobs --batch BATCH_NAME --include-subjobs --all
```

For CLI 0.1.4 compatibility, monitor the parent with bounded, one-shot `status` calls scheduled by the agent host; do not call `wait` on a batch parent and do not write a shell polling loop. Inspect `batchStatus`, stop on `Complete`, `AggregationFailed`, or `Stopped`, and report the parent as still active when the chosen elapsed-time deadline expires. A parent can aggregate while some subjobs have stopped; report both the parent and per-subjob outcomes.

## Download and rank

```bash
tamarind --no-json results BATCH_NAME --download /absolute/path/to/results
SKILL_DIR="/absolute/path/to/the/tamarind-batch-skill"
python3 "$SKILL_DIR/scripts/rank_batch.py" /absolute/path/to/subjobs.json --metric iptm --json
```

Pass `--ascending` for lower-better metrics. Only completed subjobs with the selected numeric metric are ranked.

## Recover after interruption

Do not resubmit. Query the durable batch name and resume bounded one-shot `status` checks. If the parent failed, inspect stopped subjobs and logs before proposing a replacement batch.
