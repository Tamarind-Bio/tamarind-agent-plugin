---
name: tamarind-mcp-developability
description: Score protein or antibody candidates for stability, aggregation, solubility, viscosity, polyreactivity, glycosylation, immunogenicity, and related developability risks with Tamarind Bio through MCP. Use as a post-design filter. Not for generating molecules, folding structures, or measuring binding alone.
---

# Filter candidates for developability

Treat developability as a panel of orthogonal risks, not one universal score.

## Select the panel

Call `listTags` to obtain current function values, then use filtered `getAvailableTools` calls for developability, stability, aggregation, solubility, immunogenicity, or another relevant axis. Inspect each selected tool with `getJobSchema`.

Match the input type and modality. Sequence-only, structure-based, paired-antibody, and nanobody-specific tools are not interchangeable.

Upload structures with `uploadFile` or use an accepted prior-job `s3Path`. Call `validateJob` and `estimateTime` for each planned tool. For a candidate list, use `tamarind-mcp-batch` so one settings policy is applied consistently; validate every distinct conditional payload shape before multiplying the run.

## Execute and interpret

Use `tamarind-mcp-submit-and-poll` for a single candidate and `tamarind-mcp-batch` for many independent candidates.

Report every risk axis separately with the tool, units, direction, and threshold rationale. Preserve a Pareto set when candidates trade affinity against solubility, stability, or immunogenicity. Computational predictions prioritize assays and formulation work; they do not replace them.
