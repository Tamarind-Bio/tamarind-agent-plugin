---
name: tamarind-more-tools
description: Discover and run Tamarind Bio tools outside the dedicated protein-folding, binder, antibody, docking, inverse-folding, and developability skills. Use for enzyme work, small-molecule properties/QM, molecular dynamics, nucleic acids, cryo-EM, structure search, and format utilities. Not for a domain that already has a dedicated Tamarind skill.
---

# Use Tamarind's long-tail tool catalog

The catalog is large and changes frequently. Always query live:

```bash
tamarind --json functions
tamarind --json modalities
tamarind --json tools --function FUNCTION
tamarind --json tools --modality MODALITY --function FUNCTION
tamarind --json schema TOOL
```

Match the available input and desired output, identify upstream dependencies, and choose one primary tool plus conditional alternatives. Do not submit a managed job for a trivial local calculation.

## Domain references

Load only the relevant file:

- Enzymes: [references/enzyme.md](references/enzyme.md)
- Small molecules, ADMET, and quantum chemistry: [references/small_molecule.md](references/small_molecule.md)
- Molecular dynamics and free energy: [references/md.md](references/md.md)
- RNA/DNA and nucleic-acid models: [references/nucleic_acid.md](references/nucleic_acid.md)
- Cryo-EM: [references/cryoem.md](references/cryoem.md)
- Search and utilities: [references/search_and_utilities.md](references/search_and_utilities.md)

Treat any named tools or settings in references as orientation; confirm them with the live CLI schema.

## Validate and execute

Write `settings.yaml`, upload required files with `tamarind --json files upload PATH`, and validate:

```bash
tamarind --json validate TOOL --input settings.yaml --name JOB_NAME
```

Surface consequential scientific and cost choices, then follow `tamarind-submit-and-poll` for a single authorized run. Some long-tail tools fan out internally from one submission (for example multi-sequence inputs or multiple RNA designs), so always run that skill's post-submit status probe, use a bounded wait for an active `JobStatus` or `batchStatus`, and interpret the matching terminal field; do not assume one `submit` means one single-job row. Use `tamarind-batch` for one tool over many independent inputs and `tamarind-pipeline` for dependent stages.
