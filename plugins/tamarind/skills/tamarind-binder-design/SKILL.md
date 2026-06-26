---
name: tamarind-binder-design
description: Use when designing a NEW de novo protein, peptide, or small-molecule binder against a target on Tamarind Bio (generate backbones plus sequences from scratch, then refold and score). Covers BindCraft, RFdiffusion, RFdiffusion3, BoltzGen, and the peptide/macrocycle family (RFpeptides, AfCycDesign, PepMLM). Not for antibodies or nanobodies (use tamarind-antibody), not for redesigning the sequence of an EXISTING backbone (use tamarind-inverse-folding), not for predicting an existing structure (use tamarind-structure-prediction), not for docking a known ligand into a pocket (use tamarind-docking).
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: de novo binder design

Design a brand-new binder for a target: generate backbones and sequences from scratch, then refold and score the interface. The target can be a protein, a nucleic acid, a small molecule, or an enzyme active site. Output is a ranked set of candidate designs (structures plus interface metrics), not a single answer, so the job is to generate enough, then filter and rank.

This skill builds on the base job lifecycle in `tamarind-submit-and-poll` (validate, submit, poll to terminal, download). It assumes you know how to run one job; here it adds **which binder tool fits which target**, the **per-tool required fields**, and the **read-back-and-rank** step. For first-time key setup use `tamarind-api-setup`; for many targets or a large design sweep use `tamarind-batch`.

Scope boundaries worth stating up front: antibody and nanobody binders have their own machinery (CDR numbering, framework scaffolds) and live in `tamarind-antibody`. Redesigning the sequence of a backbone you already have is inverse folding (`tamarind-inverse-folding`). Predicting the structure of a sequence you already have is `tamarind-structure-prediction`.

## Pick the binder tool by what the TARGET is

Filter live first (`getAvailableTools(function="binder-design")` or `GET /tools`), read each candidate's `description`, and match it to the target you actually have. The catalog drifts, so confirm with `getJobSchema` before committing. As a starting orientation:

- **A single PROTEIN target, you want filtered hits with minimal setup** -> **`bindcraft`**. It hallucinates a binder, redesigns the interface with ProteinMPNN, validates with AlphaFold2, and returns only designs that pass a filter set. Auto-selects hotspots if you leave them blank. The lowest-friction default.
- **A protein target, you want the most TASK VARIETY or raw backbone control** -> **`rfdiffusion`** (binder design, motif scaffolding, symmetry, partial diffusion, custom contigs). The mature, heavily-cited backbone generator; sequence is filled in downstream by ProteinMPNN, optionally auto-scored with the `verify` toggle.
- **A SMALL-MOLECULE, NUCLEIC-ACID, or ENZYME active-site target** -> **`rfdiffusion3`**, the all-atom successor. It conditions on a bound ligand, DNA/RNA, or a theozyme at the atom level (the `small-molecule-binder-design`, `na-binder-design`, `enzyme-design` tasks). This atom-level conditioning is what the original `rfdiffusion` cannot do.
- **You want built-in Boltz-2 refold plus ipSAE interface scoring in ONE job, across modalities** -> **`boltzgen`**. One model spans nanobodies, antibodies, proteins, peptides, cyclotides, and small-molecule binders, with refolding and diversity-aware budget selection bundled. (For antibody/nanobody binders specifically, also weigh `tamarind-antibody`; BoltzGen's nanobody/antibody modes are covered here for completeness.)
- **A PEPTIDE or MACROCYCLE binder** -> see the [peptide and macrocycle binders](#peptide-and-macrocycle-binders) section below (`rfpeptides`, `afcycdesign`, `pepmlm`, and friends).

There are many more binder tools than these four; the catalog section near the end names them so you can reach for one when a workflow calls for it. When the user names a specific tool, evaluate it and sanity-check a sibling in the same `function` group, then let `validateJob` confirm the input you have actually fits.

## The four canonical tools (required fields, gotchas, validated payloads)

Every binder tool is gated on a **task / type selector** (the first required field), and almost every other field is conditional on it. Fetch `getJobSchema(<tool>)` and read the `tasks` / `binderTypes` on each param; do not assume a field from one mode applies to another. File-typed params (`pdbFile`, `targetFile`) take the **bare filename** of an uploaded file, NOT an email-prefixed S3 key (see `tamarind-submit-and-poll` for the file-param rule).

### bindcraft

- Selector: `mode` (`default` or `peptide`).
- Required: `pdbFile` (target structure, trim under 750 residues), `chains` (target chains to design against).
- Key knobs: `hotspotResidues` (per-chain ranges, e.g. `{"A": "56-58"}`; **leave empty to auto-select**), `numDesigns` (it keeps generating until this many PASS filters, ~10 to test, ~100 for a campaign), `binderLengthRange` (`70,150` default mode / `10,20` peptide), `maxRunTime` (hours, default 16, the primary "why did it stop early" lever; Free tier capped at 4), `filterType` (`default` / `relaxed` / `peptide` / `custom`).
- Gotcha: **"no passing designs" is a real, common outcome on hard targets.** BindCraft runs until `maxRunTime`, then stops with whatever passed (possibly zero). The fix is usually adjusting hotspots or relaxing `filterType`, not rerunning unchanged.
- Validated payload:
  ```json
  {"mode": "default", "pdbFile": "target.pdb", "chains": ["A"],
   "hotspotResidues": {"A": "56-58"}, "numDesigns": 10, "binderLengthRange": "70,120"}
  ```

### rfdiffusion

- Selector: `task` (default `Motif Scaffolding`; for a binder use `Binder Design`).
- Binder Design required: `pdbFile`, `targetChains`, `binderLength` (single `"20"` or range `"20-30"`).
- Key knobs: `binderHotspots` (per-chain, **space-separated** within a chain, e.g. `{"A": "20 21 23"}`, NOT comma), `numDesigns`, `verify` (default true: pipe designs through ProteinMPNN + AlphaFold for scores), `potentials` (comma-separated potential string).
- Gotchas: hotspot separator is a SPACE inside a chain string, not a comma. For `Symmetric Oligomer`, `oligomerLength` must be divisible by the symmetry order (C4 -> 4, D2 -> 4, tetrahedral -> 12) or it rejects. `verifySequences` is in the schema but tagged `exclude: [api, ...]`; do NOT pass it over the API.
- Validated payload (Binder Design):
  ```json
  {"task": "Binder Design", "pdbFile": "target.pdb", "targetChains": ["A"],
   "binderLength": "60-100", "binderHotspots": {"A": "45 47 52"}, "numDesigns": 8, "verify": true}
  ```

### rfdiffusion3

- Selector: `task` (default `protein-binder-design`; the all-atom tasks are `small-molecule-binder-design`, `na-binder-design`, `enzyme-design`; power users use `json`).
- Required across design tasks: `pdbFile` (target structure including any ligand), `binderLength` (range `"min,max"`, default `"100,150"`).
- Per-task: `targetChains` (protein/NA binder) + `hotspots` (protein binder only; **space-separated** within a chain), `ligands` (which ligand codes from the PDB to target, for small-molecule/enzyme), `smBinderConditions` (per-ligand atom conditioning rows for small-molecule design), enzyme knobs (`scaffoldingMode`, `fixAtoms`/`fixAtomsSelection`, `interfaceChain`/`interfaceResidues`/`designedLengths`, `classifierFreeGuidance` at 2x cost).
- Gotchas: the `json` raw-config task is the highest-volume failure path (follow the Foundry input format exactly); prefer the guided tasks. `binderLength` is auto-flipped if min >= max but give it `"min,max"`. Global knobs `numDesigns`, `nonLoopy` (default true, structured designs), `stepScale` (default 1.5, lower for more diversity), `gammaZero` (default 0.6, lower for more designable).
- Validated payload (protein binder):
  ```json
  {"task": "protein-binder-design", "pdbFile": "target.pdb", "targetChains": ["A"],
   "binderLength": "80,120", "hotspots": {"A": "45 47 52"}, "numDesigns": 4}
  ```

### boltzgen

- Selector: `binderType` (`de-novo-nanobody` default, `de-novo-antibody`, `protein`, `small-molecule-binder`, `peptide`, `cyclotide`, `protein-redesign`, `custom`, `yaml`).
- Required for structure-target types: `targetFile` (target structure), plus `numDesigns` and (for the de-novo-nanobody/antibody/protein types) `scaffold` (`default` or `custom`). `targetChains` is optional but usually set.
- Key knobs: `bindingSite` / `notBindingSite` (residues to steer toward/away), `budget` (final count optimized for diversity/quality), `runIpsae` (default true: per-complex ipSAE/pDockQ), `skipRefolding` (default false), `omitAAs` (default C for peptide/nanobody). The `small-molecule-binder` type uses `targetLigandFormat` + `targetSmiles`/`targetCcd`/`targetLigandFile`; peptide/cyclotide use `lengthRange`/`peptideSequence`/`cyclotideSequence` plus disulfide fields.
- Gotchas: `numDesigns` defaults to 10; authors recommend a much larger number for a real campaign. **`skipRefolding: true` skips the slow Boltz-2 refold** and ranks the ORIGINAL generated structures, so the same structure can appear in both `final_*_designs/` and a `before_refolding/` mirror. When verifying a skipRefolding job, pull an actual PDB and check the coords, do not trust the metrics CSV alone. Targets with gaps or insertion codes in their residue numbering are a recurring failure source (raises a clear input error).
- Validated payload (nanobody-against-protein):
  ```json
  {"binderType": "de-novo-nanobody", "targetFile": "target.pdb", "targetChains": ["A"],
   "scaffold": "default", "numDesigns": 10}
  ```

See [references/tools.md](references/tools.md) for the full per-task field maps and the catalog of every other binder tool. See [references/examples.md](references/examples.md) for more validated payloads and the end-to-end design-then-fold chain.

## Surface the consequential choices before submitting

Binder design has high-blast-radius settings. `numDesigns`, `binderLength`/`binderLengthRange`, hotspots, `maxRunTime`, and `skipRefolding` materially change cost, runtime, and whether you get any usable hits. When the request is open-ended, present the meaningful options plus the default you would otherwise apply and let the user pick **before** you submit, rather than choosing silently and reporting it after the job is queued. This matters most for **batches**, where one shared-settings choice multiplies across every job. `getJobSchema` and `validateJob`'s `normalized` show exactly which knobs you are filling in.

## Generate, then rank: read the designs back

A binder job returns many candidates and a metrics table; selecting hits is the real work. Each tool writes its ranked designs and a CSV:

- **BindCraft** -> an `Accepted/` (and `Accepted/Ranked/`) folder plus `final_design_stats.csv` (AF2 interface metrics).
- **BoltzGen** -> `final_ranked_designs/` plus `final_ranked_designs/all_designs_metrics.csv` (ipSAE / pDockQ when `runIpsae` is on), a `final_{budget}_designs/` subfolder, and `results_overview.pdf`.
- **RFdiffusion (verify=true) / RFdiffusion3** -> per-design backbone `.pdb`/`.cif` plus a scores CSV with the ProteinMPNN + AlphaFold metrics.

The bundled `scripts/summarize_binder_metrics.py` ranks designs by the interface metric (ipSAE / ipTM / pDockQ / pLDDT, auto-detected) and reports the max, 10th-best, and fraction above a confidence cutoff. Probe deps first, then run it on a downloaded results dir:

```bash
python3 -c "import requests" 2>/dev/null || python3 -m pip install -r scripts/requirements.txt || python3 -m pip install --user --break-system-packages -r scripts/requirements.txt
python3 scripts/summarize_binder_metrics.py <downloaded-results-dir>
python3 scripts/summarize_binder_metrics.py <results-dir> --metric ipsae --cutoff 0.7 --json
```

`_common.py` (vendored alongside it) supplies the CIF/PDB and CSV primitives; `gemmi`/`numpy` are only needed if you go beyond the CSV, so install them only if an import fails.

**A passing metrics CSV is necessary, not sufficient.** Pull at least one actual output structure and inspect its coordinates, sequence, and atom count, especially for a `skipRefolding` BoltzGen run where the refolded and original structures can be identical.

## Run jobs without blocking

Binder jobs run minutes to hours. Submit and poll through the base lifecycle:

```bash
python3 scripts/tamarind_job.py submit my-binder bindcraft @settings.json
python3 scripts/tamarind_job.py wait     my-binder      # polls JobStatus to terminal
python3 scripts/tamarind_job.py download my-binder      # two-step presigned -> my-binder.zip
```

- **Codex (primary):** run the script as a FOREGROUND shell command with `yield_time_ms: 1000`. Do NOT append `&` or `nohup`.
- **Claude Code:** run it via Bash with `run_in_background: true`.

Jobs are addressable by name from any process, so you can submit, persist the name, and re-attach later from a fresh session.

## Peptide and macrocycle binders

A clearly distinct family: linear peptides, head-to-tail cyclized macrocycles, and the sequence/structure tooling around them. Pick by what you have and what shape you want.

- **A macrocyclic (cyclized) binder against a target PROTEIN** -> **`rfpeptides`**. RFdiffusion run with a cyclic-closure protocol, then ProteinMPNN sequence design and AlphaFold refold validation. Cyclic backbones tend to be more protease-resistant and conformationally constrained than linear peptides.
  - Required: `pdbFile` (target), `binderLength` (single `"14"` or range `"12-18"`).
  - Knobs: `targetChains`, `binderHotspots` (per-chain, space-separated, e.g. `{"A": "48 50 51 52 62 65"}`), `numDesigns` (up to a very large ceiling, batched internally), `temperature` (this is the **diffusion-step count** displayed as "Diffusion Steps", default 50 matching the paper, NOT a sampling temperature).
  - Validated payload: `{"pdbFile": "target.pdb", "targetChains": ["A"], "binderLength": "12-18", "binderHotspots": {"A": "48 50 51 52 62 65"}, "numDesigns": 8}`
- **A de novo CYCLIC PEPTIDE, a binder against a target protein or a free scaffold** -> **`afcycdesign`**. Inverts AlphaFold with a cyclic-offset encoding to hallucinate head-to-tail cyclic-peptide backbones; it designs cyclic-peptide binders against a target as well as target-free scaffolds. Lean schema: required `pdbFile` (starting structure) + `chain`, plus `numDesigns`; confirm the exposed fields with `getJobSchema` rather than inventing target/hotspot knobs. Scale with `numDesigns`.
- **A LINEAR peptide binder from just the target SEQUENCE** (no structure needed) -> **`pepmlm`**. An ESM-2-based masked language model. Required: `targetSequence`, `peptideLength` (default 15), `numDesigns` (a **dropdown** with discrete values `[1,2,4,8,16,32]`, not a free integer). Sequence-in, sequence-out: a good first pass / large pool when you lack a structure, but a high-scoring peptide still needs downstream validation (cofold the target plus peptide, or screen developability).

Catalog (one line each, reach for these when a workflow names them; confirm with `getJobSchema`):

- **`pepmimic`**: design peptide binders by MIMICKING a known binder's interface (latent-diffusion). Needs `refComplexesZip` (a zip with an `index.txt` TSV of target/binder chains) and peptide length bounds (<= 25). Generation-only on the platform.
- **`cyclicmpnn`**: inverse folding for cyclic peptides, design sequences for a GIVEN cyclic backbone (ProteinMPNN-family with a cyclic offset). Reach for it after `rfpeptides`/`afcycdesign` gives you a backbone. Required `pdbFile`; knobs `designedChains`/`designedResidues`, `numSequences`, `temperature`.

For predicting the structure of a cyclic-peptide sequence you already have, that is structure prediction (the cyclic folder lives in `tamarind-structure-prediction`), not design.

## Catalog of other binder tools

Beyond the four canonical tools, the platform carries many binder generators. Reach for one when a workflow specifically calls for it; always `getJobSchema` it first since these drift. One line each:

- **`mosaic-hallucinate`** (Mosaic Hallucination): SOTA gradient-based single-shot de novo protein/peptide binder design; optimizes a sequence directly on a composite Boltz-2 (ipTM/PAE/contacts) + ProteinMPNN loss, collapsing the backbone-generate / inverse-fold / filter stages into one hallucination. A strong de novo alternative to `bindcraft`/`rfdiffusion` against a target sequence or structure.
- **`idr`** (IDR Binder Design): de novo protein binders against an INTRINSICALLY DISORDERED target (IDR/IDP) from the target SEQUENCE alone, no folded structure needed (RFdiffusion + ProteinMPNN + AlphaFold2 initial-guess); the complement to `bindcraft`'s folded-target scope.
- **`rfdiffusion-all-atom`**: RFdiffusion variant that diffuses all atoms (ligand/cofactor aware); the RFdiffusion-lineage option for small-molecule or cofactor-conditioned scaffolding when you do not want RFdiffusion3.
- **`rfdiffusion2`**: SOTA for atom-level ENZYME active-site scaffolding (scaffolds an atomic catalytic motif, with the ORI token controlling active-site placement); enzyme active-site design lives in `tamarind-more-tools`. For general binder design prefer `rfdiffusion3` (rfdiffusion2 is not for binders).
- **`boltzdesign`** (BoltzDesign1): inverts Boltz-1 to design binders across proteins, antibodies, peptides, enzymes, and small-molecule-binding proteins; a Boltz-1-grounded design across many modalities.
- **`pxdesign`** (PXDesign): de novo protein binder design using diffusion models; another diffusion-based protein binder generator.
- **`protein-hunter`** (Protein Hunter): broad de novo protein design / binder discovery when you want a distinct method.
- **`rso`** (RSO Binder Design): efficient binder design; reach for it for a faster/cheaper pass than the heavier diffusion pipelines.
- **`esmfold2-binder-design`**: de novo protein binders using ESMFold2 (language-model-folded); an MSA-free, ESM-based binder loop.
- **`evopro`** (EvoPro): a genetic-algorithm binder OPTIMIZATION pipeline; reach for it to affinity-mature an EXISTING binder rather than design from scratch.
- **`germinal`** (Germinal): epitope-targeted de novo ANTIBODY / nanobody design (ColabDesign hallucination, AbMPNN CDR redesign, cofold filtering); for antibodies prefer `tamarind-antibody`, this is the cross-reference.
- **`riffdiff`** (RiffDiff): a complete de novo ENZYME design pipeline from a theozyme (scaffolds the catalytic motif into a backbone with RFdiffusion, then refines sequence/structure); primarily an enzyme tool (see `tamarind-more-tools`).
- **`disco`** (DISCO): SOTA ligand-, DNA-, or RNA-conditioned sequence+structure co-design with no template or theozyme; the no-template option for small-molecule or nucleic-acid-binder and de novo enzyme co-design (primary home is the enzyme tooling in `tamarind-more-tools`).
- **`genie3`** (Genie3), **`frameflow`** (FrameFlow): SE(3) diffusion / flow-matching de novo backbone generators (sequence-free); reach for one to generate novel backbones, then design sequences with `tamarind-inverse-folding`.
- **`proteina-complexa`** (Proteina-Complexa): de novo protein binder / motif generator; another from-scratch backbone-and-binder generator alongside rfdiffusion3 / boltzgen.

## Reference files

- [references/tools.md](references/tools.md): full per-task field maps for the four canonical tools, output shapes, routing/runtime notes, and the complete binder catalog.
- [references/peptide_macrocycle.md](references/peptide_macrocycle.md): the peptide and macrocycle family in depth (rfpeptides, afcycdesign, pepmlm, pepmimic, cyclicmpnn), with validated payloads and the design-validate loop.
- [references/examples.md](references/examples.md): validated `settings` payloads per tool, the design-then-fold chain, what fails and the exact error, and output-shape notes.
