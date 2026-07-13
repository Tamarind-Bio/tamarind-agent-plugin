# Binder-design CLI examples

Tool schemas change. Query `tamarind --json tools --function binder-design`, inspect `tamarind --json schema TOOL`, and validate every settings file.

## Target structure input

```bash
tamarind --json files upload /absolute/path/target.pdb
```

Use the returned bare `filename` in the exact target-file field from the live schema.

## Validate a design payload

`design.yaml` should capture the tool's required mode/task, target, site/hotspots, binder class/length, candidate count, and intentional overrides.

```bash
tamarind --json validate TOOL --input design.yaml --name target-design-v1
```

If file validation fails, confirm the upload and filename. Do not replace a structure-file field with an amino-acid sequence.

## Authorized execution

After the user confirms material candidate count and scope:

```bash
tamarind --json submit TOOL --input design.yaml --name target-design-v1
tamarind --json wait target-design-v1 --timeout 14400 --poll-interval 20
tamarind --json results target-design-v1 --download /absolute/path/to/results
```

Extract the bundle and rank it:

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-binder-design-skill"
python3 "$SKILL_DIR/scripts/summarize_binder_metrics.py" /absolute/path/to/extracted-run --json
```

## Design-to-fold handoff

For generated sequences, create a fold batch whose per-job settings use the downstream tool's `sequence` field. For generated structures, download and inspect exact artifact paths, upload selected files, and use the returned filenames. CLI 0.2 does not provide a general result-file list or `fromJob` batch shortcut, so do not guess remote paths.

Submit original validated settings, not normalized validation output.
