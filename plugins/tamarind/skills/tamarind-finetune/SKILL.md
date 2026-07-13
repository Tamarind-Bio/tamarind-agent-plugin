---
name: tamarind-finetune
description: Fine-tune a Tamarind-hosted model on user-provided labeled data and run the matching inference tool with the trained job. Use for supported finetune/inference pairs in protein, affinity, enzyme, or small-molecule workflows. Not for stock pretrained inference, ordinary batch prediction, or unsupported custom training code.
---

# Fine-tune and run inference

Treat training and inference as two durable jobs with explicit data and evaluation boundaries.

## Confirm a supported pair

```bash
tamarind --json tools --function finetuning
tamarind --json tools --search finetune
tamarind --json schema FINETUNE_TOOL
tamarind --json schema INFERENCE_TOOL
```

Require a live, account-visible finetune tool and its matching inference tool. Do not infer a pair from naming alone or submit fields that fail validation.

## Prepare data and validate training

Check required columns, target units, sequence/structure identifiers, split strategy, class balance, leakage, and size limits. Upload the dataset with `tamarind --json files upload PATH` and use the returned filename.

```bash
tamarind --json validate FINETUNE_TOOL --input train-settings.yaml --name TRAIN_NAME
```

Surface base model, epochs/steps, dataset size, and expected weighted-hour spend. Training can be materially expensive; obtain explicit confirmation before submission.

## Train, recover, then validate inference

```bash
tamarind --json submit FINETUNE_TOOL --input train-settings.yaml --name TRAIN_NAME
# Run tamarind-submit-and-poll's filtered status probe; use wait only for JobStatus.
tamarind --json wait TRAIN_NAME --timeout 28800 --poll-interval 30
```

Require a successful terminal status. Build the inference payload using the exact trained-model reference required by the live inference schema, often the training job name, then validate it:

```bash
tamarind --json validate INFERENCE_TOOL --input infer-settings.yaml --name INFER_NAME
tamarind --json submit INFERENCE_TOOL --input infer-settings.yaml --name INFER_NAME
# Run tamarind-submit-and-poll's filtered status probe; use wait only for JobStatus.
tamarind --json wait INFER_NAME --timeout 14400 --poll-interval 20
tamarind --json results INFER_NAME --download /absolute/path/to/results
```

Do not bypass failed validation. Evaluate on held-out data and compare against the stock/base model before using predictions downstream.

Read [references/tools.md](references/tools.md) and [references/examples.md](references/examples.md) for supported families and dataset shapes.
