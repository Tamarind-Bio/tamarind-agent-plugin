---
name: tamarind-mcp-finetune
description: Fine-tune a supported Tamarind-hosted model on labeled data and run its matching inference tool through MCP. Use for live account-visible finetune/inference pairs in protein, affinity, enzyme, or small-molecule workflows. Not for stock inference, ordinary batch prediction, or unsupported custom training code.
---

# Fine-tune and run inference through MCP

Treat training and inference as two durable, separately validated jobs with explicit data and evaluation boundaries.

## Confirm a supported pair

Call `getAvailableTools(function="finetuning")` or use a narrow `search`. Inspect both the training and inference tools with `getJobSchema`. Require the live schemas to document the handoff; do not infer a pair from names alone.

## Prepare training

Check required columns, target units, identifiers, split strategy, class balance, leakage, held-out evaluation, and size limits. Upload the dataset with `uploadFile` and use the returned bare filename.

Call `validateJob` for the training payload, require no mutation warning, and call `estimateTime`. Surface the base model, epochs or steps, dataset size, split, expected runtime, and weighted hours when available. Obtain explicit authorization because training can be materially expensive.

## Train and infer

Run training with `tamarind-mcp-submit-and-poll`. Require an explicit success state. Inspect `listJobFiles` and the training row for the exact trained-model reference required by the inference schema.

Build and validate the inference payload with that exact reference. Estimate and separately authorize inference when it materially expands scope, then run it through `tamarind-mcp-submit-and-poll` or `tamarind-mcp-batch` for many independent inputs.

Evaluate on held-out data and compare against the stock/base model. Report leakage risks, calibration limits, dataset applicability, and uncertainty before using predictions downstream.
