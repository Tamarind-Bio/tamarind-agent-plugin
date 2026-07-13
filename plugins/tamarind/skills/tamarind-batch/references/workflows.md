# Batch workflow recipes

CLI 0.2 accepts a list of settings or an object containing `settings`. Its `--prevalidate` checks every final row and aborts before submission when any row is invalid.

## Validate representative rows

Write each distinct conditional settings shape to its own file and run:

```bash
tamarind --json validate TOOL --input probe.yaml --name BATCH-probe
```

For a small batch, validate every row. For a large homogeneous batch, validate all conditionally distinct shapes and audit the generated document for missing/duplicate values.

## Submit and monitor

```bash
tamarind --json batch TOOL --input batch.yaml --name BATCH_NAME --prevalidate
tamarind --json status BATCH_NAME
tamarind --json jobs --batch BATCH_NAME --include-subjobs --all
```

Monitor the parent with `tamarind --json wait BATCH_NAME --timeout SECONDS`, not a shell polling loop. Inspect `batchStatus`, stop on `Complete`, `AggregationFailed`, or `Stopped`, and report the parent as still active on exit 7. A parent can aggregate while some subjobs have stopped; report both parent and per-subjob outcomes.

## Download and rank

```bash
tamarind --json results BATCH_NAME --download /absolute/path/to/results
SKILL_DIR="/absolute/path/to/the/tamarind-batch-skill"
python3 "$SKILL_DIR/scripts/rank_batch.py" /absolute/path/to/subjobs.json --metric iptm --json
```

Known lower-better metric names are inferred. Pass `--ascending` or `--descending` to override. Only completed subjobs with the selected numeric metric are ranked.

## Recover after interruption

Do not resubmit. Query the durable batch name and resume bounded one-shot `status` checks. If the parent failed, inspect stopped subjobs and logs before proposing a replacement batch.
