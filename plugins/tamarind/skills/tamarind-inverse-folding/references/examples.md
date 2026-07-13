# Inverse-folding and PLM CLI examples

Confirm the live tool and schema before using these patterns.

## Fixed-backbone design

```bash
tamarind --json files upload /absolute/path/backbone.pdb
tamarind --json schema proteinmpnn
tamarind --json validate proteinmpnn --input design.yaml --name mpnn-design-v1
```

The settings file should use the returned bare filename plus the live schema's designed-chain/residue, sequence-count, temperature, model, and omit-AA fields.

After explicit scope confirmation:

```bash
tamarind --json submit proteinmpnn --input design.yaml --name mpnn-design-v1
tamarind --json wait mpnn-design-v1 --timeout 7200 --poll-interval 15
tamarind --json results mpnn-design-v1 --download /absolute/path/to/results
```

## Sequence-only PLM task

```bash
tamarind --json tools --function protein-language-models
tamarind --json schema TOOL
tamarind --json validate TOOL --input plm.yaml --name plm-run-v1
```

Model size, task, sequence length, and generation/sample count are consequential choices.

## Verify designed sequences

Parse the output, select a diverse subset, and fold each sequence through a structure tool. Put sequences in the downstream `sequence` field, not a template or structure-file field. Use `tamarind-batch` for the independent folds.

CLI 0.2 does not expose `fromJob` or a general remote file-list command; download, inspect, and explicitly marshal artifacts between stages.
