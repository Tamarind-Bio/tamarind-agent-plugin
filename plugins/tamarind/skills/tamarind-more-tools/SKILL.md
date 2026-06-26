---
name: tamarind-more-tools
description: "Use for Tamarind Bio domains without a dedicated skill: enzyme design and kinetics, small-molecule property / ADMET / quantum chemistry, molecular dynamics and free energy, nucleic-acid (RNA/DNA) design and language models, cryo-EM model building, and homology / structure search plus format utilities. Discover the right tool live with getAvailableTools(function=...) / listModalities() / listTags(), then read its getJobSchema before submitting. Not for protein/complex structure prediction, binder or antibody design, inverse folding, developability, or docking (those have their own skills); for the submit/poll/download mechanics use tamarind-submit-and-poll."
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: more tools (the long tail)

Tamarind runs hundreds of tools. The high-demand domains (structure prediction, binder and antibody design, inverse folding, developability, docking) each have their own skill. This skill is the catalog for everything else: enzyme work, small-molecule properties / ADMET / QM, molecular dynamics and free energy, nucleic-acid design and language models, cryo-EM model building, and search + format utilities.

These domains are lower-volume and the catalog drifts, so this skill does **not** dump full schemas. It points you at **live discovery** plus a few anchor tools per domain so you have a starting handle. The pattern is always the same: filter the catalog by `function`, read a candidate's `getJobSchema`, then run it with **`tamarind-submit-and-poll`** (validate, submit, poll to terminal, download). For many inputs of one tool use `tamarind-batch`.

## Discover live, then confirm the schema

Do not hardcode tool names or params; both drift. Find the tool, then read its exact schema:

```
listModalities()                 # molecule types: protein, small-molecule, nucleic-acid, enzyme, cryoem, ...
listTags()                       # functions: enzyme-design, molecular-dynamics, structure-search, ...
getAvailableTools(function="molecular-dynamics")   # the live tool list for a domain
getJobSchema(jobType="openmm")   # exact params + required fields + an exampleJob
```

Over plain REST (no MCP), `GET /tools` returns the full list with each tool's inline `settings`; filter client-side. The `function` values that map to this skill's domains:

| Domain | Discover with | Reference |
|---|---|---|
| Enzyme design + kinetics + function | `getAvailableTools(function="enzyme-design")` (design); `modality="enzyme"` | [references/enzyme.md](references/enzyme.md) |
| Small-molecule property / ADMET / QM | `getAvailableTools(function="small-molecule-property-prediction")`; `modality="small-molecule"` | [references/small_molecule.md](references/small_molecule.md) |
| Molecular dynamics + free energy | `getAvailableTools(function="molecular-dynamics")` (and `binding-affinity`) | [references/md.md](references/md.md) |
| Nucleic-acid design + language models | `getAvailableTools(modality="nucleic-acid")`; `function="rna-design"` / `"rna-language-models"` / `"codon-optimization"` | [references/nucleic_acid.md](references/nucleic_acid.md) |
| Cryo-EM model building | `getAvailableTools(modality="cryoem")` | [references/cryoem.md](references/cryoem.md) |
| Search + format utilities | `getAvailableTools(function="structure-search")` / `function="utilities"` | [references/search_and_utilities.md](references/search_and_utilities.md) |

Match the user's **intent** (input you have, output you need), not a tool name. When a candidate looks right, `getJobSchema` / `validateJob` it before committing; it is the authority on required fields.

## Anchor tools per domain (a starting handle, not the full list)

- **Enzyme** ([references/enzyme.md](references/enzyme.md)): `enzygen2` (motif-conditioned enzyme co-design), `disco` (SOTA ligand- / DNA- / RNA-conditioned de novo co-design, no theozyme), `catpred` (kcat / Km / Ki kinetics), `deepfri` (GO + EC function prediction).
- **Small-molecule property / ADMET / QM** ([references/small_molecule.md](references/small_molecule.md)): `admet` (broad ADMET over a list of SMILES), `logp` / `pka` (single physicochemical properties), `conformer-generation` (3D ensembles), the shared `qchem` CPU suite (energies, geometry, spectra), `reinvent-finetune` / `enumeration` (library generation).
- **Molecular dynamics + free energy** ([references/md.md](references/md.md)): `gromacs` / `openmm` (classical MD), `openfe` / `rbfe` (relative binding free energy), `gbsa` (endpoint MM/GBSA affinity).
- **Nucleic-acid** ([references/nucleic_acid.md](references/nucleic_acid.md)): `evo2` (genome DNA language model), `rna-fm` (RNA embeddings + secondary structure), `ribodiffusion` (RNA inverse folding), the codon-optimization set (`derna` / `vaxpress` / `syn-codon-lm`).
- **Cryo-EM** ([references/cryoem.md](references/cryoem.md)): `modelangelo` / `cryfold` (map-to-model building), `cryoboltz` (map-guided structure prediction).
- **Search + utilities** ([references/search_and_utilities.md](references/search_and_utilities.md)): `foldseek` (structure search), `blast` / `psiblast` (sequence search), `foldmason` (multi-structure alignment); `file-converter`, `pulchra`, `alphacutter`, `ipc` (format + misc).

## Patterns that hold across these domains

- **File inputs take a BARE filename.** A param like `pdbFile` / `sdfFile` / `map` references a file you uploaded first (`uploadFile` returns the bare name); pass just that name, e.g. `"pdbFile": "receptor.pdb"`. Do **not** email-prefix it and do **not** pass an S3 key: a plain string in a file field is treated as inline content, and an email-prefixed key 400s as "not uploaded". `validateJob` actually checks file existence, so a not-yet-uploaded filename returns `valid:false` (the rest of the settings still resolved). Full mechanics: `tamarind-submit-and-poll`.
- **Many of these tools use a task selector.** A `task` / `inputType` / `systemType` field gates which other params apply (e.g. `deepfri` `task: sequence|PDB`, the qchem tools `inputType: smiles|sdf`, MD `systemType: protein|protein-ligand`). Set the selector first; sibling fields for the other mode are silently ignored.
- **SMILES / sequence inputs are batchable.** Text inputs (a SMILES, a DNA/RNA/protein sequence) chain and batch cleanly. To score many molecules or sequences against one tool, use `tamarind-batch`. The exception is `admet`, which takes a LIST of SMILES in one job, so you do not batch it.
- **CPU vs GPU cost.** The qchem property suite and most search/format utilities are CPU tools (fast, cheap in weighted hours). MD, free energy, the genome / RNA language models, and the cryo-EM builders are GPU and longer-running; surface the runtime-driving knobs (simulation length, number of edges/repeats, model size) before submitting.

## Reference files

One file per domain, each pointing at live discovery plus the anchor tools and the domain-specific gotchas:

- [references/enzyme.md](references/enzyme.md): enzyme design, kinetics, and function prediction.
- [references/small_molecule.md](references/small_molecule.md): ADMET, physicochemical properties, the qchem QM suite, conformers, library generation.
- [references/md.md](references/md.md): classical MD, membrane MD, enhanced sampling, RBFE and endpoint free energy (incl. the openmm string-typed-numeric and RBFE-congeneric-ligand gotchas).
- [references/nucleic_acid.md](references/nucleic_acid.md): RNA/DNA design, language models, codon optimization.
- [references/cryoem.md](references/cryoem.md): cryo-EM map-to-model building and map-guided prediction.
- [references/search_and_utilities.md](references/search_and_utilities.md): homology / structure search, structural alignment, and format / misc utilities.
