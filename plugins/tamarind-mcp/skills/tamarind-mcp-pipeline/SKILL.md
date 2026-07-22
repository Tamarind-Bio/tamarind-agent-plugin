---
name: tamarind-mcp-pipeline
description: Orchestrate multiple dependent Tamarind Bio tools as a resumable MCP campaign where successful stages feed later stages, such as design to fold to score. Use when stages depend on earlier artifacts or metrics. Not for one job, one independent batch, a nonexistent submitPipeline call, or CLI orchestration.
---

# Chain Tamarind jobs through MCP

The current MCP surface has no declarative pipeline submission tool. Build an explicit resumable campaign from `validateJob`, `estimateTime`, `submitJob` or `submitBatch`, bounded `getJobs` polling, and server-side artifact paths.

## Plan the data flow

For every stage record:

- deterministic stage and durable job/batch names;
- live tool and validated settings;
- required artifact and producing stage;
- success criterion and metric direction;
- fan-out and `topN` boundary;
- chosen output file and exact `s3Path`;
- current remote status and authorization state.

Keep this as a reviewable state object in the task or a local JSON file when the client has a workspace. Re-read authoritative remote state before resuming.

## Execute one stage at a time

For each stage:

1. Call `getJobSchema`.
2. Build the stage settings from confirmed inputs.
3. Call `validateJob`; require `valid: true` and no mutation warning.
4. Call `estimateTime` and confirm any material new scope.
5. Call `submitJob` once, or one `submitBatch` for a bounded fan-out.
6. Poll with `getJobs` at 15-30 second intervals and a finite deadline.
7. On explicit success, call `listJobFiles`; select the output using stage-specific evidence.
8. Pass the exact returned `s3Path` into the next schema when supported. Otherwise retrieve with `getJobFile` and re-upload with `uploadFile`.

Never guess filenames or paths. Never advance a failed, stopped, or still-running stage.

## Fan-out and selection

Use `submitBatch(fromJob=...)` or `submitBatch(fromFile=...)` only when one generated sequence maps directly into the downstream `sequenceField`. For target-candidate complexes or any row that combines shared context with one candidate, build explicit `settings` plus `jobNames` so every final input is reviewable. Bound the expansion with `topN`, validate shared or explicit settings, estimate total cost, and obtain authorization before the fan-out.

Inspect and rank successful subjobs only. Advance a diverse, evidence-backed shortlist rather than every candidate or one scalar winner.

## Recovery and safety

- If a submit response is ambiguous, query its durable name; do not invoke the submit tool again.
- If a polling deadline expires, checkpoint the active status and reattach later; do not restart the stage.
- On failure, call `getJobLogs` with a bounded line count, checkpoint the failure, and stop.
- Confirm total campaign scope before the first paid stage and again before a material fan-out or changed payload.
- Use `cancelJob` or `cancelBatch` only after resolving and confirming the exact active target.
- Preserve intermediate outputs, settings, metrics, and selection rationale for reproducibility.

Return the campaign state, completed and pending stages, durable names, selected artifacts, spend information, and the exact next safe action.
