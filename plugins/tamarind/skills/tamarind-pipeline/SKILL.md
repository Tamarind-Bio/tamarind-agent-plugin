---
name: tamarind-pipeline
description: Orchestrate multiple dependent Tamarind Bio tools as a resumable CLI campaign where each successful stage feeds the next, such as design to fold to score. Use when later stages depend on earlier artifacts or metrics. Not for one job or one tool applied independently across many inputs.
---

# Chain Tamarind jobs through CLI stages

CLI 0.1 does not expose a declarative server-side pipeline command. Use an explicit, resumable campaign: validate, submit, wait, inspect, download, and checkpoint each stage before starting the next.

## Plan the data flow

For each stage record:

- stage name and durable job name;
- tool and validated settings file;
- required input artifact and producing stage;
- success criterion and metric direction;
- fan-out/batch boundary;
- output directory and selected artifact.

Keep this state in a local `pipeline-state.json` or equivalent reviewable file. Re-read remote status before resuming; never infer success from the existence of a local command process.

## Execute one stage at a time

For each stage:

```bash
tamarind --json schema TOOL
tamarind --json validate TOOL --input stage-settings.yaml --name STAGE_JOB
tamarind --json submit TOOL --input stage-settings.yaml --name STAGE_JOB
# Run tamarind-submit-and-poll's filtered status probe; use wait only for JobStatus.
tamarind --json wait STAGE_JOB --timeout 14400 --poll-interval 20
tamarind --no-json results STAGE_JOB --download /absolute/path/to/stage-results
```

Inspect `JobStatus` after wait. On failure, capture `tamarind --json logs STAGE_JOB`, checkpoint the failure, and stop. Do not cancel or resubmit automatically.

## Transfer artifacts explicitly

CLI 0.1 lacks a general remote result-file listing command. After a successful stage:

1. Extract and inspect its downloaded bundle.
2. Select the exact artifact using stage-specific evidence.
3. Upload it with `tamarind --json files upload /absolute/path/artifact`.
4. Put the returned bare filename into the next stage's settings.
5. Validate the next stage before submitting.

When a stage fans out over many candidates, use `tamarind-batch`; inspect and rank completed subjobs before advancing only the selected candidates.

## Safety and recovery

- Confirm total intended campaign scope before the first paid stage and again before any large fan-out.
- Use deterministic unique names derived from the campaign and stage.
- If a submit result is ambiguous, query the job name before any retry.
- Resume by reading `pipeline-state.json` and remote status; do not restart completed stages.
- Preserve intermediate outputs and selection rationale for reproducibility.

Read [references/workflows.md](references/workflows.md) for campaign shapes and [references/examples.md](references/examples.md) for stage examples. Treat live CLI schemas and validation results as authoritative when an example drifts.
