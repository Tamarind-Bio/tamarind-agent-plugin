# Tamarind Bio: developability / stability / immunogenicity tool map

> Operational examples in this reference use the Tamarind CLI. Query the live catalog and schema before relying on this grounded snapshot.

The catalog drifts. Treat this as a starting map, not a frozen list: filter live with
`tamarind --json tools --function developability` (narrower facets exist as function tags:
`thermostability`, `aggregation`, `solubility`, `immunogenicity`, `humanization`,
`point-mutations`, `mutation-scoring`, `protein-language-models`), read each candidate's
`description`, then run `tamarind --json schema NAME` for the exact parameters. Pass the
lowercase tool `name` (e.g. `aggrescan3d`), not the display name.

## Picking the right developability tool

These tools are **filters on a hit list**, not generators. Match the input you have to the
axis you want to filter on, in this order:

1. **What input do you have?** A folded **structure** -> the structure-aware scorers
   (`aggrescan3d`, `thermompnn`, `thermompnn-d`, `proteinmpnn-ddg`, `rosetta-ddg-prediction`).
   Only a **sequence** -> the PLM/compositional scorers (`netsolp`, `protein-sol`, `saprot`,
   `temstapro`, `deepstabp`, `tap`, `tnp`, `deepsp`, `deep-viscosity`, `polyxpert`,
   `n-linked-glycosylation`, `deepimmuno`, `tlimmuno`). Don't fold a structure just to score
   solubility if a sequence model answers it. (`stabddg` also needs a structure but scores
   protein-protein BINDING ddG, not developability; it lives in `tamarind-docking`.)
2. **Which axis?** Thermostability/Tm, aggregation, solubility, viscosity, polyreactivity,
   glycosylation, or immunogenicity. One tool per axis below.
3. **What format is the molecule?** General protein -> the general scorers. **Paired antibody
   (VH+VL)** -> `tap` (full scorecard) + `deepsp`/`deep-viscosity`/`polyxpert`. **Single-domain
   nanobody/VHH** -> `tnp` (and the VHH-specific siblings). The TAP-vs-TNP split below is the
   most common mis-pick.

## TAP vs TNP: paired antibody vs single-domain VHH

The platform has two antibody developability profilers and they are NOT interchangeable:

- **`tap` (TAP2, Therapeutic Antibody Profiler)** - for a **paired antibody** (heavy AND light
  chain). Requires BOTH `heavySequence` and `lightSequence`; an empty chain is rejected.
- **`tnp` (TNP, Therapeutic Nanobody Profiler)** - for a **single-domain nanobody/VHH** (heavy
  only). Takes ONE `sequence`.

Paired (VH+VL) -> `tap`; single-domain VHH -> `tnp`. The wrong profiler returns a meaningless
score, not an error, so confirm the format before picking. The antibody aggregation/viscosity
tools (`deepsp`, `deep-viscosity`) and polyreactivity (`polyxpert`) are also paired
heavy+light; the nanobody analogs are separate tools (filter live by `modality=antibody`).

## Thermostability / stability (ddG, Tm) - `function=thermostability` / `point-mutations`

| Tool | Use it for | Input |
|---|---|---|
| `thermompnn` | **Deep.** Propose ranked **single** stabilizing point mutations (predicted ddG) from a structure. | `pdbFile` + `chains` (list, or `allChains`) + `topK` |
| `thermompnn-d` | Propose stabilizing **double** mutations; `model` = `epistatic`/`additive`/`single`, with distance + threshold filters. | `pdbFile` + `chains` + `model` |
| `proteinmpnn-ddg` | Unsupervised **fold-stability ddG saturation scan** (every position) on a monomer/multimer structure, ProteinMPNN-based. Stability, NOT binding. | `pdbFile` + `chains` (+ `topK`) |
| `rosetta-ddg-prediction` | **Physics-based** (Rosetta) ddG-of-folding on a **monomer**; high-throughput stability scan when a Rosetta-grounded estimate is preferred. | `pdbFile` + `saturationMutagenesis` + `mutations` or (`positions` + `residueTypes`) |
| `saprot` | Structure-aware PLM scoring **intrinsic stability** + binary solubility (#1 on ProteinGym DMS). Takes a `sequence` (no structure needed) or a structure. | `inputType` + `properties` + `sequence` or `pdbFile` |
| `temstapro` | Sequence-only thermostability call (PLM), no structure. | `sequence` |
| `deepstabp` | Predict **melting temperature (Tm)** from sequence. | `sequence` (+ `growthTemp`, `measurementCondition`) |

`thermompnn` / `thermompnn-d` PROPOSE stabilizing mutations; `proteinmpnn-ddg` and
`rosetta-ddg-prediction` saturation-SCAN every position for **fold-stability** ddG. For a numeric
Tm with no mutation work, `deepstabp` (Tm) or `temstapro` (thermostability call); `saprot` gives a
quick sequence-only stability + solubility triage. All of these are **fold / monomer stability**.
`stabddg` is different: it scores protein-protein **binding** ddG for interface mutations on a
complex and lives in `tamarind-docking` (see Cross-references), NOT here. `rosetta-ddg-prediction`
mutations are `chain.wt.pos.mut` (e.g. `A.V.1.K`), newline-separated, commas for a multi-point
entry; toggle `saturationMutagenesis: true` to scan `positions` x `residueTypes` instead.

## Aggregation / viscosity - `function=aggregation`

| Tool | Use it for | Input |
|---|---|---|
| `aggrescan3d` | **Deep.** Structure-aware, per-residue aggregation (A3D score on the 3D surface). Accepts a multi-chain complex. | `pdbFile` |
| `deepsp` | Antibody **viscosity + SCM + SAP** from the paired heavy+light sequence. | `heavySequence` + `lightSequence` |
| `deep-viscosity` | Antibody **viscosity** from the paired heavy+light sequence. | `heavySequence` + `lightSequence` |

Note: the platform `apm` (All-Atom Protein Generative Model) is a **design** tool, NOT an
aggregation scorer - don't reach for it to "map aggregation". For sequence-only aggregation /
amyloid, filter live (e.g. an amyloid-nucleation model); for structure-aware aggregation use
`aggrescan3d`.

## Solubility - `function=solubility`

| Tool | Use it for | Input |
|---|---|---|
| `netsolp` | **Deep.** Sequence-only solubility + usability (PLM), 0-1 scores. The fast expression pre-screen. | `sequence` |
| `protein-sol` | Sequence-only solubility via compositional features (alternative method). Needs sequences of at least 21 residues. | `sequence` |

For structure-aware solubility design, route to `aggrescan3d` (it surfaces the aggregation
patches you'd redesign away).

## Therapeutic peptides - `function=developability`

| Tool | Use it for | Input |
|---|---|---|
| `peptiverse` | Unified therapeutic-peptide developability (hemolysis, solubility, non-fouling, cell penetrance, toxicity) + serum half-life + PAMPA/Caco-2 permeability + optional peptide-protein binding. | `inputType` (`wt`/`smiles`) + `sequence` or `smilesInput` (+ optional `targetSequence`) |

The `smiles` path (`smilesInput`) handles cyclic / non-canonical peptides that sequence-only
protein models can't score; pass a `targetSequence` to also get a peptide-protein binding-affinity
class. For a standard protein hit list use the general scorers above, not PeptiVerse.

## Polyreactivity / non-specific binding - `function=developability`

| Tool | Use it for | Input |
|---|---|---|
| `polyxpert` | Antibody (paired) polyreactivity classifier. | `heavyChain` + `lightChain` (Fv sequences) |

Mind the param names: `polyxpert` uses `heavyChain` / `lightChain`, NOT the
`heavySequence`/`lightSequence` that `tap`/`deepsp`/`deep-viscosity` use.

## Glycosylation - `function=developability`

| Tool | Use it for | Input |
|---|---|---|
| `n-linked-glycosylation` | Predict N-linked glycosylation **sequon sites** (N-glyco motifs that affect manufacturability / heterogeneity). | `sequence` |

## Immunogenicity - `function=immunogenicity`

| Tool | Use it for | Input |
|---|---|---|
| `deepimmuno` | Predict immunogenic epitopes for **T-cell immunity (Class I / CD8)**; the top result from every 9-mer is returned. | `sequence` (+ optional `hlas` HLA-allele panel, `HLA-A*`-style, all by default) |
| `tlimmuno` | Predict **MHC class II / CD4** peptide immunogenicity (TLimmuno2); scans sliding-window peptides (default length 15) against HLA-II alleles. The Class-II counterpart to `deepimmuno`. | `sequence` + `hlas` (`DRB1_*`/`DQ`/`DP`-style) (+ optional `peptideLength`) |

## Antibody / nanobody developability profilers (TAP family)

| Tool | Use it for | Input |
|---|---|---|
| `tap` | **Deep.** Paired-antibody one-shot developability scorecard (TAP2). | `heavySequence` + `lightSequence` |
| `tnp` | Nanobody/VHH developability profiler (TNP); the single-domain analog of `tap`. | `sequence` |

## Cross-references (these live in OTHER skills)

- **Designing or generating the molecule** (`rfdiffusion` / `boltzgen` / `bindcraft` /
  `rfantibody` / `igdesign`): `tamarind-binder-design` and `tamarind-antibody`. Developability
  is the FILTER you run on those designs' output.
- **Humanization** (`humatch` / `biophi` - humanness scoring + humanization, a developability-
  adjacent axis for antibodies): they live under `function=humanization` and are surfaced in
  `tamarind-antibody`.
- **Folding / co-folding** to get a structure for the structure-based scorers (`boltz` / `chai`
  / `protenix` / `alphafold` / `immunebuilder`): `tamarind-structure-prediction` and the
  antibody structure tools in `tamarind-antibody`.
- **Binding affinity and docking** (`prodigy` / `autodock-vina` / `diffdock`):
  `tamarind-docking`. `stabddg` (StaB-ddG) belongs there too: it scores protein-protein
  **binding** ddG for interface mutations (affinity maturation), NOT fold stability, so reach for
  it from the docking skill; absolute affinity prediction also lives there.
- **Inverse folding on a backbone** (`proteinmpnn` + the soluble/thermostable MPNN variants):
  `tamarind-inverse-folding` (a designer can bias toward solubility/thermostability up front).

## Deep-tool gotchas (the non-obvious behaviors)

### tap / tnp
- **`tap` requires BOTH `heavySequence` and `lightSequence`** - it folds the paired Fv first.
  A single chain is rejected. **`tnp` takes ONE `sequence`** (the VHH). Wrong tool for the
  format = a meaningless score, not an error.
- Disulfides are detected STRUCTURALLY on the predicted structure, with the conserved
  framework cysteine pair whitelisted; a genuine free cysteine elsewhere still flags as an
  unpaired-cysteine liability.

### thermompnn / thermompnn-d
- **`chains` is a LIST** (`["A"]`), required unless `allChains: true`. Indexing `[0]` silently
  scopes to one chain on a multi-chain input.
- **`verify`** (auto-fold designs with AlphaFold) is UI-only and ignored by CLI submission.
  Leave it out.
- Reconstruct a mutated sequence from the CSV columns (`wildtype` + `position` + mutant), not
  by re-parsing the PDB, to survive gap-filled / non-contiguous numbering.
- `thermompnn-d` `model`: `epistatic` runs inference on every single mutation (slower, captures
  coupling); `additive` sums single contributions; default `threshold` only saves mutations
  below -0.5 kcal/mol (set high, e.g. 100, to save all).

### stabddg (a binding-ddG tool; primary home `tamarind-docking`)
- Scores protein-protein **binding** ddG (SKEMPIv2-trained, SOTA) for **interface** mutations on
  a wild-type complex, NOT fold/monomer thermostability. Documented here only because it's
  developability-adjacent (affinity maturation); its home skill is `tamarind-docking`.
- Mutation format is `wildtype+chain+position+mutant` (e.g. `EA63Q` = E->Q at position 63 of
  chain A), using your submitted PDB's numbering; it renumbers each chain to start at 1 and
  reports the renumbered mutation alongside the result. `binder1Chains` / `binder2Chains` define
  the interface.

### aggrescan3d
- `pdbFile` is the only param; it accepts a **complex**, scoring aggregation in the assembled
  context, not just a monomer. Structure-only (no sequence mode) - route sequence-only
  aggregation elsewhere.

### protein-sol
- **Minimum 21 residues** - a shorter sequence is rejected. For very short peptides use a
  different solubility/aggregation method.

### deepimmuno
- Returns the highest-scoring result from every 9-mer in the input `sequence`. The `hlas` panel
  defaults to all alleles; narrow it to the relevant HLA set for a targeted read.
