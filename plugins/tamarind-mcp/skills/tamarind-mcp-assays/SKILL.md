---
name: tamarind-mcp-assays
description: Order wet-lab assays of designed sequences from Tamarind's partner labs (Adaptyv, Ginkgo, A-Alpha Bio) through MCP — binding affinity, binding screens, expression, thermostability, fluorescence, developability — then track the order and download the lab's results. Use when the user wants real lab measurements, a price or turnaround for one, or the status or results of an existing assay order. Not for computational prediction of binding, stability or developability, or for running compute jobs.
---

# Order and track wet-lab assays through MCP

A lab order is real spend, and its sequences leave Tamarind for a third-party lab. Keep the user in control at three points: before estimating, before submitting, and before cancelling. Authorization must come from the live user for that exact order.

Five tools cover the whole flow: `listAssayTypes`, `listAssayTargets`, `submitAssay` (`mode` = `"validate"`, `"estimate"` or `"submit"`), `listAssays` and `cancelAssay`.

## 1. Check access and pick the assay

Call `listAssayTypes()` (optionally with `provider`). If `wetLabAccess` is false, stop. The other tools will answer 403 `wetlab_access_required`, and the user can ask for access at `requestAccessUrl`.

Pick the `assayType` from what the user wants measured; do not hardcode the catalog. Read from that type:

- `modalities`: send `modality` ("antibody" or "protein") when it lists both.
- `minSequences` / `maxSequences`: some types need 20 or more.
- `settings`: which are required, the allowed `options`, and `list` for array values.
- `targetsProvider`: set when the assay needs a target (step 2).
- `turnaround`: how long the lab takes. Tell the user.

## 2. Find the target (binding assays)

When `targetsProvider` is set, call `listAssayTargets(provider=<targetsProvider>, search=<name, alias or UniProt id>)`. If `truncated` is true, narrow `search` rather than raising `limit`. When several targets match, show them and let the user choose, because species, tag and construct differ (canine and human PD-L1 are different targets).

Put the chosen `id` in `settings`: `targetId` for Adaptyv, `targetIds` (a list) for A-Alpha Bio, or `targetAntigen` for Ginkgo.

## 3. Build and validate the order

- `sequences`: antibodies as `{"name", "heavy", "light"}` objects (or "HEAVY:LIGHT" strings); proteins as `{"name", "sequence"}` objects (chains joined with ":"). Name every sequence so results map back to designs. Names and sequences must all differ.
- Many sequences: upload a CSV with `uploadFile`, then pass `csvFile` and `columnMapping` instead of `sequences`.
- Call `submitAssay(mode="validate", ...)`. It is the default mode, creates nothing and sends nothing to a lab. Fix every item in `details` and validate again until `valid: true`.
- Keep the exact validated fields; estimate and submit take the same ones.

A valid order can still be refused at submit (`duplicate_order`, `assays_blocked`, `assays_in_flight`): validation does not compare it with earlier orders.

## 4. Estimate (optional; ask first)

`submitAssay(mode="estimate", ...)` sends the sequences to the lab to be priced. Ask the user before running it.

Report `estimatedCostUsd`, `costPerSequenceUsd`, `turnaround` / `turnaroundDays` and `note`. A null price means the target is priced on request. An estimate is not a quote; Tamarind confirms the final price with the user before approving the order. On 400 `quote_rejected` the lab would not accept the order as it is. On 503 `estimate_unavailable`, try later or place the order without an estimate.

## 5. Place the order

Summarize for the user: lab and assay type, target, sequence count, settings, any estimate, and that Tamarind reviews the order and arranges payment before the lab starts. Submit only after they confirm this exact order.

Generate one new UUID for this order and call `submitAssay(mode="submit", idempotencyKey=<uuid>, ...)` with the validated fields. Submit exactly once. If the call fails, times out or its outcome is unclear, retry with the SAME key and the SAME fields: you get the original order back (`idempotentReplay: true`), never a second one. Never make a new key to retry.

Give the user the `assay.assayId`; a new order is `pending_approval`.

When it is refused, follow the `code`:

- `duplicate_order`: nothing was created. Show `duplicateOfOrderId` and ask whether the user wants a second, separately billed order. Only if they do, resend with `confirmDuplicate=true` and a NEW key.
- `teamNotified: true` (`assays_blocked`, `order_incomplete`, `provider_error`): do not resubmit. Tamarind has been notified and will follow up.
- `assays_in_flight`: check `listAssays` in a minute. If the order does not appear, send the user to support rather than retrying.
- `idempotency_in_progress`: wait a minute, then retry with the same key.
- A 500 that carries an `assayId`: the order exists. Do not resubmit; look it up.
- `wetlab_access_required`, or an unclaimed trial key: stop and tell the user.

## 6. Follow the order and get results

`listAssays(assayId=...)` returns one order. It normally goes `pending_approval` → `approved` → `in_progress` → `completed`. Lab work takes days to weeks, so do not poll in a loop: check when the user asks, or tell them when to look again.

Check `resultsAvailable`, not `status`. Once it is true, the same call also returns `results.files` (name and download URL). Download what the user needs right away and map rows back to the sequence names. The links expire: call `listAssays(assayId=...)` again for fresh ones, and do not store them or repeat them in the final answer. `complete: false` means the files in `missingFiles` are not downloadable yet. A `resultsError` means the order is fine but its files could not be listed just now; try again later.

`listAssays()` without `assayId` lists orders newest first. Pass `nextToken` back until it is null, optionally filtering by `status`.

## 7. Cancel (ask first)

Check the order's `cancellable` first. Adaptyv orders cannot be cancelled here; send the user to Tamarind support. Cancelling cannot be undone, so call `cancelAssay(assayId=..., reason=...)` only after the user confirms. A Ginkgo order shows `cancelling` until Ginkgo confirms.

On 409 `approval_in_progress`, retry in a minute. On 409 `approval_under_review`, send the user to support. On 502 `cancel_unconfirmed`, check the order with `listAssays` before trying again.
