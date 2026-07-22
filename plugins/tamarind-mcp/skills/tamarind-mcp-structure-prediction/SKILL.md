---
name: tamarind-mcp-structure-prediction
description: Predict or co-fold proteins, peptides, nucleic acids, ligands, or biomolecular complexes with Tamarind Bio through MCP. Use for live AlphaFold-, Boltz-, Chai-, ESMFold-, or Protenix-style structure workflows when MCP is requested. Not for de novo binder generation, antibody-specific modeling, or docking into a known pocket.
---

# Predict biomolecular structures through MCP

Use the live catalog and schema; model availability and settings change.

## Choose the model family

Call `getAvailableTools(function="structure-prediction")`, then inspect candidates with `getJobSchema`.

- Prefer a live co-folding model for multi-chain, ligand, or nucleic-acid complexes when its schema supports every component.
- Prefer a fast single-sequence model when one protein fold and low latency are sufficient.
- Route Fv, VHH, or TCR-specific work to `tamarind-mcp-antibody`.
- Route known-receptor pocket or pose work to `tamarind-mcp-docking`.

Do not copy payloads between model families.

## Build and validate

Represent every molecule in the exact field and format required by the live schema. Upload file inputs with `uploadFile` and use the returned bare filename, or use an exact prior-job `s3Path` accepted by the schema.

Call `validateJob`. Require `valid: true` with no `mutatedFields`. Validation does not identify molecule type: confirm that DNA/RNA is routed to nucleotide inputs rather than a protein sequence field.

Call `estimateTime`, then surface consequential settings such as sample/model count, MSA, recycles, model/version, templates or restraints, affinity calculation, and output format. Keep tuned defaults unless the user intentionally changes them. A production canary should minimize input size and independent samples without forcing quality parameters to unsafe minima.

## Execute and interpret

Use `tamarind-mcp-submit-and-poll` for authorization, one submission, bounded status polling, and targeted output retrieval.

Report local confidence, global fold confidence, and interface confidence separately. High pLDDT alone does not prove a correct complex interface; inspect pTM, ipTM, ipSAE, pDockQ, or model-specific fields when present. Treat confidence as model evidence, not experimental validation, and require geometry inspection before recommending a structure.
