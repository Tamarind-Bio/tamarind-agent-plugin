# CLI stage example

For each stage, use the same sequence:

```bash
tamarind --json schema TOOL
tamarind --json validate TOOL --input stage.yaml --name CAMPAIGN-stage
tamarind --json submit TOOL --input stage.yaml --name CAMPAIGN-stage
tamarind --json wait CAMPAIGN-stage --timeout 14400 --poll-interval 20
tamarind --json results CAMPAIGN-stage --download /absolute/path/to/stage-results
```

After extraction, choose the exact downstream artifact, upload it, and validate the next stage:

```bash
tamarind --json files upload /absolute/path/to/stage-results/selected.pdb
tamarind --json validate NEXT_TOOL --input next-stage.yaml --name CAMPAIGN-next
```

If the stage produces many independent candidates, switch to `tamarind-batch` for the next stage and checkpoint the parent plus every selected candidate name.

Never hide stage failures by advancing only the successful subset without reporting the stopped/failed rows.
