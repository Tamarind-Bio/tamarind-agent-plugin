---
name: tamarind-mcp-antibody
description: Design, redesign, model, number, humanize, or search antibodies, nanobodies, VHHs, and TCRs with Tamarind Bio through MCP. Use for CDR-aware and repertoire-specific workflows when MCP is requested. Not for generic non-antibody binder design, ordinary complex folding, or developability scoring alone.
---

# Engineer antibodies through MCP

Clarify antibody versus VHH/nanobody/TCR and the goal: de novo CDR design, redesign, structure prediction, numbering, humanization, or repertoire/paratope search.

## Select and inspect

Call `getAvailableTools(modality="antibody")`. Narrow with a live function such as antibody design or structure prediction, then call `getJobSchema` for the strongest fit.

Prefer antibody-specific tools when chain pairing, CDR regions, framework numbering, epitope/hotspot steering, or humanization matters. Route generic co-folding to `tamarind-mcp-structure-prediction` and non-antibody binders to `tamarind-mcp-binder-design`.

## Build and validate

Capture the heavy/light or VHH sequence, framework, antigen structure and chain, epitope or hotspots, CDR regions and lengths, candidate count, and excluded residues required by the live schema. Upload structures with `uploadFile` and use the returned filename or an accepted prior-job `s3Path`.

Call `validateJob`, require no mutation warning, and call `estimateTime`. Confirm chain identities, numbering scheme, CDR scope, candidate count, refolding plan, filters, and estimated spend before submission.

## Execute and filter

Use `tamarind-mcp-submit-and-poll`. For multiple independent candidates, use `tamarind-mcp-batch` rather than repeated `submitJob` calls.

Rank design outputs on interface confidence and geometry, then apply antibody-specific developability filters through `tamarind-mcp-developability`. Preserve sequence diversity and flag liabilities instead of selecting only the top scalar score. Predictions prioritize experiments; they do not replace binding and developability assays.
