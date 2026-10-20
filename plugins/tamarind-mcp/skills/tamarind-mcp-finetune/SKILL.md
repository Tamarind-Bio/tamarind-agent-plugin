---
name: tamarind-mcp-finetune
description: Fine-tune (train) a Tamarind-hosted model on the user's labeled data with submitFinetuningRun, then run the trained model by its modelId through MCP. Use for training a property, affinity, fitness, or enzyme predictor, a training sweep, retraining a new version of a model, or running a model already listed by listFinetunedModels. Not for stock pretrained inference, ordinary batch prediction, or unsupported custom training code.
---

# Fine-tune and run a model through MCP

Training and inference are separate jobs: training registers a model, and inference runs it by `id`. The tool descriptions carry field details.

## Train

Call `getAvailableModels()` for the trainers (e.g. `chemprop-finetune`) and `getJobSchema(jobType="<trainer>")` for their settings. To run a model that already exists, skip to "Find the model".

Check the data: required columns, units, split, class balance, leakage between train and held-out sets, and size limits. Upload it with `uploadFile`. `validateJob` does not compare column-name settings with the file's header, so check them against the header yourself.

Call `validateJob(type="<trainer>", jobName=..., settings=...)` and require `valid: true` with no `mutatedFields`. For a new version of a model, put its `id` in `settings.parentModelId` before validating. Call `estimateTime`, but a finetune estimate is neither a forecast nor a cap (it returned a flat 1 weighted hour for `chemprop-finetune` whatever the epochs), so say so. Surface the trainer, base model, epochs, dataset size and split, and get explicit authorization from the live user.

Call `submitFinetuningRun(model="<trainer>", jobName=..., settings=...)` once, adding `projectTag` if the organization requires one (call `listProjects` if the 400's `availableProjects` lacks the right project). Follow `tamarind-mcp-submit-and-poll`: poll the returned `jobName` with a finite deadline, and check `getJobs` before any retry. For a sweep, do not loop `submitFinetuningRun`; call `submitBatch` once with the trainer as `type`, following `tamarind-mcp-batch`.

## Find the model

After training succeeds, call `listFinetunedModels(type="<trainer>")` with the default `limit`, since a small one currently files your own models under `organizationModels`. Take the row whose `name` is the training job name, that has no `owner`, and that was `created` after you submitted; if several match, ask. If it is not listed or not yet Available, check again within the deadline rather than retraining. For an existing model, use the `id` the user gives, or let them choose from `listFinetunedModels`.

Names are not unique, so identify the model by `id` from here on. Only `status: "Available"` can run, and `inferenceType` is the tool that runs it (null means none).

## Run the model

Build settings from `getJobSchema(jobType="<inferenceType>")`, validate with `validateJob(type="<inferenceType>", jobName=..., settings=...)`, and call `estimateTime` and get authorization before submitting when inference expands scope. Pass the model as a top-level `modelId`, not inside `settings`:

```json
{"jobName": "<inference-job-name>", "type": "<inferenceType>", "modelId": "<id>", "settings": {}}
```

Use `submitJob` for one input set, following `tamarind-mcp-submit-and-poll`, or one `submitBatch` with the same `type` and `modelId` for many, following `tamarind-mcp-batch`.

Evaluate on held-out data against the base model. Report leakage risks, the training data's applicability domain and uncertainty before the predictions are used downstream.
