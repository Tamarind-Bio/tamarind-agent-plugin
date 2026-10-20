---
name: tamarind-mcp-finetune
description: Fine-tune (train) a Tamarind-hosted model on the user's labeled data with submitFinetuningRun, then run the trained model by its modelId through MCP. Use for training a property, affinity, fitness, or enzyme predictor, a training sweep, retraining a new version of a model, or running a model already listed by listFinetunedModels. Not for stock pretrained inference, ordinary batch prediction, or unsupported custom training code.
---

# Fine-tune and run a model through MCP

Training and inference are two separate, durable jobs. Training registers a model; inference runs that model by its `id`.

## 1. Choose the trainer

Call `getAvailableModels()` (optionally with `search`). It lists the tools you can train with, such as `chemprop-finetune`, never the inference tool that runs the result. Models already trained are in `listFinetunedModels`, not here.

Call `getJobSchema(jobType="<trainer>")` for the training settings. If the user wants to run a model that already exists, skip to step 5.

## 2. Prepare and check the data

Check required columns, target units, identifiers, split strategy, class balance, leakage between train and held-out sets, and size limits. Upload the dataset with `uploadFile` and use the returned bare filename in the file setting.

`validateJob` does not compare column-name settings with the file's header, so a wrong column passes validation. Check every column-name setting against the actual header yourself before submitting.

## 3. Validate, estimate, authorize

Choose a unique `jobName` (letters, digits, `_` or `-`; the trained model takes this name). Call `validateJob(type="<trainer>", jobName=..., settings=...)` and require `valid: true` with no `mutatedFields`. To train a new version of an existing model, put its `id` (a model trained with the same trainer) in `settings.parentModelId` first, so validation checks the parent and the settings you submit are the ones that passed.

Call `estimateTime` with the same type and settings. Treat a finetune estimate as a placeholder, neither a forecast nor a cap: for `chemprop-finetune` it returned a flat 3600 s and 1 weighted hour whatever the epoch count. A 5-epoch run on 66 rows finished in about 32 s, while a large dataset trained for many epochs can run for hours. Say so when asking for authorization.

Surface the trainer, base model, epochs or steps, dataset size, split, and the estimate. Training spends compute; get explicit authorization from the live user before submitting.

## 4. Train once and poll

Follow `tamarind-mcp-submit-and-poll` for the lifecycle, with `submitFinetuningRun` in place of `submitJob`:

- Call `submitFinetuningRun(model="<trainer>", jobName=..., settings=...)` once. `model` is the trainer name, the field `submitJob` calls `type`.
- Add `projectTag` when the organization requires one. The 400's `availableProjects` is capped and can be absent; if it does not hold the intended project, call `listProjects` (only an `org`-scope project satisfies the policy), and ask the user when more than one could fit.
- Poll with the returned `jobName`; it is the stored name. If `endpoint` is not `/finetune`, the run was accepted as an ordinary job and may register no model, so say so.
- If the response is ambiguous, query `getJobs(jobName=...)` before any retry. Poll `getJobs` with a finite deadline; a local timeout never authorizes resubmission.

For a sweep (several training runs with one trainer), do not loop `submitFinetuningRun`. Call `submitBatch` once with the trainer as `type` and one settings row and job name per run, following `tamarind-mcp-batch`. It sends a finetune batch to the finetuning batch route itself; `endpoint` in the result names the route that accepted it.

## 5. Find the trained model

After the training job reaches an explicit success state, call `listFinetunedModels(type="<trainer>")` with the default `limit`. A small `limit` currently files the caller's own models under `organizationModels`, so search both `personalModels` and `organizationModels`.

Find the row whose `name` is the training job name, that has no `owner` (a teammate's row carries one), and that was `created` after you submitted. If more than one row still matches, stop and ask rather than picking one.

For a model that already exists, use the `id` the user gives. Otherwise call `listFinetunedModels` (with `type` when the trainer is known) and let the user choose from the candidate rows, showing `name`, `owner`, `type`, `created`, and `status`.

Names are not unique, so identify the model by `id` from here on. Then read the row:

- Only `status: "Available"` can run. If it is not Available yet, check again within the same finite deadline instead of retraining.
- `inferenceType` is the tool that runs the model; do not guess it from the trainer's name. A null `inferenceType` means the model has no inference tool.
- A row with `owner` is a teammate's model; run it by `id`, never by `modelName`.

## 6. Run inference

Call `getJobSchema(jobType="<inferenceType>")` and build the inference settings. Choose a unique inference `jobName` and validate with `validateJob(type="<inferenceType>", jobName=..., settings=...)`. It takes no model argument; the model reference is checked at submission. Before submitting, call `estimateTime` and get separate authorization from the live user when inference materially expands scope.

Pass the model as a top-level `modelId`, not inside `settings`:

```json
{"jobName": "<inference-job-name>", "type": "<inferenceType>", "modelId": "<id>", "settings": {}}
```

Run one input set with `submitJob`, following `tamarind-mcp-submit-and-poll`. For many independent inputs, call `submitBatch` once with `type` set to the `inferenceType` and the same top-level `modelId`, following `tamarind-mcp-batch`. Any other `type` is refused for that model.

## 7. Evaluate before use

Evaluate on held-out data and compare against the stock or base model. Report leakage risks, calibration limits, the applicability domain of the training data, and uncertainty before predictions are used downstream. Report the trainer, training job name, model `id`, `inferenceType`, and inference job names.
