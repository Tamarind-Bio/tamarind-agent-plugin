---
name: tamarind-mcp-more-tools
description: Discover and run Tamarind Bio tools outside the dedicated MCP structure, binder, antibody, docking, inverse-folding, and developability skills. Use for enzymes, small-molecule properties or QM, molecular dynamics, nucleic acids, cryo-EM, structure search, and utilities. Not for a domain with a dedicated Tamarind MCP skill.
---

# Use the long-tail Tamarind MCP catalog

The catalog changes frequently. Start with `listModalities` and `listTags`, then call `getAvailableTools` with the narrowest relevant `modality`, `function`, or `search`. Inspect candidate schemas with `getJobSchema`.

## Select by domain

- Enzymes: distinguish function prediction, activity, stability, design, and substrate specificity.
- Small molecules: distinguish ADME/ADMET, property prediction, conformation, quantum chemistry, and generation.
- Molecular dynamics: confirm force field, solvent, atom count, simulation length, replicas, and whether the schema expects a prepared system.
- Nucleic acids: preserve RNA/DNA identity, modifications, complexes, and desired structure or design output.
- Cryo-EM: confirm map format, resolution, sequence/model inputs, fitting versus reconstruction, and output expectations.
- Search/utilities: avoid paid managed compute when a trivial local conversion or calculation is sufficient.

Recommend one primary tool and conditional alternatives only when the live catalog supports them. Identify upstream file/structure requirements and downstream validation.

## Validate and execute

Upload required files with `uploadFile`, call `validateJob`, reject mutation warnings, and call `estimateTime`. Surface the domain-specific parameters that affect scientific meaning and spend.

Use `tamarind-mcp-submit-and-poll` for one authorized run, `tamarind-mcp-batch` for one tool over independent inputs, and `tamarind-mcp-pipeline` for dependent stages. Some settings may fan out internally; inspect the returned row and expansion estimate instead of assuming one submission means one compute unit.
