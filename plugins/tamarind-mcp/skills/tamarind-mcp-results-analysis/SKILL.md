---
name: tamarind-mcp-results-analysis
description: Recover and analyze an existing Tamarind Bio job or batch through MCP by durable name, including bounded monitoring, logs, metrics, output-file inspection, cancellation, and downstream artifact selection. Use after submission or across sessions. Not for starting a new job or using the CLI.
---

# Recover Tamarind MCP results

Treat the durable job or batch name as the recovery key. Never create a replacement merely because the original client task ended.

## Recover state

- Single job: call `getJobs(jobName=...)`.
- Batch or pipeline: call `getJobs(batch=..., includeSubjobs=true)` and, when present, inspect its parent row separately by name.
- Active work: poll `getJobs` at 15-30 second intervals through a bounded client wait/session. Stop at a finite deadline and report the current state.
- Failed work: call `getJobLogs(jobName=..., maxLines=200)` and explain the actionable failure without automatically resubmitting.

Parse score fields defensively. Report only metrics actually present, say whether higher or lower is better, and distinguish confidence or computational affinity from experimental validation.

## Inspect outputs

Call `listJobFiles` first. Select files by evidence from the listing, not an assumed filename.

- Use `getJobFile` for targeted text, structures, tables, configs, or other files within its size limit.
- Use `getResult` only when the complete result archive is required. Treat its presigned URL as sensitive and do not quote it back to the user.
- For a downstream stage, prefer the exact `s3Path` returned by `listJobFiles` when the next live schema accepts it. Otherwise retrieve the artifact and re-upload it with `uploadFile`.

For structures, inspect local/global/interface confidence separately when present. Reject obviously malformed geometry and require independent structural validation before recommending a candidate. For design or docking outputs, preserve diverse candidates and do not optimize on one scalar score alone.

## Cancel or delete

Both operations are consequential. Resolve the exact durable target with `getJobs` first.

- Use `cancelJob` for one active job and `cancelBatch` for a batch or pipeline. Cancellation preserves rows and outputs.
- Use `deleteJob` only after explicit confirmation that the exact named job or batch should be permanently removed.
- Use `deleteFile` only after confirming the exact file or folder. Folder deletion is bulk deletion.

Never substitute a similarly named target, expand a wildcard, or delete active work unless the user explicitly includes it.

## Report

Return the durable name, current or terminal status, subjob counts when applicable, weighted hours and scores when present, inspected artifacts, analysis limits, and a precise downstream handoff if requested.
