# Results and recovery examples

## Recover one single job

```bash
tamarind --json status my-job | python3 -c 'import json,sys; blocked={"resulturl","downloadurl","presignedurl","uploadurl","headurl"}; scrub=lambda v: [scrub(x) for x in v] if isinstance(v,list) else {k:scrub(x) for k,x in v.items() if k.lower() not in blocked} if isinstance(v,dict) else v; print(json.dumps(scrub(json.load(sys.stdin))))'
tamarind --json wait my-job --timeout 1800 --poll-interval 15
```

Inspect `JobStatus` even when the command exits 0. If it is stopped or failed:

```bash
tamarind --json logs my-job --max-lines 200
```

If the initial `status` response carries `batchStatus` instead, it is a batch parent. On CLI 0.1.4, use bounded one-shot `status` checks scheduled by the agent host and do not call `wait` for that parent.

## Download a successful result

```bash
tamarind --no-json results my-job --download /absolute/path/to/results
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
