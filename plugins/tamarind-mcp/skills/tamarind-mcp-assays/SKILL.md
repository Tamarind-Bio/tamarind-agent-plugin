---
name: tamarind-mcp-assays
description: Order wet-lab assays of designed sequences from Tamarind's partner labs (Adaptyv, Ginkgo, A-Alpha Bio) through MCP, then track the order and download the lab's results. Use when the user wants real lab measurements (binding, expression, stability, developability), a price for them, or the status of an existing order. Not for computational prediction or compute jobs.
---

# Order and track wet-lab assays through MCP

A lab order is real spend, and estimating or ordering sends the sequences to a third-party lab. Authorization must come from the live user for that exact order. The tool descriptions carry field formats and error codes; this skill is the order of operations and the decisions.

## Pick the assay and target

Call `listAssayTypes()`. If `wetLabAccess` is false, stop and point the user to `requestAccessUrl`. Choose the type from what the user wants measured, and read its `modalities`, sequence limits, `settings` and `turnaround` live.

When the type has a `targetsProvider`, call `listAssayTargets(provider=..., search=...)`. If several targets match, let the user choose: species and construct differ. Put the `id` in the target setting the type lists; the live `settings` decide its name.

## Validate, then estimate if wanted

Call `submitAssay(mode="validate", ...)` until `valid: true`. It creates nothing and contacts no lab. Send sequences as named objects, using the design's own identifier as `name` so results map back; plain strings get auto-named.

`mode="estimate"` sends the sequences to the lab to be priced. Ask the user first and name what will be disclosed: the lab, the assay, the target and which sequences. An estimate is not a quote.

## Submit

Summarize the lab, assay, target, sequence count and any estimate, and submit only after the user confirms. Call `mode="submit"` with a new UUID as `idempotencyKey`. Submit exactly once. If the outcome is unclear, retry with the SAME key and the SAME fields, which returns the original order. Never make a new key to retry.

Follow a refusal's `code`. On `duplicate_order`, ask the user before resending with `confirmDuplicate=true` and a NEW key. With `teamNotified: true`, do not resubmit.

## Follow up and cancel

Call `listAssays(assayId=...)`. Lab work takes days to weeks, so do not poll in a loop; check when the user asks. Check `resultsAvailable`, not `status`; once it is true, the same call returns the file links. The links expire, so fetch fresh ones rather than storing or repeating them.

Call `cancelAssay` only after the user confirms and only when the order's `cancellable` is true; otherwise send them to Tamarind support.
