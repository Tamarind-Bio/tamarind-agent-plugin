---
name: tamarind-mcp-binder-design
description: Design new protein, peptide, macrocycle, or small-molecule binders against a target with Tamarind Bio through MCP, then refold and rank candidates. Use for de novo generation when MCP is requested. Not for antibody CDR engineering, fixed-backbone inverse folding, docking an existing ligand, or predicting an existing structure.
---

# Design de novo binders through MCP

Treat binder design as a generate-and-filter campaign, not a deterministic answer.

## Define and select

Clarify the target structure or sequence, target chains/site/hotspots, binder class, length or chemistry constraints, candidate count, and downstream filters. Use `tamarind-mcp-antibody` for antibody or VHH CDR workflows.

Call `getAvailableTools(function="binder-design")`. For small-molecule generation, discover the exact current function with `listTags` before filtering. Inspect the chosen model with `getJobSchema`; do not assume a remembered name or field remains available.

## Validate generation

Upload the target with `uploadFile`, or use an accepted `s3Path` from `listJobFiles`. Build only fields supported by the live schema and call `validateJob`. Require `valid: true` with no mutation warning.

Call `estimateTime`. Surface candidate count, sampling budget or steps, target site, scaffold or length range, refolding, filters, and estimated spend. Candidate count often dominates cost, so obtain explicit authorization for the validated scope.

## Execute the funnel

Run the generation stage with `tamarind-mcp-submit-and-poll`. Use `listJobFiles` to identify the actual sequence or structure outputs.

For many generated sequences, use one bounded `submitBatch` rather than individual submissions. Use `fromJob` only when the downstream schema expects each generated sequence by itself in `sequenceField`. When refolding target-binder complexes that require a combined target and candidate per row, build explicit `settings` plus matching `jobNames` instead; a naive `fromJob` batch could fold the binder alone. Validate every final complex row, estimate the fan-out, and reconfirm scope when it materially expands.

Rank on multiple signals: independent refold confidence, interface geometry, target-site satisfaction, liabilities, uniqueness, and diversity. Carry a diverse shortlist into wet-lab testing; never optimize on one metric alone.
