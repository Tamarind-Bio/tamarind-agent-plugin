# CLI workflow recipes

All recipes use an explicit settings file, a durable job name, a bounded wait, and status inspection.

## Sequence-only fold

`settings.yaml`:

```yaml
inputFormat: sequence
sequence: GYAGYAGYAGYAGYAGYAGYAGYA
numSamples: 1
```

No-spend validation:

```bash
tamarind --json schema boltz
tamarind --json validate boltz --input settings.yaml --name fold-example
```

Only after the exact run is authorized:

```bash
tamarind --json submit boltz --input settings.yaml --name fold-example
# Run the filtered status probe from the parent SKILL.md first; continue only for JobStatus.
tamarind --json wait fold-example --timeout 7200 --poll-interval 15
tamarind --json results fold-example --download /absolute/path/to/results
```

## Upload a structure, then run a structure-based tool

```bash
tamarind --json files upload /absolute/path/target.pdb
tamarind --json files list --search target.pdb
```

Put the returned `filename` in the tool's live-schema field, validate, then use the same submit/wait/download sequence.

## Submit now, recover later

```bash
tamarind --json submit TOOL --input settings.yaml --name durable-name
```

Persist `durable-name`. In another task or process:

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-submit-and-poll-skill"
tamarind --json status durable-name
# Use wait only if the filtered probe carries JobStatus, not batchStatus.
tamarind --json wait durable-name --timeout 1800 --poll-interval 15
```

Do not create a new job merely because the first local process ended.

## Diagnose a terminal failure

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-submit-and-poll-skill"
tamarind --json status durable-name
tamarind --json logs durable-name --max-lines 200
```

Fix the payload against the current schema and ask before submitting a replacement run.
