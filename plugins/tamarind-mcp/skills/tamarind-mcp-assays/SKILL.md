---
name: tamarind-mcp-assays
description: Order wet-lab assays of designed sequences from Tamarind's partner labs (Adaptyv, Ginkgo, A-Alpha Bio) through MCP for clearly benign research, diagnostic, or therapeutic development, then track or cancel the order and download results. Use for real lab measurements, their price, or an existing order. Not for computational prediction or compute jobs.
---

# Order and track wet-lab assays through MCP

## Confirm scope

Proceed only for clearly benign research, diagnostic, or therapeutic development; decline requests intended to cause harm. Estimating or ordering sends sequences to a third-party lab, and an order is real spend. Authorization must come from the live user for that exact order.

## Choose the assay and target

Call `listAssayTypes()`. If `wetLabAccess` is false, stop and share `requestAccessUrl`. Read the type's `modalities`, sequence limits, `settings` and `turnaround` live. If it has a `targetsProvider`, call `listAssayTargets(provider=..., search=...)` and let the user choose among matches. Put the `id` in the type's target setting; the live `settings` decide its name.

## Validate and estimate

Call `submitAssay(mode="validate", ...)` until `valid: true`; it contacts no lab. Send sequences as objects named with the design identifiers. `mode="estimate"` sends the sequences to the lab to be priced. Ask the user first and name what will be disclosed: lab, assay, target and sequences.

## Submit

Once the user confirms the lab, assay, target, settings, named sequences and any estimate (again if any change), call `mode="submit"` with a new UUID `idempotencyKey`. Submit exactly once. If the outcome is unclear, retry with the SAME key and the SAME fields. Never make a new key to retry. On `duplicate_order`, resend with `confirmDuplicate=true` and a NEW key only if the user wants a second, separately billed order. With `teamNotified: true`, do not resubmit.

## Follow up

Call `listAssays(assayId=...)`; do not poll in a loop. Check `resultsAvailable`, not `status`; the same call then returns file links. The links expire, so fetch fresh ones. Call `cancelAssay` only with the user's OK and when `cancellable` is true; otherwise refer them to Tamarind support.
