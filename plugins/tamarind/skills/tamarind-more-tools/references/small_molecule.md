# Small-molecule property / ADMET / quantum chemistry

Compute properties of a single small molecule from its 2D/3D structure: drug-likeness / ADMET, physicochemical descriptors (logP, pKa, solubility), quantum chemistry (energies, geometries, electronic structure, spectra), conformer ensembles, and library generation / search. Mostly fast CPU predictors keyed off a SMILES string or an SDF file. NOT docking or simulation (use the docking skill or [references/md.md](md.md)).

Discover live, then read the schema:

```
getAvailableTools(function="small-molecule-property-prediction")
getAvailableTools(modality="small-molecule")
getJobSchema(jobType="logp")            # exact params + conditionals before you submit
```

Most of the QM / property tools (`logp`, `pka`, `conformer-generation`, and the rest of the qchem suite) share ONE CPU Docker image and the same SMILES-or-SDF input shape, so once you know one, the others follow the same pattern. Each typically has a `task` / `inputType` selector picking `smiles` (text) vs `sdf` (file, bare filename, uploaded first).

## Anchor tools

### admet (ADMET)
Broad first-pass profile across many ADMET / physicochemical endpoints (permeability, clearance, tox flags, drug-likeness) over a LIST of candidates in one job.
- Required: `smilesStrings` (a LIST of SMILES). This is the only param.
- It is the rare property tool you do NOT batch: pass all molecules in `smilesStrings`. No upstream SMILES validation, so pre-canonicalize with RDKit if input provenance is uncertain.
- For lipophilicity / permeability / solubility specifically, use the open path: `admet` + `logp` + `aqueous-solubility`.

### logp (LogP) and pka (Macroscopic pKa)
Single physicochemical properties with method control.
- `logp`: `inputType` (`smiles`/`sdf`), then `smiles` or `sdfFile`; `method` (`crippen` instant atom-contribution, or `xtb` physics-based ~30s); `charge` (only respected when `method=xtb`).
- `pka`: `inputType`, then `smiles`/`sdfFile`; `method` (`xtb-gfn2`); `charge` is the charge of the MOST PROTONATED state (set it correctly for already-charged inputs); `ionizableSites` uses 0-based RDKit atom INDICES (auto-detect by leaving empty).
- Conditional fields are silent no-ops when their condition is unmet, so `validateJob` before submitting.

### conformer-generation (Conformer Generation)
Generate, cluster, and energy-rank a 3D conformer ensemble to feed docking, shape comparison, QM, or pharmacophore work.
- `inputType`, then `smiles`/`sdfFile`; `generationMethod` (`rdkit` ~10s, or `crest` GFN2 metadynamics ~10min, ~60x slower); `forceField` (ignored for crest); `numConformers`; `clustering`; `energyScreening` (`mmff` < `xtb-gfn2` < `g-xtb` < `r2scan-3c`, increasing cost); `solvent` (only used when energy screening is on); `pruneSimilar` / `pruneThreshold`.
- Start with `rdkit` + `xtb-gfn2`; reserve `crest` for genuinely flexible molecules.
- Siblings: `openconf` (preset workflows), `loqi` (QM-accuracy low-energy conformers), `geometry-optimization` (relax ONE geometry, not an ensemble).

### The qchem suite (shared CPU image)
One image, the SMILES-or-SDF input shape, fast and cheap. Discover the current set with `getAvailableTools(function="small-molecule-property-prediction")` and `getJobSchema(<tool>)` for each tool's method-specific knobs.

### reinvent-finetune / enumeration (library generation)
- `enumeration` (R-Group Enumeration): build a combinatorial library from a `[*:1]/[*:2]`-marked scaffold SMILES plus an R-group CSV, with optional Lipinski / MW / logP / TPSA filters and diversity selection.
- `reinvent-finetune` (REINVENT4): RL-driven generative design and finetuning (de novo, optimization, scaffold/linker/peptide design) with configurable scoring + diversity filters; finetune a generative prior on your own SMILES (CSV with `smilesCol`). The only small-molecule generative finetuner; see `tamarind-finetune`.

## Catalog (one-liners)

Reach for `getJobSchema(<tool>)` for exact knobs; most share the qchem image.

- Physicochemical / solubility: `aqueous-solubility` (logS, optional xTB solvation), `fastsolv` (solubility in a named solvent), `molecular-descriptors` (200+ RDKit descriptors + fingerprints).
- Acid/base and protonation: `microscopic-pka` (per-group), `qupkake` (fast ML pKa, optional tautomerize), `protonation-state` (dominant species at a pH), `tautomer` (enumerate + rank tautomers). Note `propka` is for ionizable RESIDUES in a PROTEIN, not a small molecule.
- Descriptors and charges: `charge-dipole` (partial charges + dipole).
- Electronic structure / reactivity (QM): `electrostatic-potential`, `electronic-properties` (HOMO/LUMO + Fukui + reactivity), `fukui`, `hbond-strength`, `bde` (bond dissociation energies / metabolic soft spots), `redox`, `reaction-energy`, `spin-state-energies`.
- Energies, geometry, spectra (QM): `single-point-energy` (fixed geometry), `frequency-analysis` (vibrational / IR / thermochemistry), `td-dft` (UV-Vis). Note `geometry-optimization` is FORCE-FIELD ligand cleanup (relax one conformer to a local minimum before docking / QM), NOT a QM geometry optimization.
- Conformers (additional): `openconf`, `search-conformations`, `loqi`.
- Library / database: `libinvent` (generative scaffold decoration), `chembl` / `pubchem` (similar-molecule search of a public DB).

Note: `orb-models3` (protein-ligand interaction energy) and `tmd` (RBFE engine) appear under this modality by category overlap but are binding / MD tools; route them to [references/md.md](md.md) or the docking skill.

Note: for SMILES-defined cyclic / non-canonical therapeutic PEPTIDES, developability (permeability, serum half-life, hemolysis, solubility, target binding) is `peptiverse`; it lives in the developability skill but accepts a SMILES path, so reach for it from here when the molecule is a peptide rather than a small molecule.

For execution mechanics, see `tamarind-submit-and-poll`; for many molecules against one tool, `tamarind-batch` (except `admet`, which fans out internally).
