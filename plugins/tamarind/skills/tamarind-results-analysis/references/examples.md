# Results and recovery examples

## Recover one single job

```bash
tamarind --json status my-job
tamarind --json wait my-job --timeout 1800 --poll-interval 15
```

Inspect `JobStatus` even when the command exits 0. If it is stopped or failed:

```bash
tamarind --json logs my-job --max-lines 200
```

If the initial `status` response carries `batchStatus` instead, it is a batch parent. CLI 0.2 waits on either a single job or a batch parent and returns the final typed row; keep the deadline bounded.

## Download a successful result

```bash
tamarind --json results my-job --download /absolute/path/to/results
```

Extract the downloaded archive before using directory-based analysis scripts.

## Rank structure models

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-results-analysis-skill"
python3 "$SKILL_DIR/scripts/parse_boltz_confidence.py" /absolute/path/to/extracted-run --json
```

The script accepts a directory or scores CSV, not a zip archive.

## Extract docking poses

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-results-analysis-skill"
python3 "$SKILL_DIR/scripts/extract_docking_poses.py" /absolute/path/to/extracted-run --top 5 --json
```

Check whether the detected metric is affinity (lower is better) or confidence (higher is better).

## Summarize binder designs

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-results-analysis-skill"
python3 "$SKILL_DIR/scripts/summarize_binder_metrics.py" /absolute/path/to/extracted-run --json
```

## Rank batch subjobs

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-results-analysis-skill"
python3 "$SKILL_DIR/scripts/rank_batch.py" /absolute/path/to/subjobs.json --metric iptm --json
```

Only completed rows with the selected metric are ranked.
