---
name: tamarind-mcp-inverse-folding
description: Design sequences for a fixed protein backbone or run protein language models for embeddings, mutation scoring, likelihoods, and sequence generation with Tamarind Bio through MCP. Use for ProteinMPNN-, LigandMPNN-, ESM-IF-, or PLM-style tasks. Not for de novo backbone generation, antibody CDR design, or ordinary folding.
---

# Run inverse folding and protein language models

Separate two task families: inverse folding starts from a 3D backbone and produces sequences; protein language models start from sequence and produce embeddings, scores, likelihoods, or variants.

## Discover and validate

Call `listTags` when needed, then query `getAvailableTools` for inverse folding, protein language models, or embeddings. Inspect the chosen tool with `getJobSchema`.

For inverse folding, confirm designed chains/residues, fixed context, ligand context, sequence count, temperature/noise, excluded residues, and model variant. For PLMs, confirm task, model size, sequence limit, output format, and scan or generation settings.

Upload a backbone with `uploadFile` or pass an exact accepted upstream `s3Path`. Call `validateJob`, require no mutation warning, then call `estimateTime`. Surface model size, sequence count, temperature, batch size, and estimated spend.

## Execute and verify

Use `tamarind-mcp-submit-and-poll`. For multiple inputs or downstream folds, use `tamarind-mcp-batch` rather than looping over `submitJob`.

Inverse-folded sequences require structural validation. Refold a diverse bounded subset with `tamarind-mcp-structure-prediction`, then inspect backbone recovery and confidence/interface metrics. Pass designed sequences to the downstream schema's sequence field; do not place them in a template or structure-file field.
