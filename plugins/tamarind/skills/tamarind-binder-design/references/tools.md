# Binder design tools: full field maps, outputs, catalog

> Operational examples in this reference use the Tamarind CLI. Query the live catalog and schema before relying on this grounded snapshot.

Source of truth is `tamarind --json tools --function binder-design` plus `tamarind --json schema TOOL`. The catalog drifts; treat everything below as a grounded snapshot and re-query when a field stops validating. File-typed parameters (`pdbFile`, `targetFile`, `foldConditioningTargetFile`, ...) take the **bare filename** returned by `tamarind --json files upload PATH`, a prior-job output path (`JobName/...`), or inline structure text; they do NOT take an email-prefixed object key (see `tamarind-submit-and-poll` for the full file-parameter rule).

Every tool here is gated on a first required selector field (`task` / `mode` / `binderType`). Almost every other field is conditional on that selector, so read each param's `tasks` / `binderTypes` list in the schema before assuming a field applies.

---

## bindcraft (BindCraft)

End-to-end filtered minibinder design: ColabDesign hallucination, ProteinMPNN interface redesign, AF2 validation, looped until enough designs pass a filter set.

- `mode` (required selector): `default` | `peptide`.
- `pdbFile` (required, `.pdb`): target, trim under 750 residues (`maxTotalResidues: 750`, auto-trim flagged).
- `chains` (required): target chains to design against.
- `hotspotResidues` (`selectMultichainResidues`, ranges, e.g. `{"A": "56-58"}`): leave EMPTY to auto-select.
- `numDesigns` (default 1): keeps generating until this many PASS filters (~10 test, ~100 campaign).
- `binderLengthRange`: `70,150` (default) or `10,20` (peptide).
- `maxRunTime` (hours, default 16, up to 200; Free tier capped at 4): the job stops when this elapses if not enough passing designs are found. Primary "stopped early" lever.
- Tuning: `omitAAs`, `weightsHelicity` (-5..5, negative biases beta sheets), `predictBigBang` (large targets/designs > 600 aa), `trajectoryOnly` (step-1 hallucination only, fast but unoptimized), advanced toggles `betasheetAdvancedSettings` / `mpnnAdvancedSettings` (soluble MPNN) / `flexibleAdvancedSettings` / `hardtargetAdvancedSettings`.
- `filterType`: `default` | `relaxed` | `peptide` | `custom`. With `custom`, the individual thresholds become editable (`pLDDT`, `pTM`, `ipTM`, `i_pAE`, `Surface_Hydrophobicity`, `n_InterfaceResidues`, `n_InterfaceHbonds`, `Hotspot_RMSD`, `Binder_pLDDT`, `Binder_RMSD`); some only apply with `rosetta: true`.
- `rosetta` (default false): license-gated, contact Tamarind to enable.
- `customAdvancedSettingsFile` / `customFiltersFile` (`.json`): override the checkbox settings / filter dropdown entirely.

Output: `Accepted/` (and `Accepted/Ranked/`) folders of passing design `.pdb` complexes plus `final_design_stats.csv` (the per-design AF2 interface metrics used for ranking).

Note: "no passing designs" is a real outcome on hard targets. Adjust hotspots or relax `filterType` rather than rerunning unchanged.

---

## rfdiffusion (RFdiffusion)

The mature backbone generator; sequence is filled in downstream by ProteinMPNN. Gated heavily on `task`.

- `task` (required, default `Motif Scaffolding`): `Binder Design`, `Binder Redesign`, `Motif Scaffolding`, `Partial Diffusion`, `Fold Conditioning`, `Symmetric Oligomer`, `Symmetric Motif Scaffolding`, `Custom Contigs`.
- `pdbFile` (required for most tasks).
- **Binder Design**: `targetChains` (required), `binderLength` (required, `"20"` or `"20-30"`), `binderHotspots` (`selectMultichainResidues`, space-separated per chain, e.g. `{"A": "20 21 23"}`).
- **Binder Redesign**: `binderChain`, `designedResidues`, `hotspotChain` + `hotspots`, `designedLengths`.
- **Motif Scaffolding**: `interfaceChain`, `interfaceResidues` (comma-separated ranges, e.g. `"30-40, 60-70"`), `designedLengths` (one object entry per gap, one more than the number of contiguous interface ranges).
- **Partial Diffusion**: `designedChain`, `diffusedResidues`, `provideSeq`, `partial_T` (default 20).
- **Symmetric Oligomer / Symmetric Motif Scaffolding**: `symmetryType` (`c2..c6`, `d2..d4`, `tetrahedral`), `oligomerLength` (must be divisible by symmetry order), `motifResidues`, `scaffoldLengthBefore`/`scaffoldLengthAfter`, `useOligContacts`, `guideScale`, `guideDecay`.
- **Fold Conditioning**: `foldConditioningTargetFile`, `foldConditioningBinderFile` (both `.pdb`), optional `targetSSFile` / `targetAdjFile` (`.pt`).
- **Custom Contigs**: `contigs` (raw RFdiffusion notation, e.g. `"22-22/0 A1-150"`).
- Cross-task knobs: `numDesigns`, `verify` (default true: MPNN + AlphaFold scoring), `noiseScaleCa` / `noiseScaleFrame` (0-1, lower = more designable), `potentials` (comma-separated potential string), `model` (`default` | `Complex_beta_ckpt`).
- `verifySequences` is a website-only next-step field. Do not include it in CLI settings.

Output: per-design backbone `.pdb`; with `verify` on, a scores table with ProteinMPNN + AlphaFold metrics (pLDDT, pAE, etc.).

Separator gotchas: `binderHotspots` is SPACE-separated within a chain (not comma). `interfaceResidues` uses comma-separated ranges. `oligomerLength` divisibility (C4 -> 4, D2 -> 4, tetrahedral -> 12) is enforced.

---

## rfdiffusion3 (RFdiffusion3)

All-atom successor: conditions on a bound small molecule, nucleic acid, or enzyme active site at the atom level.

- `task` (required, default `protein-binder-design`): `protein-binder-design`, `enzyme-design`, `na-binder-design`, `small-molecule-binder-design`, `json`.
- `pdbFile` (required for all tasks except `json`): target structure (protein and/or ligand).
- `binderLength` (required, range, default `"100,150"`): min,max to sample. Auto-flipped if min >= max but give `"min,max"`.
- `targetChains` (protein/NA binder), `hotspots` (`selectMultichainResidues`, space-separated within a chain; protein-binder only).
- `ligands` (ligand-code list, for protein-binder/enzyme/small-molecule): which ligands from the PDB to target.
- `smBinderConditions` (object list, small-molecule-binder): per-ligand atom rows `{conditionType: Fixed|Buried|Exposed, residue: <ligand code>, selection: <comma atom list | ALL | empty>}`.
- Enzyme knobs: `scaffoldingMode` (`Atom-level` vs `Residue-level`), `fixAtoms` + `fixAtomsSelection` (atom-level), `interfaceChain` + `interfaceResidues` + `designedLengths` (residue-level), `unindex`, `classifierFreeGuidance` (2x cost, strict motif adherence).
- `json` task: `jsonInputType` (`file` | `string`), then `jsonFile` or `jsonConfig` (Foundry RFD3 config), plus `inputFiles` (`.pdb`/`.cif` referenced by the config, matched by filename).
- Global knobs: `numDesigns` (default 1), `nonLoopy` (default true, structured designs, protein-binder only), `stepScale` (default 1.5, lower = more diversity / less helical bias), `gammaZero` (default 0.6, lower = more designable, less diverse), `oriToken` (na-binder only).

Output: per-design `.pdb`/`.cif` backbone-plus-sequence structures plus a scores table assembled from the job row.

Gotcha: the `json` raw-config task is by far the highest-volume failure path; the server validates residue indices and ligand-code references and tolerates trailing commas, but the Foundry input format must be followed exactly (`github.com/RosettaCommons/foundry`). Prefer the guided tasks.

---

## boltzgen (BoltzGen)

One model across nanobodies, antibodies, proteins, peptides, cyclotides, and small-molecule binders, with Boltz-2 refolding and ipSAE/diversity filtering bundled. Gated on `binderType`.

- `binderType` (required selector): `de-novo-nanobody` (default), `de-novo-antibody`, `protein`, `small-molecule-binder`, `peptide`, `cyclotide`, `protein-redesign`, `custom`, `yaml`.
- `targetFile` (required `.pdb`) + `targetChains` for the structure-target types.
- `scaffold` (required, `default` | `custom`) for `de-novo-nanobody` / `de-novo-antibody` / `protein`; for `custom` a large conditional tree (`frameworkInputType`, `frameworkSequence`/`frameworkFile`, `cdrRegions`, `cdrExcludeCounts`, `cdrInsertionLengths`, heavy/light variants for antibody).
- `bindingSite` / `notBindingSite` (`selectMultichainResidues`): residues to steer toward / away from.
- `protein-redesign`: `designRegions` (required).
- Small-molecule-binder: `targetLigandFormat` (`smiles` | `ccd` | `file`), then `targetSmiles` / `targetCcd` / `targetLigandFile` + `targetLigandChains`; plus `smbScaffold` and `smbLengthRange`.
- Peptide / cyclotide: `lengthRange` or `peptideSequence` spec, `cyclic`, `disulfideBonds` / `peptideDisulfideBonds`, `cyclotideSequence` (Cys-positional), optional `peptideScaffold`.
- `yaml` task: `yamlFile` + `protocol` (e.g. `nanobody-anything`, `antibody-anything`, `protein-anything`, `protein-small_molecule`, `peptide-anything`, `protein-redesign`) + `structureFile`/`structureFiles`.
- `custom` task: `entities` (required object list) + optional `constraints`.
- Global knobs: `numDesigns` (default 10; recommend a large number for a production campaign), `diffusionBatchSize`, `budget` (default 2; final count optimized for diversity/quality), `omitAAs` (default C for peptide/nanobody), `runIpsae` (default true) + `pae_cutoff` / `dist_cutoff`, `filterBindingSite`, `skipRefolding` (default false).

Output: `final_ranked_designs/` with ranked design `.pdb`/`.cif`, `final_ranked_designs/all_designs_metrics.csv` (the canonical metrics table), a `final_{budget}_designs/` subfolder, and `results_overview.pdf`. With `runIpsae` on, per-complex ipSAE / pDockQ are merged in.

Gotchas: `skipRefolding: true` skips the slow Boltz-2 refold and ranks the ORIGINAL generated structures, so the same structure can appear in both `final_*_designs/` and a `before_refolding/` mirror; a passing metrics CSV does NOT guarantee distinct refolded outputs, so pull an actual PDB and check coords. Targets with gaps or insertion codes in their residue numbering raise a clear input error; clean the numbering first.

---

## Output shapes (reason about the shape, not golden numbers)

Binder outputs are non-deterministic (seed / model / MSA), so read the metric keys and reason about ranking, not exact values.

- **Job row `Score`** (JSON on completed jobs): interface metrics for the design family (pLDDT/pTM for the monomer fold; ipTM, ipSAE, pDockQ for the interface). Higher pLDDT/pTM/ipTM/ipSAE/pDockQ is more confident.
- **Results bundle:** the per-design structures plus the tool's metrics CSV and logs. Download it with `tamarind --no-json results JOB_NAME --download DIRECTORY` and inspect the extracted filenames; do not hardcode names, which vary by tool and version.
- **`WeightedHours`** on the row is the billing unit (weighted hours, GPU tools cost more per wall-hour than CPU tools).

Use the absolute helper path documented in the parent skill, `python3 "$SKILL_DIR/scripts/summarize_binder_metrics.py" <results-dir>`, to rank designs by the auto-detected interface metric and report the max / 10th-best / fraction-above-cutoff. Resolve `SKILL_DIR` to the directory containing the parent `SKILL.md`.

---

## Catalog: every other binder generator (one line each)

Reach for one of these when a workflow specifically names it; run `tamarind --json schema TOOL` first because these drift.

- **`mosaic-hallucinate`** (Mosaic Hallucination): SOTA gradient-based single-shot de novo protein/peptide binder design; optimizes a sequence directly on a composite Boltz-2 (ipTM/PAE/contacts) + ProteinMPNN loss, replacing the separate backbone-generate / inverse-fold / filter stages. A strong de novo alternative against a target sequence or structure.
- **`idr`** (IDR Binder Design): de novo protein binders against an INTRINSICALLY DISORDERED target (IDR/IDP) from the target SEQUENCE alone, no folded structure needed (RFdiffusion + ProteinMPNN + AlphaFold2 initial-guess); complement to `bindcraft`'s folded-target scope.
- **`rfdiffusion-all-atom`**: RFdiffusion variant that diffuses all atoms (ligand/cofactor aware); RFdiffusion-lineage option for small-molecule or cofactor-conditioned scaffolding.
- **`rfdiffusion2`**: SOTA for atom-level ENZYME active-site scaffolding (scaffolds an atomic catalytic motif, ORI token controls active-site placement); enzyme design lives in `tamarind-more-tools`. Not for binders, prefer `rfdiffusion3`.
- **`boltzdesign`** (BoltzDesign1): inverts Boltz-1 to design binders across proteins, antibodies, peptides, enzymes, and small-molecule-binding proteins.
- **`pxdesign`** (PXDesign): de novo protein binder design using diffusion models.
- **`protein-hunter`** (Protein Hunter): broad de novo protein design / binder discovery.
- **`rso`** (RSO Binder Design): efficient binder design; a faster/cheaper pass than the heavier diffusion pipelines.
- **`esmfold2-binder-design`**: de novo protein binders using ESMFold2 (MSA-free, ESM-based).
- **`evopro`** (EvoPro): genetic-algorithm binder OPTIMIZATION; affinity-mature an EXISTING binder rather than design from scratch.
- **`germinal`** (Germinal): epitope-targeted de novo ANTIBODY / nanobody design (ColabDesign hallucination, AbMPNN CDR redesign, cofold filtering); for antibodies prefer `tamarind-antibody`.
- **`riffdiff`** (RiffDiff): a complete de novo ENZYME design pipeline from a theozyme (scaffolds the catalytic motif into a backbone with RFdiffusion, then refines); primarily an enzyme tool (see `tamarind-more-tools`).
- **`disco`** (DISCO): SOTA ligand-, DNA-, or RNA-conditioned sequence+structure co-design with no template or theozyme; the no-template option for small-molecule or nucleic-acid-binder and de novo enzyme co-design (primary home is the enzyme tooling in `tamarind-more-tools`).

For the peptide and macrocycle family (rfpeptides, afcycdesign, pepmlm, pepmimic, cyclicmpnn), see [peptide_macrocycle.md](peptide_macrocycle.md).
