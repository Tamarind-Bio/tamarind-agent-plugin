# Inverse folding and PLMs: field maps, outputs, catalog

> Operational examples in this reference use the Tamarind CLI. Query the live catalog and schema before relying on this grounded snapshot.

Source of truth is `tamarind --json tools --function inverse-folding`, `tamarind --json tools --function protein-language-models`, and `tamarind --json schema TOOL`. The catalog drifts; treat everything below as a grounded snapshot and re-query when a field stops validating. File-typed parameters such as `pdbFile` take the **bare filename** returned by `tamarind --json files upload PATH`, a prior-job output path (`JobName/...`), or inline PDB text; they do NOT take an email-prefixed object key (see `tamarind-submit-and-poll` for the full file-parameter rule).

The two families differ in input: inverse folders take a STRUCTURE (`pdbFile`) and emit SEQUENCES; PLMs take a SEQUENCE (`sequence`) and emit vectors, score matrices, or new sequences. Read the residue-numbering convention per tool: the MPNN family uses PDB AUTHOR numbers, ESM-IF1 requires 1..N renumbering.

---

## proteinmpnn (ProteinMPNN)

The workhorse inverse folder: a message-passing GNN that autoregressively samples residues conditioned on backbone geometry.

- `pdbFile` (required, `.pdb`): the backbone to design.
- `designedResidues` (required, `selectMultichainResidues`, per-chain map, **space-separated** PDB author numbers within a chain): the residues to redesign, e.g. `{"B": "26 27 28 29 30 31 32"}`. An empty value for a listed chain redesigns that whole chain.
- `designedChains` is UI-only for this tool. Omit it from CLI settings (omitted = design all chains).
- `numSequences` (default 2): sequences per backbone.
- `temperature` (default 0.1, 0-1): sampling diversity; higher = more diverse, suggested 0.1-0.3.
- `modelType` (default `proteinmpnn`; `task`-typed): `proteinmpnn` | `ligandmpnn` | `solublempnn` | `hypermpnn` | `abmpnn`. The variant selector that reaches four siblings without switching tools (soluble = soluble-only training; hyper = thermostability-biased; ab = antibody-finetuned, IMGT-renumbers in place; ligand = cofactor-aware).
- `noiseLevel` (default `0.2`; `0.02`/`0.1`/`0.2`/`0.3`): which noise-trained checkpoint (higher noise = more robust to imperfect backbones).
- `omitAAs` (default `C`): amino acids never sampled (cysteine omitted by default to avoid spurious disulfides).
- `bias_AA` (string, e.g. `W:3.0,P:3.0,C:3.0,A:-3.0`): global per-AA log-odds bias.
- `bias_AA_per_residue` (json, keyed `{"C1": {"P": 10.0}}` = chain+resnum): per-position per-AA bias.
- `omit_AA_per_residue` (json): per-position omit; to FORCE a residue at a position, omit all others.
- `homo_oligomer` (number): copies to tie sequences across symmetric chains (2 = dimer, 3 = trimer).
- `verifySequences` is UI-only auto-fold-back; do not include it in CLI settings.

Output: a FASTA of designed sequences (`seqs/...fa`) plus a `metrics.csv` (per-sequence ProteinMPNN score / global score / recovery). Each header carries its sampling temperature and score.

Numbering: `designedResidues` are PDB author numbers, NOT 0-indexed. Do not pre-renumber to 1..N. `numSequences` above 100 is split into 100-seq batches internally and concatenated.

---

## ligandmpnn (LigandMPNN)

Inverse folding with the bound ligand / metal / nucleic acid held fixed as context. The same wrapper as ProteinMPNN run with `--model_type ligand_mpnn`, so the fields match proteinmpnn minus the `modelType` selector.

- `pdbFile` (required, `.pdb`): the backbone INCLUDING the ligand/metal/nucleic-acid HETATM or chain records (those are the context).
- `designedChains` is UI-only; `designedResidues` (per-chain, space-separated author numbers), `numSequences` (default 2), `temperature` (default 0.1), `omitAAs` (default `C`), `bias_AA`, `bias_AA_per_residue`, `omit_AA_per_residue`, and `homo_oligomer` otherwise have the same semantics as proteinmpnn.
- `noiseLevel`: present in the schema but gated to `modelType == proteinmpnn`; the ligandmpnn tool uses the LigandMPNN checkpoint directly.
- Categories include `small-molecule-binding-protein` and `nucleic-acid`, reflecting the ligand/NA awareness.

Output: same as proteinmpnn (designed-sequence FASTA + `metrics.csv`). The ligand context is reflected in the scores but is not itself redesigned.

Gotcha: the cofactor MUST be present in the uploaded PDB as HETATM (or a separate chain for nucleic acids). Strip waters/ligands and LigandMPNN degenerates to plain ProteinMPNN behavior with no warning.

---

## esm-if1 (ESM-IF1)

Language-model inverse folding (geometric-vector-perceptron encoder + autoregressive Transformer decoder) for a SINGLE chain. A fast, lightweight alternative to ProteinMPNN.

- `pdbFile` (required, `.pdb`): the backbone. **Schema warning baked in: "make sure the indices are numbered from 1 to N."**
- `chain` (required, single chain ID): the one chain to design.
- `designedResidues` (required, `selectResidues`, RANGE string, comma-separated for multiple ranges, e.g. `62-70`): residues to redesign, scoped to the single `chain`. Format differs from the MPNN per-chain dict.
- `numSequences` (default 10).

Output: a FASTA of designed sequences for the chosen chain with per-sequence model scores.

Also a scorer: ESM-IF1 can score point-mutation variants zero-shot against the fixed backbone (per-mutation likelihoods for stability/affinity prioritization), not only generate sequences.

Numbering gotcha: ESM-IF1 expects clean 1..N numbering, the OPPOSITE of the MPNN/author-number rule. A PDB straight off the PDB or out of a cropping step often starts at a nonzero residue number, which shifts the `62-70` selection. Renumber to 1..N FIRST for esm-if1 specifically. Single-chain by construction; to inverse-fold a complex, submit one job per chain.

---

## esmc-6b (ESM-C 6B)

The largest ESM-Cambrian PLM (6 billion params), sequence-only (no MSA, no structure). Two modes.

- `task` (required, `embeddings` | `scan`): switches the output.
- `sequence` (required, `sequenceBatching:true`): the protein.
- `embeddings` mode: 2560-dim per-residue (and mean-pooled) vectors. `outputFormat` (default `pt`; `pt`/`json`), `layerPreset` (default `last`; `last`/`first`/`custom`), `layerIndex` (1-36, only when `layerPreset:custom`; the 6B stack is 36 blocks).
- `scan` mode: a per-position x 20-AA log-likelihood matrix for mutation ranking (in-silico DMS).

Output: `embeddings` -> a `.pt` (or `.json`) tensor of per-residue 2560-dim vectors plus a mean-pooled sequence vector. `scan` -> a per-position x AA log-likelihood matrix (CSV/JSON).

Gotchas: `task: scan` is a per-position LIKELIHOOD matrix, NOT a structure-conditioned ddG (use `thermompnn` / `proteinmpnn-ddg` / `rosetta-ddg-prediction` in `tamarind-developability` for fold-stability ddG). Embeddings are sequence-only: identical sequences give identical vectors regardless of structure context; use `saprot` for structure-aware tokens. The 6B model is the slow/expensive end of the family; for high-throughput scanning prefer `esmc-scan` with a smaller ESM-C size.

---

## The embeddings trio (sequence in, vectors out)

All three are sequence-only protein embedders (no MSA, no structure). Pick by the backbone you need.

### esm-embeddings (ESM2 Embeddings)

- `sequence` (required, `sequenceBatching:true`): amino-acid sequence; `:` separates multimer chains (remapped to `<cls>` by the wrapper).
- `model` (default `esm2_t33_650M_UR50D`): the full SIZE LADDER, `esm2_t6_8M_UR50D` / `esm2_t12_35M_UR50D` / `esm2_t30_150M_UR50D` / `esm2_t33_650M_UR50D` / `esm2_t36_3B_UR50D` / `esm2_t48_15B_UR50D`. Bigger = richer but more GPU/time/cost. The only one of the three with this full ladder.
- `outputFormat` (default `pt`; `pt`/`json`).
- `sequenceBatching` (default false) + `sequenceBatchSize` (both `exclude:["pipelines","batch"]`): for many sequences prefer the platform `tamarind-batch` path, which amortizes weight loading.

Output: an archive with BOTH pooled (per-sequence) and per-residue tensors. Size scales with model and count (an 8M run is small; a 15B run is large). Use small models (8M/35M) for cheap embedding at scale, large for the richest representation.

### esmc-embeddings (ESMC Embeddings)

- `sequence` (required, `sequenceBatching:true`): `:` separates multimer chains (remapped to ESM-C's native `|` at tokenization; pass `:`, NOT a raw `|`).
- `model` (default `esmc-600m`; `esmc-300m`/`esmc-600m`/`esmc-6b`): 300M/600M baked into the image, 6B loaded from shared storage (slower start).
- `outputFormat` (default `pt`; `pt`/`json`).
- `layer` (default `last`): which transformer layer to extract from (`last`/`first`/a 1-indexed integer). The only one of the three with a layer knob; useful when a downstream probe wants earlier-layer representations.
- `sequenceBatching` (default false) + `sequenceBatchSize` (default 4): both `exclude:["pipelines","batch"]`.

Output: per-sequence and per-residue tensors in `pt` or `json`. Stronger per parameter than ESM2 for downstream property/fitness tasks; native multimer handling.

### prot-t5-embeddings (Prot T5 XL Embeddings)

- `sequence` (required, `sequenceBatching:true`): the fewest knobs of the three (no `model`, no `layer`, no `outputFormat`).
- `sequenceBatching` + `sequenceBatchSize` (both `exclude:["pipelines","batch"]`).

Output: **per-residue embeddings ONLY (no pooled per-sequence vector)**, unlike ESM2 which writes both. If a downstream step needs a single per-sequence vector, mean-pool the per-residue tensor yourself; a script expecting a pooled embedding (as ESM2 gives) will misread ProtT5 output. T5's relative-position bias has no hard architectural length cap, so it tolerates long sequences better than ESM2's window; reach for it to match a ProtT5-built pipeline.

---

## Output shapes (reason about the shape, not golden numbers)

PLM and inverse-folding outputs depend on seed / model / temperature, so read the metric keys and reason about ranking, not exact values.

- **Inverse folding** -> a FASTA of designed sequences + a `metrics.csv` (ProteinMPNN score / global score / recovery; lower per-residue score is more confident for the MPNN family). Rank by score, then fold the top sequences back to verify.
- **Embeddings** -> a `.pt`/`.json` tensor archive (per-residue, plus pooled for ESM2/ESM-C; per-residue only for ProtT5). Not a "score" to rank; a feature for a downstream model.
- **Masked-LM scan** -> a per-position x AA log-likelihood matrix (CSV/JSON). Higher likelihood for a substitution = more tolerated; rank candidate mutations by the matrix.
- **Job row `Score`**: tool-specific metrics on a completed job. **`WeightedHours`**: the billing unit (weighted hours; GPU tools cost more per wall-hour than CPU tools, and the 6B/15B models are the slow/expensive end).

Download one completed small job with `tamarind --json results JOB_NAME --download DIRECTORY` and inspect the extracted paths; do not hardcode filenames, which vary by tool and version.

---

## Catalog: the rest of the bucket (one line each)

Reach for one of these when a workflow names it; run `tamarind --json schema TOOL` first because these drift.

**Inverse-folding / MPNN family**
- **`caliby`** (Caliby): SOTA ensemble/multistate inverse folding; builds a structure-conditioned Potts model (sitewise fields + pairwise couplings) and samples sequences by discrete Langevin MC, averaging energies across a structural ensemble (synthetic via partial diffusion, or user-provided). Reach for it to design over multiple structural states or to rescue native/de novo backbones ProteinMPNN fails to design; apo backbone-conditioned (for a fixed pocket ligand use `ligandmpnn`). Also packs sidechains on a backbone+sequence.
- **`fixbb`** (ColabDesign Fixed Backbone): inverse folding by reversing AlphaFold (gradient hallucination in sequence space) with optional fix-some / design-the-rest. The general-IF cross-reference named in most other IF tools' alternatives; slower than ESM-IF1/MPNN (runs an AF loop), reach for it for AF-consistent partial redesign.
- **`proteinmpnn-score`**: SCORE an existing sequence against a backbone (per-residue/global scores) rather than generate. Knobs: `pdbFile`, `sequence`, `allChains` (default true) or a single `chain`. Reach for it to rank/filter sequences you already have.
- **`protein-metrics`** (COMPSS Protein Metrics): ensemble design-FILTER scorer; runs structure-conditioned likelihoods (ESM-IF / ProteinMPNN / MIF-ST) plus sequence-only ones (ESM-1v / CARP) in one pass to triage a large library of designed sequences down to a wet-lab shortlist. Scores only (does not generate); companion to `proteinmpnn-score`.
- **`hypermpnn`**: ProteinMPNN retrained to bias toward thermostable, hyperthermophile-like sequences; when stability/Tm matters more than native recovery. Also `modelType: hypermpnn`.
- **`cyclicmpnn`**: ProteinMPNN variant for stable CYCLIC peptide sequences on a given backbone (handles wrap-around numbering); after a cyclic backbone tool gives you a structure.
- **`nampnn`** (NA-MPNN): sequence design for protein, RNA, DNA, and mixed-polymer structures plus protein-DNA binding-specificity; when the nucleic acid is itself being DESIGNED, not held as fixed context.
- **`abmpnn`** (AbMPNN): ProteinMPNN finetuned on antibodies for CDR sequence design. Also `modelType: abmpnn`. For antibody work prefer `tamarind-antibody`.
- **`ablang-mpnn`** (AbLang-MPNN): hybrid antibody design ensembling AbLang (antibody LM) with ProteinMPNN. For antibody work prefer `tamarind-antibody`.

**PLM scoring / mutational scanning**
- **`esm2`** (ESM2): ESM-2 masked LM in two modes, `mask` (fill masked residues) and `scan` (per-position x AA likelihood). For classic ESM-2 mask-filling or an in-silico DMS matching an ESM-2 pipeline.
- **`esmc-scan`** (ESMC Scan): per-position mutational scan with a selectable ESM-C backbone (`esmc-300m`/`esmc-600m`/`esmc-6b`); the cheaper / size-comparable alternative to `esmc-6b`.
- **`esm-scan`** (ESM-Scan): point-mutation scoring with the older ESM-1b baseline.
- **`amplify`** (AMPLIFY): variant scoring with the AMPLIFY protein LM; an efficient, recent masked-LM scorer.
- **`profluent-e1`** (Profluent E1): SOTA retrieval-augmented PLM; conditions on homologous sequences via block-causal multi-sequence attention to score zero-shot SINGLE-substitution mutants and run in-silico site-saturation, and emits per-residue embeddings. Outperforms ESM-2 / ESM-C at matched sizes when homologs are available; NOT for sequence generation / de novo design or multi-mutant/epistatic scoring (catalog routes those elsewhere). Pairs upstream with an MSA / MSA-Analysis homolog source.
- **`saprot`** (SaProt): structure-aware PLM (Foldseek 3Di structural-token alphabet) for property prediction (solubility, thermostability, developability); when sequence-only PLMs miss structure-dependent properties.

**Generative / family LMs**
- **`progen2-inference`** (ProGen2 Inference): samples sequences from a ProGen2 language model; built to sample from a `progen2-finetune` checkpoint (family-specific generation after finetuning on a target family / distribution).
- **`zymctrl`** (ZymCTRL): conditional generative LM for artificial enzymes (conditioned on EC number / function); candidate enzyme sequences for a target reaction class.
- **`profam`** (ProFam): protein-family language model; FIRST a zero-shot fitness / point-mutation (and indel) scorer conditioned on a set of homologs, THEN family-aware sequence generation.

**Directed evolution**
- **`evoprotgrad`** (EvoProtGrad): gradient-based directed evolution over PLM likelihood to propose improving mutations (in-silico directed evolution toward higher fitness/activity).
- **`structural-evolution`** (Structural Evolution): mutate protein COMPLEXES with a structure-informed LM (conditions on the bound partner); affinity-maturation-style mutations where the interface context matters.
- **`multi-evolve`** (MULTI-evolve): end-to-end ML-guided directed evolution; trains fully connected nets on DMS / pairwise-combination assay data (~100-200 measurements per round), nominates synergistic MULTI-mutants that capture epistasis, and generates MULTI-assembly mutagenic oligos for synthesis. Runs a zero-shot PLM ensemble for single-mutant nomination when no assay data exists yet. Reach for it to stack beneficial mutations where single-mutant scoring is insufficient.

**Evolutionary-covariance scoring**
- **`evcouplings`** (EVcouplings): unsupervised single-mutation fitness from evolutionary sequence covariation (a coupling model over an MSA). Input is just `sequence`, but it builds/downloads an MSA (MSA-dependent) and runs on CPU. For a homology-rich protein; use `esmc-6b` for MSA-free zero-shot scoring instead.
