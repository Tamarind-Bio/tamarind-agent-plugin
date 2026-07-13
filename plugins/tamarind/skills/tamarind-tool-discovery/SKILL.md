---
name: tamarind-tool-discovery
description: Choose which Tamarind Bio tool fits a scientific goal by querying the live CLI catalog and schema. Use when the user has not named a tool, when several tools could fit, or when availability and required inputs must be verified. Not for installing/authenticating the CLI or executing a tool that is already selected.
---

# Choose a Tamarind tool

Never recommend a tool from memory alone. The catalog is account-scoped and changes over time.

## Query the live catalog

Use the CLI's machine output; place `--json` before the command:

```bash
tamarind --json modalities
tamarind --json functions
tamarind --json tools --function structure-prediction
tamarind --json tools --modality antibody --function structure-prediction
tamarind --json tools --search boltz
tamarind --json schema boltz
```

If authentication is not verified, use `tamarind-api-setup`. Narrow `tools` by function and modality whenever possible; an unfiltered catalog is large.

## Select by fit

1. Identify the input the user already has: sequence, structure, receptor plus ligand, fixed backbone, labeled table, density map, or library.
2. Identify the required output: structure, pose, affinity, designed sequence, generated molecule, embedding, property score, or ranked candidates.
3. Query the matching live function and modality.
4. Read candidate descriptions and inspect the exact schema for the strongest fit.
5. Check upstream requirements. If the selected tool needs a structure or uploaded file the user does not have, include the upstream generation or upload step.
6. Recommend one primary tool and at most two conditional alternatives. Explain the condition that changes the choice; avoid unsupported "best" or "SOTA" claims.
7. Add downstream validation for every generative workflow.

When the user has named a tool, verify that it exists and that its schema accepts the available input. Mention a better-fit alternative only when the mismatch is material.

## Read the schema as authority

```bash
tamarind --json schema TOOL
```

Confirm required fields, types, conditionals, defaults, file inputs, and account-visible variants. Keep tuned defaults unless the user requests a change. Do not copy settings between sibling tools: similar tools often use different field names or enum values.

For a concrete payload, write YAML or JSON and perform a free server-side validation:

```bash
tamarind --json validate TOOL --input settings.yaml --name discovery-probe
```

`validate` does not submit or authorize a paid run. A file field can fail validation because the named file has not been uploaded; distinguish that from a malformed payload.

## Avoid waste

Compute trivial local properties locally when a standard library can answer them in seconds. Reserve Tamarind jobs for managed compute, model inference, durable artifacts, or workflow steps that need platform outputs.

## Route after selection

- Single job: use the matching domain skill plus `tamarind-submit-and-poll`.
- One tool over many inputs: use `tamarind-batch`.
- Multiple dependent tools: use `tamarind-pipeline`.

Read [references/selection_principles.md](references/selection_principles.md) for disambiguation examples and [references/tool_catalog.md](references/tool_catalog.md) for catalog field semantics.
