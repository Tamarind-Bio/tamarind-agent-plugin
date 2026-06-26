---
name: tamarind-inverse-folding
description: Use when designing SEQUENCES for a fixed protein backbone (inverse folding) or running a protein language model on Tamarind Bio for embeddings, mutational scanning, or generative sequence design. Covers ProteinMPNN (and its soluble/hyper/ab/ligand modelType variants), LigandMPNN, ESM-IF1, ESM-C 6B, the ESM/PLM scoring family, the embeddings trio (ESM2 / ESM-C / ProtT5), and generative and directed-evolution LMs. Not for de novo BACKBONE generation from scratch (use tamarind-binder-design), not for antibody CDR design with antigen context (use tamarind-antibody), not for first-time key setup (use tamarind-api-setup).
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: inverse folding and protein language models

Two intertwined jobs live here. **Inverse folding**: you have a 3D backbone and want amino-acid sequences predicted to fold into it (ProteinMPNN, LigandMPNN, ESM-IF1). **Protein language models (PLMs)**: you have a sequence and want a learned representation (embeddings), a per-position mutational-effect score (masked-LM scan), or generated variants. Inverse folding takes a STRUCTURE and emits SEQUENCES; a PLM takes a SEQUENCE and emits vectors, scores, or new sequences.

This skill builds on the base job lifecycle in `tamarind-submit-and-poll` (validate, submit, poll to terminal, download). It assumes you can run one job; here it adds **which tool fits which input**, the **per-tool required fields and numbering conventions**, and the **read-back step**. For first-time key setup use `tamarind-api-setup`; for many sequences or backbones use `tamarind-batch`.

Scope boundaries worth stating up front. Generating a brand-new backbone from scratch is de novo design (`tamarind-binder-design`), not inverse folding (which redesigns a backbone you already have). Antibody CDR redesign with antigen context has its own IMGT-aware machinery and lives in `tamarind-antibody` (AbMPNN, AntiFold, IgDesign). Structure-conditioned stability prediction (ddG) is a developability question (`tamarind-developability`), not a sequence-design one.

## Pick the tool by what you HAVE and what you WANT

Filter live first (`getAvailableTools(function="inverse-folding")` or `function="protein-language-models"`, or `GET /tools`), read each candidate's `description`, and match it to your actual input/output. The catalog drifts, so confirm with `getJobSchema` before committing. Starting orientation:

- **A backbone, you want general-purpose sequences** -> **`proteinmpnn`**. The workhorse inverse folder; nearly every de novo design pipeline ends in a ProteinMPNN sequencing step. Its `modelType` selector reaches four siblings WITHOUT switching tools (see below).
- **A backbone WITH a bound ligand / metal / nucleic acid you want held fixed** -> **`ligandmpnn`**. The one inverse folder that "sees" hetero-atoms, so the designed residues are chosen to be compatible with the cofactor in the pocket. Plain ProteinMPNN ignores ligands entirely.
- **A single-chain backbone, you want a language-model second opinion** -> **`esm-if1`**. A structure-conditioned LM (not a GNN); fast, single-chain, minimal knobs. Good as a cross-check alongside ProteinMPNN.
- **A sequence (no structure), you want a learned vector** -> the embeddings trio: **`esm-embeddings`** (ESM2, full 8M-15B size ladder), **`esmc-embeddings`** (newer ESM-C, layer knob + multimer), **`prot-t5-embeddings`** (ProtT5, long sequences / matching a ProtT5 pipeline).
- **A sequence, you want to rank point mutations / an in-silico DMS** -> the masked-LM scan family: **`esmc-6b`** (`task: scan`, strongest sequence-only), **`esmc-scan`** (pick a smaller ESM-C size), **`esm2`** (classic ESM-2), **`esm-scan`** (ESM-1b baseline), **`amplify`**.
- **A sequence prompt, you want NEW generated sequences** -> the generative LMs: **`progen2-inference`** (samples from a finetuned ProGen2 checkpoint), **`zymctrl`** (enzymes conditioned on EC number).
- **A sequence you want to evolve toward higher fitness** -> directed-evolution: **`evoprotgrad`** (gradient-based over PLM likelihood), **`structural-evolution`** (complex-aware, conditions on the bound partner).

When the user names a specific tool, evaluate it and sanity-check a sibling in the same `function` group, then let `validateJob` confirm the input you have actually fits. The catalog section near the end names the rest so you can reach for one when a workflow calls for it.

## The four canonical tools (required fields, gotchas, validated payloads)

File-typed params (`pdbFile`) take the **bare filename** of an uploaded file, a prior-job output path (`JobName/...`), or inline PDB text; NOT an email-prefixed S3 key (see `tamarind-submit-and-poll` for the file-param rule). `validateJob` does a real file-existence check, so a not-yet-uploaded filename returns `valid:false` until you upload it (for a quick no-upload dry-run, pass inline PDB text instead). Act on `valid`, not the `source` label (built-in tools always report `static-fallback`, a schema-resolution note, not a "validator down" signal).

### proteinmpnn

Inverse folding for a single- or multi-chain backbone.

- Required: `pdbFile` (the backbone), `designedResidues` (per-chain map of residues to redesign, **space-separated PDB author numbers**, e.g. `{"B": "26 27 28 29 30"}`; an empty value for a chain redesigns that whole chain).
- `modelType` (default `proteinmpnn`): the variant selector that reaches four siblings in one tool: `solublempnn` (soluble-only training, fewer aggregation-prone residues), `hypermpnn` (thermostability-biased), `abmpnn` (antibody-finetuned, IMGT-renumbers the input in place), `ligandmpnn` (cofactor-aware). So "ProteinMPNN but for solubility / thermostability / antibody" is a `modelType` change, not a different tool.
- Key knobs: `numSequences` (default 2), `temperature` (default 0.1, range 0-1; higher = more diverse, suggested 0.1-0.3), `noiseLevel` (`0.02`/`0.1`/`0.2`/`0.3`, higher noise = more robust to imperfect backbones), `omitAAs` (default `C`, cysteine omitted to avoid spurious disulfides), `bias_AA` / `bias_AA_per_residue` / `omit_AA_per_residue` (per-AA or per-position biasing), `homo_oligomer` (tie sequences across symmetric chains).
- Gotchas: `designedResidues` numbers are PDB author numbers, NOT 0-indexed positions; do not pre-renumber to 1..N (the wrapper maps the tokens directly). `designedChains` is tagged `exclude:["api"]` in the schema; you can leave it out (omitted = design all chains). `verifySequences` (UI auto-fold-back) is tagged `exclude:["api","pipelines","batch"]`; do NOT send it over the API. `numSequences` above 100 is split into 100-seq batches internally and concatenated, so a large value is fine but slower.
- Validated payload:
  ```json
  {"pdbFile": "backbone.pdb",
   "designedResidues": {"B": "26 27 28 29 30 31 32"},
   "numSequences": 4, "temperature": 0.1, "modelType": "proteinmpnn", "omitAAs": "C"}
  ```

### ligandmpnn

Inverse folding with the small-molecule / metal / nucleic-acid context held fixed. It IS the ProteinMPNN wrapper run with `--model_type ligand_mpnn`, so the fields match proteinmpnn (minus the `modelType` selector).

- Required: `pdbFile` (the backbone **including** the ligand/metal/nucleic-acid HETATM or chain records, those are the context).
- Same knobs as proteinmpnn: `designedChains` (`exclude:["api"]`), `designedResidues` (per-chain, space-separated author numbers), `numSequences`, `temperature`, `omitAAs`, the bias/omit JSON fields, `homo_oligomer`.
- Gotchas: the ligand/cofactor MUST be present in the uploaded PDB as HETATM (or a separate chain for nucleic acids). If you strip waters/ligands before uploading, LigandMPNN degenerates to plain ProteinMPNN behavior with NO warning. Per-residue numbering follows the same author-number convention as proteinmpnn.
- Validated-shape payload (upload a real cofactor-containing PDB first, then pass its bare name):
  ```json
  {"pdbFile": "enzyme_with_substrate.pdb",
   "designedResidues": {"A": "60 61 62 63 64 65 66"},
   "numSequences": 4, "temperature": 0.1, "omitAAs": "C"}
  ```

### esm-if1

Language-model inverse folding for a SINGLE chain. The PLM-flavored alternative to ProteinMPNN's GNN style. It can also score point-mutation variants zero-shot against the fixed backbone (stability/affinity prioritization), not only generate sequences.

- Required: `pdbFile`, `chain` (a single chain ID, e.g. `A`), `designedResidues` (a **range string** scoped to that chain, e.g. `62-70`, comma-separated for multiple ranges, NOT a per-chain dict).
- `numSequences` (default 10).
- Gotchas: **the schema warns "make sure the indices are numbered from 1 to N."** This is the most common ESM-IF1 footgun and it is the OPPOSITE of the MPNN family rule: renumber the chain to 1..N before uploading, because a PDB straight off the PDB (or out of a cropping step) often starts at a nonzero residue number, which shifts the `62-70` selection. The `designedResidues` format also differs from the MPNN family: a hyphenated range, not a space-separated per-chain dict. ESM-IF1 is single-chain by construction; to inverse-fold a complex, submit one job per chain (or batch them).
- Validated-shape payload (`backbone_renum.pdb` must be renumbered 1..N before upload):
  ```json
  {"pdbFile": "backbone_renum.pdb", "chain": "A", "designedResidues": "62-70", "numSequences": 10}
  ```

### esmc-6b

The largest ESM-Cambrian PLM (6 billion params), sequence-only (no MSA, no structure). Two modes via `task`.

- Required: `task` (`embeddings` or `scan`), `sequence` (the protein; `sequenceBatching:true` so a multi-sequence input fans out).
- `embeddings` mode: per-residue (and mean-pooled) 2560-dim vectors. Knobs: `outputFormat` (`pt` PyTorch tensor / `json` list-of-lists), `layerPreset` (`last` default / `first` / `custom`), `layerIndex` (1-36, only when `layerPreset:custom`).
- `scan` mode: a per-position x 20-AA log-likelihood matrix for ranking point mutations (in-silico DMS).
- Gotchas: `task: scan` here is a per-position LIKELIHOOD matrix, NOT a structure-conditioned ddG; for fold-stability ddG use the developability tools (`thermompnn` / `proteinmpnn-ddg` / `rosetta-ddg-prediction`), not this. Embeddings are sequence-only, so identical sequences give identical embeddings regardless of any structure context; for structure-aware tokens use `saprot`. The 6B model is the slow/expensive end of the family; for high-throughput scanning prefer `esmc-scan` with a smaller ESM-C size.
- Validated payload (sequence-typed, directly runnable with no upload):
  ```json
  {"task": "scan", "sequence": "MKTIIALSYIFCLVFADYKDDDDK"}
  ```

See [references/tools.md](references/tools.md) for the embeddings trio in depth, the full PLM scoring / generative / directed-evolution catalog, and output shapes. See [references/examples.md](references/examples.md) for more validated payloads, the design-then-fold chain, and what fails.

## The embeddings trio (sequence in, vectors out)

Three protein embedders, all sequence-only (no MSA, no structure). Pick by the backbone you need:

- **`esm-embeddings`** (ESM2): the default workhorse and the only one with the full **size ladder** (`model`, 8M / 35M / 150M / 650M / 3B / 15B). Bigger = richer but more GPU/time/cost. Writes both pooled (per-sequence) and per-residue tensors. Use the small (8M/35M) models for cheap embedding at scale, the large ones for the richest representation.
- **`esmc-embeddings`** (ESM-C, current generation): generally stronger per parameter. Exposes a `layer` knob (`last`/`first`/integer; ESM2 and ProtT5 here do not) and native multimer handling (separate chains with `:`, remapped to ESM-C's `|`). `model` is `esmc-300m`/`esmc-600m`/`esmc-6b`.
- **`prot-t5-embeddings`** (ProtT5-XL): reach for it to match a ProtT5-built pipeline, or for very long sequences (T5 relative-position bias has no hard architectural length cap). **Writes per-residue embeddings ONLY (no pooled per-sequence vector)** unlike ESM2; if a downstream step wants one vector, mean-pool the per-residue tensor yourself. Fewest knobs of the three (just `sequence`).

All three accept `outputFormat` where exposed (`pt`/`json`) and take a colon-separated multimer string. For many sequences, prefer the platform `tamarind-batch` path over the single-job `sequenceBatching` knobs (it amortizes weight loading). Validated payloads are in [references/examples.md](references/examples.md).

## Surface the consequential choices before submitting

Several settings here have real blast radius. `modelType` (which MPNN variant), `numSequences`, `temperature` / `noiseLevel`, the embeddings `model` size (8M vs 15B is a large cost/time swing), and `task` (embeddings vs scan) materially change the results, runtime, or cost. When the request is open-ended, present the meaningful options plus the default you would otherwise apply and let the user pick **before** you submit, rather than choosing silently and reporting it after the job is queued. This matters most for **batches**, where one shared-settings choice multiplies across every job. `getJobSchema` and `validateJob`'s `normalized` show exactly which knobs you are filling in.

## Read the results back

- **Inverse folding** (proteinmpnn / ligandmpnn / esm-if1) -> a FASTA of designed sequences (`seqs/...fa`) plus a `metrics.csv` of per-sequence scores (ProteinMPNN score / global score / recovery), bundled in the result zip. Each header carries the sampling temperature and score. Rank by score, then **fold the designed sequences back to verify** (see chaining).
- **Embeddings** -> a `.pt` (or `.json`) tensor archive of per-residue (and, for ESM2/ESM-C, mean-pooled) vectors. Feed these to your downstream predictor / clustering / probe.
- **Masked-LM scan** -> a per-position x AA log-likelihood matrix (CSV/JSON) for mutation ranking.

Enumerate exact output paths with MCP `listJobFiles(jobName)` (it returns each file's `s3Path`) before downloading; do not hardcode filenames, which vary by tool and version. The job row's `Score` and `WeightedHours` carry the tool metrics and the billing unit (weighted hours; GPU tools cost more per wall-hour than CPU tools).

## Chain: design sequences, then fold them back

Inverse folding emits SEQUENCES, so verifying them is a fold step. **Match the input type the next tool wants:** fold a designed sequence by passing it as a `sequence`, NOT through a file/template field. The cleanest design-then-fold chain is MCP `submitBatch(fromJob=...)`, which reads a completed design job's generated sequences and folds each as one job:

```
# ProteinMPNN designs sequences -> fold every one with a structure predictor, one call:
submitBatch(batchName="verify-designs", type="esmfold", fromJob="my-proteinmpnn-job")
```

Do NOT route a designed sequence through a structural-template file param (e.g. an AlphaFold `templateFiles`): that is a structural template, gated and `.cif`-only, not "fold this sequence." To fold a sequence, pass `sequence`. See `tamarind-submit-and-poll` references for the full chaining rules.

## Run jobs without blocking

Inverse-folding and PLM jobs run seconds to minutes (the 6B and 15B models are the slow end). Submit and poll through the base lifecycle:

```bash
python3 scripts/tamarind_job.py submit my-design proteinmpnn @settings.json
python3 scripts/tamarind_job.py wait     my-design      # polls JobStatus to terminal
python3 scripts/tamarind_job.py download my-design      # two-step presigned -> my-design.zip
```

- **Codex (primary):** run the script as a FOREGROUND shell command with `yield_time_ms: 1000`. Do NOT append `&` or `nohup`.
- **Claude Code:** run it via Bash with `run_in_background: true`.

Probe the deps first; install only if the import fails:

```bash
python3 -c "import requests" 2>/dev/null || python3 -m pip install -r scripts/requirements.txt || python3 -m pip install --user --break-system-packages -r scripts/requirements.txt
```

Jobs are addressable by name from any process, so you can submit, persist the name, and re-attach later from a fresh session. The `from tamarind_client import ...` form only resolves from `scripts/`; the wrapper above resolves from any cwd (see `tamarind-submit-and-poll`).

## Catalog of the rest (one line each)

Reach for one of these when a workflow names it; `getJobSchema` it first since these drift.

**Inverse-folding / MPNN family**
- **`caliby`**: SOTA ensemble/multistate inverse folding (a structure-conditioned Potts model sampled by discrete Langevin MC). Reach for it to design sequences over a STRUCTURAL ENSEMBLE or to rescue native/de novo backbones that ProteinMPNN fails to design; single backbone or a user-supplied multi-state ensemble. Apo backbone-conditioned (for a fixed ligand in the pocket use `ligandmpnn`).
- **`fixbb`** (ColabDesign Fixed Backbone): inverse folding by reversing AlphaFold (gradient hallucination in sequence space); supports fixing some residues and designing the rest. The general-IF cross-reference; slower than the LM/GNN folders (runs an AF loop), reach for it for AF-consistent partial redesign.
- **`proteinmpnn-score`**: SCORE an existing sequence against a backbone (per-residue/global scores) rather than generate; reach for it to rank or filter sequences you already have. Knobs: `pdbFile`, `sequence`, `allChains` or a single `chain`.
- **`protein-metrics`** (COMPSS): ensemble design-FILTER scorer that runs ESM-IF / ProteinMPNN / MIF-ST (structure) plus ESM-1v / CARP (sequence) likelihoods in one pass; reach for it to triage a large library of designed sequences down to a wet-lab shortlist. Companion to `proteinmpnn-score`; it only scores, it does not generate.
- **`hypermpnn`**: ProteinMPNN retrained to bias toward thermostable, hyperthermophile-like sequences; reach for it when stability/Tm matters more than native recovery. Also reachable as `modelType: hypermpnn`.
- **`cyclicmpnn`**: ProteinMPNN variant for stable CYCLIC peptide sequences on a given backbone (handles the wrap-around numbering); reach for it after a cyclic backbone tool gives you a structure.
- **`nampnn`**: sequence design for protein, RNA, DNA, and mixed-polymer structures plus protein-DNA binding-specificity; reach for it when the nucleic acid is itself being DESIGNED, not just held as fixed context (that is ligandmpnn).
- **`abmpnn`** / **`ablang-mpnn`**: antibody-tuned inverse folding (AbMPNN finetuned on antibodies; AbLang-MPNN blends an antibody LM with ProteinMPNN). For antibody work prefer `tamarind-antibody`; these are the cross-reference.

**PLM scoring / mutational scanning**
- **`esm2`**: ESM-2 masked LM in two modes, `mask` (fill masked residues) and `scan` (per-position x AA likelihood); reach for it for classic ESM-2 mask-filling or an in-silico DMS when a published pipeline expects ESM-2.
- **`esmc-scan`**: per-position mutational scan with a selectable ESM-C backbone (`esmc-300m`/`esmc-600m`/`esmc-6b`); reach for it instead of `esmc-6b` when you want a cheaper size or to compare sizes in one tool.
- **`esm-scan`**: point-mutation scoring with the older ESM-1b baseline.
- **`amplify`**: variant scoring with the AMPLIFY protein LM; an efficient, recent masked-LM scorer.
- **`profluent-e1`**: SOTA retrieval-augmented PLM; scores zero-shot SINGLE-substitution mutants (and runs in-silico site-saturation), optionally conditioned on homolog sequences for better accuracy, and emits sequence embeddings. Peer of esm2/esmc/amplify (stronger at matched sizes when homologs are available); NOT for sequence generation / de novo design or multi-mutant/epistatic scoring.
- **`saprot`**: structure-aware PLM (Foldseek 3Di token alphabet) for property prediction (solubility, thermostability, developability); reach for it when sequence-only PLMs miss structure-dependent properties. (Stability ddG lives in `tamarind-developability`.)

**Generative / directed-evolution LMs**
- **`progen2-inference`**: samples sequences from a ProGen2 language model; built to sample from a `progen2-finetune` checkpoint (family-conditioned generation after finetuning on a target family / distribution). Reach for it to generate candidates from a ProGen2 model you have finetuned.
- **`zymctrl`**: conditional generative LM for artificial enzymes (conditioned on EC number / function); reach for it to generate candidate enzyme sequences for a target reaction class.
- **`profam`**: protein-family language model; reach for it FIRST for zero-shot fitness / point-mutation (and indel) scoring conditioned on a set of homologs, then for family-aware sequence generation.
- **`fampnn`** (FaMPNN): full-atom inverse folding, designs a sequence AND packs its sidechains for the fixed backbone; reach for it when you want explicit all-atom sidechain output rather than sequence-only (the proteinmpnn default).
- **`evoprotgrad`**: gradient-based directed evolution over PLM likelihood to propose improving mutations (in-silico directed evolution toward higher fitness/activity).
- **`structural-evolution`**: mutate protein COMPLEXES with a structure-informed LM (conditions on the bound partner); reach for it for affinity-maturation-style mutations where the interface context matters.
- **`multi-evolve`**: ML-guided directed evolution that trains on your DMS / pairwise-combination assay data, nominates synergistic MULTI-mutants accounting for epistasis, and designs MULTI-assembly mutagenic oligos for gene synthesis (and runs a zero-shot PLM ensemble to nominate single mutants when no assay data exists yet). Reach for it to stack beneficial mutations where single-mutant scoring is insufficient.

**Evolutionary-covariance scoring**
- **`evcouplings`**: unsupervised single-mutation fitness from evolutionary sequence covariation (a coupling model over an MSA). Input is just `sequence`, but it is MSA-dependent (it builds/downloads an MSA) and runs on CPU. Reach for it for a homology-rich protein; use `esmc-6b` instead for MSA-free zero-shot mutation scoring.

## Reference files

- [references/tools.md](references/tools.md): the embeddings trio in depth, full per-tool field maps, output shapes, routing/runtime notes, and the complete PLM catalog.
- [references/examples.md](references/examples.md): validated `settings` payloads per tool, the design-then-fold chain, what fails and the exact signal, and output-shape notes.
