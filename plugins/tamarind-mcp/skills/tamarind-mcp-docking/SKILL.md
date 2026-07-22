---
name: tamarind-mcp-docking
description: Dock or screen known ligands against a receptor, perform protein-protein docking, or score existing poses and complexes with Tamarind Bio through MCP. Use for pocket-based or blind docking and pose ranking. Not for sequence co-folding, generating a new ligand or binder, or general structure prediction.
---

# Dock and score through MCP

Start from the input the user actually has: receptor structure, ligand or SMILES/library, known pocket box, or an existing complex.

## Select the method

Call `listTags` when needed, then query `getAvailableTools` for protein-ligand docking, protein-protein docking, or binding affinity. Inspect the exact candidate with `getJobSchema`.

- Prefer box-based physics docking when pocket coordinates are known.
- Prefer blind methods only when the live schema supports the available inputs.
- Prefer score-only tools for a pose or complex that already exists.
- Fold sequence-only inputs before sending them to structure-only docking fields.

Closely related tools use different receptor, ligand, box, exhaustiveness, and scoring fields. Never transfer a sibling payload without schema inspection.

## Prepare and run

Upload receptor or ligand files with `uploadFile`, or use exact accepted `s3Path` values from successful upstream jobs. Keep receptor and ligand separate when required.

Call `validateJob` and `estimateTime`. Confirm blind versus box docking, pocket definition, ligand count, pose count, exhaustiveness or sampling, rescoring, and estimated spend. Route a library to `tamarind-mcp-batch` or a schema-supported file batch instead of looping `submitJob`.

Use `tamarind-mcp-submit-and-poll`. Retrieve poses and score tables by calling `listJobFiles` before targeted `getJobFile` calls.

Report whether lower energy/affinity or higher model confidence is better. Check pose geometry and interactions; docking scores prioritize candidates but do not prove experimental binding.
