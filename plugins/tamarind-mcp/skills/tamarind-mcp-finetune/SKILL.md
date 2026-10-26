---
name: tamarind-mcp-finetune
description: Fine-tune (train) a Tamarind-hosted model on the user's labeled data with submitFinetuningRun, then run it by modelId through MCP, for clearly benign research, diagnostic, or therapeutic development. Use for training or retraining a property, affinity, fitness, or enzyme predictor, a training sweep, or running a model from listFinetunedModels. Not for stock inference or custom training code.
---

# Fine-tune and run a model through MCP

## Confirm scope

Proceed only for clearly benign research, diagnostic, or therapeutic development; decline requests intended to cause harm. Training and inference spend compute, so get explicit authorization from the live user before each.

## Train

Find trainers with `getAvailableModels()` and their settings with `getJobSchema(jobType="<trainer>")`. Check the data's columns, units, split, balance, leakage and size, then `uploadFile` it. `validateJob` does not compare column-name settings with the file's header, so check them yourself.

Call `validateJob(type="<trainer>", jobName=..., settings=...)` and require `valid: true` with no `mutatedFields`; set `settings.parentModelId` first when retraining a model. Call `estimateTime`, but say a finetune estimate is neither a forecast nor a cap. Show the trainer, base model, epochs, data size, split and the estimate, and after authorization call `submitFinetuningRun(model="<trainer>", jobName=..., settings=...)` once, adding `projectTag` if required (`listProjects` if the 400 lacks it). Follow `tamarind-mcp-submit-and-poll` with a finite deadline, with `submitFinetuningRun` in place of `submitJob`. For a sweep, do not loop `submitFinetuningRun`; use one `submitBatch` with the trainer as `type`, following `tamarind-mcp-batch`.

## Find the model

Call `listFinetunedModels(type="<trainer>")` with the default `limit`; a small one misfiles your own models. Take the row named after the training job that has no `owner` and was `created` after submission. Ask if several match; if none is listed or Available yet, check again rather than retraining. For an existing model, use the user's `id` or let them choose. Then identify the model by `id`. Only `status: "Available"` runs, through its `inferenceType` (null means none).

## Run and evaluate

Validate and estimate the `inferenceType` job, then pass the model as a top-level `modelId`, not inside `settings`:

```json
{"jobName": "<name>", "type": "<inferenceType>", "modelId": "<id>", "settings": {}}
```

Use `submitJob` for one input set or one `submitBatch` for many, following `tamarind-mcp-submit-and-poll` or `tamarind-mcp-batch`. Compare against the base model on held-out data, and report leakage, the training data's applicability domain and uncertainty.
