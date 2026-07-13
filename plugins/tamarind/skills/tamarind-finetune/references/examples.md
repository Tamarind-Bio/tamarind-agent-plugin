# Fine-tune and inference CLI examples

Use only finetune/inference pairs returned by the active account's live catalog.

## Validate the training stage

```bash
tamarind --json tools --function finetuning
tamarind --json schema FINETUNE_TOOL
tamarind --json files upload /absolute/path/training-data.csv
tamarind --json validate FINETUNE_TOOL --input train.yaml --name model-train-v1
```

Check data columns, units, splits, leakage, base model, epochs/steps, and dataset size. Obtain explicit confirmation before training spend.

## Train and recover

```bash
tamarind --json submit FINETUNE_TOOL --input train.yaml --name model-train-v1
tamarind --json wait model-train-v1 --timeout 28800 --poll-interval 30
SKILL_DIR="/absolute/path/to/the/tamarind-finetune-skill"
python3 "$SKILL_DIR/scripts/safe_status.py" model-train-v1
```

Require a successful terminal status.

## Validate the matching inference stage

Inspect `tamarind --json schema INFERENCE_TOOL` for the exact trained-model reference. Build `infer.yaml` and require full validation:

```bash
tamarind --json validate INFERENCE_TOOL --input infer.yaml --name model-infer-v1
```

Do not omit a trained-model field for validation and add it only on submit. A setting that the live schema rejects is not safe to bypass.

After validation and authorization:

```bash
tamarind --json submit INFERENCE_TOOL --input infer.yaml --name model-infer-v1
tamarind --json wait model-infer-v1 --timeout 14400 --poll-interval 20
tamarind --no-json results model-infer-v1 --download /absolute/path/to/results
```

Evaluate on held-out data and compare against the base model.
