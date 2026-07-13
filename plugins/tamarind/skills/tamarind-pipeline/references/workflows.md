# Resumable campaign patterns

CLI 0.2 runs pipelines as explicit stages. Each stage has a durable job name, bounded wait, local result directory, and checkpoint entry.

## Design to fold to score

1. Validate and run the design tool.
2. Download and rank designs.
3. Select a diverse subset and record the rationale.
4. Build a fold batch from selected sequences.
5. Validate the fold settings shapes, confirm multiplied scope, and run the batch.
6. Rank completed folds by the correct structure/interface metric.
7. Upload selected structures and run the score/developability stage.

## Structure to dock to rescore

1. Obtain or predict the receptor structure.
2. Download and inspect the exact receptor artifact.
3. Upload it and validate the docking payload.
4. Run docking or a ligand batch.
5. Extract top poses and run a distinct rescoring method when justified.

## Stage checkpoint

Maintain fields like:

```json
{
  "campaign": "example",
  "stages": [
    {
      "name": "design",
      "jobName": "example-design-v1",
      "tool": "TOOL",
      "status": "Complete",
      "settings": "/absolute/path/design.yaml",
      "results": "/absolute/path/design-results",
      "selectedArtifacts": []
    }
  ]
}
```

Before resuming, query each recorded `jobName`. Never restart a completed stage or retry an ambiguous submission without checking remote state.
