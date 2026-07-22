---
name: tamarind-mcp-tool-discovery
description: Choose a Tamarind Bio tool by querying the live MCP catalog and schema. Use when the user requests MCP, has not named a tool, several tools could fit, or availability and required inputs must be verified. Not for reconnecting OAuth or executing a tool that is already selected.
---

# Choose a live Tamarind tool

Never recommend a tool from memory alone. The catalog is account-scoped and changes over time.

## Narrow the catalog

1. Identify the input already available: sequence, structure, receptor plus ligand, fixed backbone, labeled table, density map, or library.
2. Identify the required output: structure, pose, affinity, designed sequence, generated molecule, embedding, property score, or ranked candidates.
3. Call `listModalities` and `listTags` when the correct facet values are not known.
4. Call `getAvailableTools` with `modality`, `function`, or a narrow `search`. Avoid an unfiltered catalog response.
5. Inspect the strongest candidate with `getJobSchema(jobType=...)`.

Recommend one primary tool and at most two conditional alternatives. Explain the input or scientific condition that changes the choice; avoid unsupported best-in-class claims.

## Treat the schema as authority

Confirm required fields, types, enum values, conditionals, defaults, file inputs, and account-visible variants. Do not copy settings between sibling models.

For a concrete proposed payload, call `validateJob` with a durable probe name. Require `valid: true` and no `mutatedFields` warning. Validation is free and does not authorize a paid run. If a file field fails because the file is absent, upload it with `uploadFile` or choose an exact `s3Path` from `listJobFiles`; do not guess a path.

Validation checks schema and character constraints, not scientific identity. Confirm molecule type independently, especially when nucleotide letters could also be parsed as amino-acid codes.

## Route execution

- One known job: use the matching MCP domain skill plus `tamarind-mcp-submit-and-poll`.
- One tool over many inputs: use `tamarind-mcp-batch`.
- Dependent stages: use `tamarind-mcp-pipeline`.

Compute trivial local properties locally when a standard library can answer them quickly. Reserve Tamarind for managed inference, durable artifacts, or platform workflows.
