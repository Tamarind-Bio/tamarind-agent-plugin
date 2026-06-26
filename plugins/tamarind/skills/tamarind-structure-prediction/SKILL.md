---
name: tamarind-structure-prediction
description: "Use when folding or co-folding a biomolecule from sequence on Tamarind Bio: predict the 3D structure of a protein, a complex, or a protein+ligand / nucleic-acid assembly, optionally with binding affinity. Covers AlphaFold, Boltz-2, Chai-1, ESMFold2, Protenix, and the wider folding catalog (OpenFold, IntelliFold, RoseTTAFold-3, ESMFold, OmegaFold, CombFold, AlphaLink2, conformational-ensemble AF derivatives, HighFold cyclic peptides). Not for de novo design of a NEW binder or backbone (use tamarind-binder-design), not for antibody/nanobody-specific structure (use tamarind-antibody), not for docking a known ligand into a known pocket (use tamarind-docking)."
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: structure prediction (folding and co-folding)

Predict the 3D structure of a biomolecule from sequence. A single protein, a multimer, or a complex of proteins with nucleic acids and small-molecule ligands, optionally with a binding-affinity number. This is the highest-demand work on the platform, and most of it routes through five tools: `alphafold`, `boltz`, `chai`, `esmfold2`, `protenix`. The catalog has many more folders for special cases (below).

This skill is the folding layer on top of the base job lifecycle. The submit/poll/download mechanics live in `tamarind-submit-and-poll`; this skill picks the right folder, builds correct `settings`, and reads the confidence back. If `TAMARIND_API_KEY` is unset or a call returns 401, run `tamarind-api-setup` first.

The canonical order is the same everywhere: **discover -> schema -> validate -> submit -> poll -> download -> parse confidence.** Do not hardcode a tool or its settings; the catalog drifts and schemas evolve. Fetch the live schema (`getJobSchema` / `GET /tools`) and let `validateJob` confirm the shape before you spend.

## Pick the right folder

Match the user's INPUT and OUTPUT, not a favorite name. Filter live with `getAvailableTools(function="structure-prediction")`, read each candidate's `description`, then confirm fields with `getJobSchema`. Quick orientation:

- **Single protein or multimer (default)** -> an AlphaFold3-class cofolder, `boltz` is the platform default for almost any target (proteins included). Reach for `alphafold` specifically when you need AF2/ColabFold weights: reproducing AF2 results, matching an AF2-trained downstream model, full MSA + template control, tuned recycles, an `initialGuess` refine, or an AF2-dependent pipeline (it handles proteins only, up to 5000 residues; AF2 is superseded by AF3-class models for most new prediction work). For a fast MSA-free fold, `esmfold2` (or `omegafold` for orphan sequences with no good MSA).
- **A complex with a small-molecule ligand, DNA, or RNA** -> an AlphaFold3-class cofolder: `boltz`, `chai`, `protenix`. These predict the bound complex from sequence; reach for them whenever a ligand or nucleic acid is part of the system.
- **You also want a binding-affinity number** -> `boltz` with `predictAffinity` (small-molecule binders). It is the only folder in this bucket with an affinity head.
- **A hard interface, especially antibody-antigen** -> `protenix` reports major gains there. (Antibody-SPECIFIC modeling, CDR design, numbering, and humanization live in `tamarind-antibody`.)
- **Speed over everything** -> `esmfold2` (language-model trunk, single-sequence option, ~2000-residue cap; set `model:"esmfold2-fast"` for the faster variant); `chai` with `useMSA:false` swaps the real MSA for a language-model embedding at ~90% accuracy.
- **A second independent model for consensus** -> run two of `boltz` / `chai` / `protenix` / `openfold` / `intfold` / `rf3` and compare confidence.
- **Conformational ensembles, large assemblies, cyclic peptides, restraint-guided** -> see "Wider catalog" below.

See [references/tools.md](references/tools.md) for the full per-tool schema, when-to-pick reasoning, and gotchas.

## MSA: the primer behind boltz / alphafold / chai / protenix

Most accurate folders condition on a multiple-sequence alignment (MSA), and the platform generates it for you by default (`useMSA:true`, `msaDatabase` defaults to `uniref`). You rarely call MSA directly for a one-off fold. Two cases where it matters:

- **`msa` is its own tool.** Submit `type:"msa"` to generate an alignment for a sequence (`msaDatabase` = `uniref` / `swissprot` / `uniref+swissprot`; `monomer_msa:true` for a separate MSA per chain vs one for the whole complex; optional `templateMode:"pdb100"` to also emit a PDB100 template search). Use it to inspect MSA depth, reuse one alignment across runs, or prime a folder that has no built-in MSA worker.
- **Precomputed MSA (`a3mFiles`).** boltz/chai accept uploaded `.a3m` alignments (one per protein chain) instead of generating them. **An a3m is matched to a chain by its QUERY SEQUENCE, not by filename** (the first sequence in the a3m must equal that chain's sequence), and you map files to chains explicitly (`a3mMapping` for boltz: `a3mName` + `boltzChainID`). MSA generation is skipped for any chain you supply an a3m for. (These params are version-gated, e.g. boltz `version:"2.2.1"` -> confirm with `getJobSchema`.)

For a quick, MSA-free fold, turn the MSA off (`useMSA:false`) or use a single-sequence folder (`esmfold2`, with `model:"esmfold2-fast"` for the faster variant, or `omegafold`); expect lower accuracy on sequences with rich evolutionary signal.

## Build settings (per-folder required fields differ)

`sequence` alone is rarely enough. The cofolders take a task selector:

- `alphafold`: `sequence` is the only required field. Multimer = one `sequence` with chains joined by `:`.
- `boltz`, `protenix`, `chai`: `inputFormat` is **required** (`"sequence"` is the common case; `boltz`/`esmfold2` also accept `"yaml"`; `chai` adds `"molecules"`; `protenix` is `"sequence"`/`"list"` only). In `sequence` mode, `sequence` is required, chains joined by `:`.
- Ligands: for `boltz`/`protenix` set `addLigands:true`, then `ligands` (a list); `chai` has no `addLigands` param, so pass `ligands` directly. boltz/chai take bare CCD codes or SMILES; **protenix prefixes CCD codes with `CCD_`** (e.g. `CCD_ATP:CCD_MG`), so don't copy a ligand value across tools.
- `esmfold2`: `inputFormat` defaults to `sequence`; pick the `model` (`esmfold2` full vs `esmfold2-fast`).

Always `getJobSchema(<tool>)` then `validateJob` before submitting. validateJob runs the real submit-validation with no spend and names the first bad field. Act on `valid`, not the `source` label (built-in tools always report `static-fallback`, which is a schema-resolution note, not a "validator down" signal). Submit the clean settings you validated, not validateJob's `normalized` echo. See `tamarind-submit-and-poll` for the validateJob authority rule and `references/examples.md` for validated payloads.

## Surface consequential choices before submitting

When the request fully specifies what to run, proceed. But a folding submit hides several knobs that change runtime, cost, and results: `numSamples` / `numModels` / `numBatches` (a 5x sample count is roughly 5x the cost), MSA on/off, `model`/`version` choice, GPU-driving length, and whether to compute affinity. When the request is open-ended, present the meaningful options plus the default you would apply and let the user pick BEFORE you submit, rather than choosing silently and reporting it after the job is queued. `getJobSchema` and validateJob's `normalized` show exactly which knobs you would be filling in.

## Submit, poll, download

Drive the lifecycle through the bundled CLI wrapper so the sibling client import resolves from any cwd (probe `python3 -c "import requests"` first; install `scripts/requirements.txt` only if it fails):

```bash
python3 scripts/tamarind_job.py submit my-fold boltz \
  '{"inputFormat":"sequence","sequence":"MKT...:EVQ..."}'
python3 scripts/tamarind_job.py wait     my-fold      # polls JobStatus to a terminal state
python3 scripts/tamarind_job.py download my-fold      # two-step presigned -> my-fold.zip
# or submit + wait + download in one call:
python3 scripts/tamarind_job.py run      my-fold boltz @settings.json
```

`wait` polls on a 15-30s cadence and raises on `Stopped`/`Failed`; for a stopped job read the tail with MCP `getJobLogs(jobName)` (bad input, OOM, length cap, budget). Jobs run minutes to hours, so launch the submit/poll with the runtime's non-blocking facility:

- **Codex (primary):** run the script as a FOREGROUND command with `yield_time_ms: 1000`; do NOT append `&` or `nohup`.
- **Claude Code:** run it via Bash with `run_in_background: true`.

Jobs are addressable by name from any process, so you can submit, persist the name, and re-attach later with `tamarind_job.py get`/`wait` from a fresh session. For MANY sequences through one folder use `tamarind-batch` (poll the parent `batchStatus`); to chain design -> fold -> score use `tamarind-pipeline`.

## Read the confidence back

Folding outputs are non-deterministic (seed / model / MSA), so reason about the metric SHAPE, not golden numbers. A completed job's `Score` field (a JSON string) carries the headline metrics, and the results zip has the structures (`rank_*.pdb` / `*.cif`), a per-model `-scores.csv`, and logs. The metrics:

- **pLDDT** (0-100): per-residue / mean local confidence (stored in the B-factor column of the structure). Higher is better.
- **pTM** (0-1): global fold confidence. **ipTM** (0-1): interface confidence for a complex.
- **ipSAE**, **pDockQ**: interface-quality metrics for protein-protein complexes (boltz `runIpsae:true`).
- **affinity**: a binding score when boltz `predictAffinity` is on.

The bundled `scripts/parse_boltz_confidence.py` reads a downloaded results dir (or a single scores CSV) and prints a per-model table ranked by the platform's own selection metric, flagging any model whose interface confidence falls below a cutoff. It works across boltz / chai / alphafold / protenix / esmfold2 output:

```bash
python3 -c "import gemmi, numpy" 2>/dev/null || python3 -m pip install -r scripts/requirements.txt || python3 -m pip install --user --break-system-packages -r scripts/requirements.txt
python3 scripts/parse_boltz_confidence.py my-fold/            # ranked table
python3 scripts/parse_boltz_confidence.py my-fold/ --json     # machine-readable
python3 scripts/parse_boltz_confidence.py my-fold/ --iptm-cutoff 0.6
```

To enumerate a job's exact output filenames before downloading, use MCP `listJobFiles(jobName)` (returns `s3Path`, usable directly as the next job's file input). For deeper metric read-back and downstream chaining, see `tamarind-results-analysis`.

## Verify the structure, not just the metric

A passing confidence CSV is necessary, not sufficient. Before trusting a result, open at least one actual output structure and sanity-check it: chain count, sequence, atom count, and that distinct models aren't byte-identical. The `Score` row can look fine while the structure is wrong, so spend the extra read.

## Wider catalog (one line each; confirm params live)

These cover special cases. Filter with `getAvailableTools(function="structure-prediction")` and `getJobSchema(<tool>)` before submitting; details in [references/tools.md](references/tools.md):

- **More AF3-class cofolders** (consensus / alternatives to boltz/chai/protenix): `openfold` (OpenFold3), `intfold` (IntelliFold-2), `rf3` (RoseTTAFold-3).
- **Single-sequence / language-model folding:** `esmfold` (original ESMFold, protein-only; superseded by `esmfold2`), `omegafold` (MSA-free, orphan sequences).
- **Large assemblies:** `combfold` (CombFold, AlphaFold-Multimer on subunit pairs plus combinatorial assembly when the complex is too big for one cofold pass).
- **Restraint-guided complexes:** `alphalink2` (complex structure from crosslinking mass-spec / XL-MS restraints). For pocket/contact restraints, boltz / chai / protenix expose them directly.
- **Conformational ensembles / multiple states** (AlphaFold derivatives, when you want a distribution rather than one best model): `alphaflow`, `af-traj`, `afcluster`, `af2rave`, `bioemu`, `afsample`, `af-unmasked`. (`bioemu` also surfaces under the `molecular-dynamics` facet, where its primary tag lives, so filter that facet if it does not appear under structure-prediction.)
- **Cyclic peptides:** `highfold` (head-to-tail cyclics, where linear folders mis-model the closure); boltz also has a `cyclicPeptide` flag.
- **De novo backbone generation** (sequence-FREE generators, design-adjacent, not sequence-to-structure folding): `genie3`, `frameflow` -> see `tamarind-binder-design`.

## Reference files

- [references/tools.md](references/tools.md): per-tool schema, when-to-pick, and gotchas for the five canonical folders plus the wider catalog. Cites `getJobSchema` as the authority.
- [references/examples.md](references/examples.md): validated `settings` payloads (alphafold monomer/multimer, boltz sequence + ligand + affinity, esmfold2, protenix, chai), the read-only self-check, what fails with the exact error, and output shapes.
- `scripts/parse_boltz_confidence.py`: rank models by confidence, flag weak interfaces.
