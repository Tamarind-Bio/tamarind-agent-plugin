---
name: tamarind-mcp-batch
description: Run one Tamarind Bio tool across many independent inputs with one MCP submitBatch call, then monitor subjobs and rank completed results. Use for libraries, screens, generated-sequence refolding, or repeated inference. Not for one input, dependent tool stages, loops of submitJob, or CLI batches.
---

# Run a Tamarind MCP batch

A batch multiplies throughput and possible weighted-hour spend. Keep one tool and one scientific settings policy across the batch.

## Choose one input mode

Inspect the tool with `getJobSchema`, then use exactly one `submitBatch` mode:

1. `fromJob`: use a completed sequence-design job as the source when every downstream row consists of that generated sequence in one `sequenceField`.
2. `fromFile`: use a workspace FASTA/CSV filename or an exact prior-job `s3Path`.
3. `settings` plus matching `jobNames`: use explicit per-job settings when rows need full individual control.

Use `topN` to bound generated-sequence fan-out and `sharedSettings` only for fields valid for every generated row. Do not call `submitJob` in a loop.

`fromJob` and `fromFile` do not construct target-candidate complexes. If the downstream schema requires a combined target and candidate value such as `TARGET:BINDER`, build explicit per-row `settings` plus `jobNames`; otherwise the batch may fold or score the candidate alone.

## Validate and estimate

For explicit mode, call `validateJob` for every final row when feasible and at least every distinct conditional shape for very large inputs. Require `valid: true` without `mutatedFields`. Check duplicate names, file availability, input count, sampling settings, and schema compatibility.

For `fromJob` or `fromFile`, inspect the source and validate a representative final settings object containing the intended sequence field and shared settings. Treat server-side expansion as consequential even when not all generated rows can be prevalidated client-side.

Call `estimateTime` for each distinct settings shape. Multiply by the intended row count or use the returned expansion count. Surface the total count, wall-clock interpretation, and weighted hours when available.

Authorization for multiplied spend must come from the live user. If a numeric ceiling is specified, pass `weightedHoursBudget` to `submitBatch`; if the estimate cannot verify the ceiling, stop. A no-spend validation or setup request never authorizes the batch.

## Submit once

Call `submitBatch` exactly once with a unique `batchName`, one tool `type`, the chosen input mode, optional per-job timeout, and authorized budget.

If the result is ambiguous, do not call `submitBatch` again. Query `getJobs(batch=BATCH_NAME, includeSubjobs=true)` and the parent name first.

## Monitor with a bound

Poll `getJobs(batch=..., includeSubjobs=true)` at a moderate interval through the client's bounded wait/session mechanism. Track completed, active, failed, and stopped counts. Do not hide partial failures behind an aggregate status.

Stop after a finite deadline and report the batch as still active; never resubmit because a local wait ended. For failed subjobs, inspect a bounded number of representative logs with `getJobLogs` rather than flooding context.

Use `cancelBatch` to stop the whole active batch after confirming its exact name. Do not fan out `cancelJob` calls.

## Rank results

Rank only successful terminal subjobs. Keep incomplete, unknown-status, and unscored rows explicitly unranked. Confirm metric direction: affinity, energy, PAE, RMSD, Kd/Ki, and IC50 are commonly lower-better, while confidence scores are commonly higher-better.

Use `listJobFiles` and targeted `getJobFile` calls for selected subjobs. Return the batch name, input mode, total and per-status counts, budget/weighted hours when present, ranking metric and direction, shortlisted artifacts, and limitations.
