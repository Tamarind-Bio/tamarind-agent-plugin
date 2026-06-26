# Tamarind Bio: antibody and nanobody tool map

The catalog drifts. Treat this as a starting map, not a frozen list: filter live with
`getAvailableTools(modality="antibody", function=<tag>)`, read each candidate's
`description`, then `getJobSchema(<name>)` for the exact params. Pass the lowercase tool
`name` (e.g. `rfantibody`), not the displayName.

## Picking the right tool (the antibody decision)

Match the user's INTENT to the input you have and the output you need, in this order:

1. **What input do you have?** Antigen structure only (no antibody yet) -> de novo design
   (`rfantibody` / `mber` / `mage`). An antibody-antigen complex -> CDR redesign conditioned
   on the antigen (`igdesign`). An antibody backbone alone -> inverse folding (`abmpnn` /
   `antifold` / `antidif` / `ablang-mpnn`). Just a sequence -> structure prediction
   (`immunebuilder` / `abodybuilder` / `nbforge`) or numbering (`anarci`).
2. **Do you want to GENERATE new loops or RESEQUENCE existing ones?** Generate backbones +
   loops de novo -> `rfantibody`. Resequence CDRs on a fixed backbone -> the inverse folders.
3. **Antibody-specific, or generic?** See the caution below. A generic task on an antibody
   input is often better served by a generalist (cofolder / general binder designer / plain
   ProteinMPNN) than by a niche antibody-only tool.

### Don't keyword-match a pure-antibody tool over the established generalist

A tool having "antibody" in its name does not make it the right pick. Common over-reaches:

- **Antibody-antigen complex structure** -> use a cofolder (`boltz` / `chai` / `protenix`,
  in `tamarind-structure-prediction`). `protenix` reports major antibody-antigen interface
  gains. The antibody-only structure predictors (`immunebuilder`, `abodybuilder`, `nbforge`)
  model the variable domain WITHOUT the antigen; reach for them only when you don't need the
  complex.
- **A binder against a target that's an antibody** -> `rfdiffusion` / `boltzgen` / `bindcraft`
  (`tamarind-binder-design`). `boltzgen` and `promera` span nanobodies/antibodies AND general
  binders in one model, so you may not need a dedicated antibody designer at all.
- **Inverse folding with no CDR-specific intent** -> plain `proteinmpnn` (with
  `modelType: "abmpnn"`) from `tamarind-inverse-folding` may suffice; the dedicated `abmpnn`
  tool is for when you want antibody CDR detection built in.

When the user names a specific tool, evaluate it AND sanity-check its `tag`-group siblings -
a faster or more appropriate one often exists. Let `validateJob` confirm a candidate accepts
your input before committing.

## De novo / generative design (`function=antibody-design` / `binder-design`)

| Tool | Use it for |
|---|---|
| `rfantibody` | **Deep.** De novo CDR-loop generation against an epitope on a known antigen structure (RFdiffusion -> ProteinMPNN -> RF2). Control framework, which CDRs, hotspots, lengths. |
| `mber` | VHH (nanobody) de novo binder design; lighter-weight nanobody alternative to rfantibody. |
| `mage` | De novo antibody generation from antigen SEQUENCE (language models) - use when you have the antigen sequence but no structure. |
| `evonb` | Mutate/optimize nanobody sequences with a VHH language model; supports finetuning. Affinity maturation for nanobodies. |
| `antibody-diffusion-properties` | Property-aware CDR sequence/structure design via diffusion; CDRs optimized toward a target property, not just binding. |
| `abgpt` | Generative antibody-sequence language model; sample novel BCR heavy/light sequences UNCONDITIONALLY from an N-terminal seed motif (no antigen conditioning, no scoring). |
| `lichen` | Generate light-chain sequences conditioned on a given heavy chain; pairing / light-chain design. |
| `germinal` | **SOTA.** Epitope-targeted de novo nanobody (VHH) / scFv design from a target structure: ColabDesign hallucination -> AbMPNN CDR redesign -> cofolding filter. Also surfaces under binder-design. |
| `iggm` | Joint CDR-sequence + antibody-antigen complex co-design against a target antigen; epitope-specific when epitope residues are given (ICLR 2025). |
| `nos-inference` | Property-guided discrete-diffusion antibody generation (NOS): finetune on paired heavy/light sequences with numeric property labels, then infill `[MASK]` positions toward that property (expression yield, affinity). The generate half of the `nos` finetune pair. |
| `adapt` | Structure-based TCR / TCR-mimic antibody design against a peptide-MHC (pMHC) target (AF2 conformational sampling + ProteinMPNN). For pMHC immunotherapy targets, not general non-pMHC antigens. |

## Inverse folding - resequence an existing backbone (`function=inverse-folding`)

| Tool | Use it for |
|---|---|
| `igdesign` | **Deep.** Wet-lab-validated CDR redesign on an antibody-antigen COMPLEX, conditioned on the antigen (and optionally the light chain). Strongest "redesign CDRs on an existing complex" pick. |
| `abmpnn` | **Deep.** Fast antibody-aware inverse folding from a backbone (ProteinMPNN fine-tuned on antibodies). Auto CDR detection. The antibody analog of plain `proteinmpnn`. |
| `antifold` | AntiFold model - design sequences for antibodies. |
| `antidif` | Antibody inverse folding (diffusion-based). |
| `ablang-mpnn` | Hybrid antibody design using an AbLang + ProteinMPNN ensemble. |

## Structure / conformation (`function=structure-prediction`)

| Tool | Use it for |
|---|---|
| `immunebuilder` | **Deep.** Fastest sequence-to-structure of an Fv / VHH / TCR, no MSA, seconds. The lightweight default. |
| `abodybuilder` | ABodyBuilder3 - refined antibody-only structure prediction. |
| `flashabb` | FlashABB - fast antibody structure + developability + embeddings in one pass (one-shot triage). |
| `nbforge` | Nanobody structure prediction with HCDR3 blueprint + disulfide priors; pick when VHH loop disulfide topology matters. |
| `abb4` | ABB4-STEROIDS - antibody conformational ENSEMBLE (takes VH+VL). |
| `its-flexible` | Predict conformational flexibility of antibody/TCR CDR3 loops. |
| `tcrmodel2` | **TCRModel2.** TCR-peptide-MHC COMPLEX prediction (and unbound TCR Fv) where vanilla AF-Multimer fails on docking orientation / CDR3 loops. immunebuilder models the TCR Fv alone; this does the pMHC complex. |

For the antibody-antigen COMPLEX (not the antibody alone), use the cofolders in
`tamarind-structure-prediction` (`boltz` / `chai` / `protenix`).

## Affinity / sequence optimization + naturalness scoring (`function=affinity-optimization`)

| Tool | Use it for |
|---|---|
| `ablang` | **AbLang2 (SOTA).** Antibody-specific LM: score VH/VL naturalness (per-residue + sequence likelihood), suggest non-germline CDR/framework mutations, restore masked residues, emit antibody embeddings, filter designs for naturalness. Likelihood is not affinity (rank binding with the developability ddG tools). Paired TCR scoring via the TCRLang weights. |
| `antibody-evolution` | Language-model mutation recommendations to raise binding affinity (point mutations). |
| `antiberty` | Optimize antibody/nanobody sequence affinity with the AntiBERTy LM. |
| `balm-paired` | Score point mutations with the BALM-paired (heavy+light) language model. |
| `cosine` | Evolve antibody sequences along realistic affinity-maturation trajectories. |

## Humanization (`function=humanization`)

| Tool | Use it for |
|---|---|
| `humatch` | Humatch - humanization evaluation + mutation recommendation. |
| `biophi` | BioPhi - OASis/Sapiens humanness scoring + humanization evaluation + mutation recommendation. |

## Numbering / annotation / search (`function=utilities`)

| Tool | Use it for |
|---|---|
| `anarci` | ANARCI - the canonical CDR/framework numbering utility (number/annotate immune proteins). |
| `igblast` | IgBLAST - germline assignment; searches immune proteins against public DBs from nucleotide or AA. |
| `antibody-annotation` | Annotate CDRs/regions (numbering sibling of anarci). |
| `oas` | OAS Search - find similar sequences in the Observed Antibody Space paired database. |
| `plabdab` | PLAbDab - search antibody sequences from patents + literature (prior-art / known-binder lookup). |
| `space2` | SPACE2 - cluster antibodies by structural similarity to group same-epitope binders (epitope binning). |

## Paratope / interface / affinity

| Tool | Use it for |
|---|---|
| `paragraph` | Predict antibody paratopes from heavy-chain structures. |
| `parasurf` | Predict paratope residues (surface-based). |
| `p2pxml` | Predict antibody-antigen binding affinity (IC50) from structures. |
| `dsmbind` | Predict antibody-antigen binding affinity. |
| `deeprank-ab` | Score and rank antibody-antigen complex models by predicted DockQ. |

## Cross-references (these live in OTHER skills)

- **Developability filters** (`tap` TAP2 for paired antibodies, `tnp` TNP for nanobodies,
  `tempro` thermostability, `nanobody-polyreactivity` / `polyxpert`, viscosity, aggregation,
  `deepimmuno` / `tlimmuno` immunogenicity): **`tamarind-developability`**. Run as filters on
  a hit list after design. TAP vs TNP = paired antibody vs single-domain VHH.
- **Cofolders for the antibody-antigen complex** (`boltz` / `chai` / `protenix`):
  **`tamarind-structure-prediction`**.
- **General non-antibody binder design** (`rfdiffusion` / `boltzgen` / `bindcraft`):
  **`tamarind-binder-design`**.
- **Generic inverse folding / PLMs** (`proteinmpnn`, the ESM family):
  **`tamarind-inverse-folding`**.

## Deep-tool gotchas (the non-obvious behaviors)

These are the things the schema doesn't spell out for the four canonical tools.

### rfantibody

- **Multi-chain antigens are concatenated into one continuous target** with absolute
  1-indexed numbering internally. You pass `hotspots` in the ORIGINAL chain+resnum form
  (`{"A": "305, 456"}`) and the wrapper remaps them. An unmatched hotspot residue is
  rejected with a clear error telling you which residue/chain is wrong.
- **Capping groups are auto-stripped.** ACE/NMA/NME caps (from Schrodinger Prep or an MD
  frame export) are removed automatically, so a capped PDB is handled, not rejected.
- **Named frameworks need no upload.** `hu-4D5-8_Fv` / `h-NbBCII10` are fetched server-side;
  `heavyChain`/`lightChain` are forced to `H`/`L` for them. Only `framework=custom` needs
  `antibodyFile` + your chain IDs.
- **Custom-CDR residue numbers are ORIGINAL PDB numbers**, not 0-indexed - don't pre-convert.
- `numDesigns` recommendation: ~10,000 in silico, ~100-10,000 wet-lab. `numDesigns` batches
  automatically (tiers of 10 up to 49 total, else 64/batch).

### igdesign

- **CDR residue selections are treated as IMGT positions.** If you hand-pick CDRs
  (`selectCDRIndices`), the input PDB must already be IMGT-numbered, or the selection
  mis-targets. By default CDRs are IMGT-numbered automatically; a generic 1-indexed renumber
  before submitting would silently mis-target, so don't.
- **A single `antigenChain`** (singular), unlike rfantibody's `antigenChains` list.
- **1000 designs per batch** - start with `numBatches: 1`, `regions: ["hcdr3"]` for a first
  pass; the full 6-CDR run is a lot of compute.
- Bound small molecules in the input complex are stripped/cleaned automatically.

### abmpnn

- **`designedChains` is `exclude: ["api"]`** and **`verifySequences` is
  `exclude: ["api", "pipelines", "batch"]`** - both are UI-only and silently dropped over the
  API/MCP. The API shape is `pdbFile` + `designedResidues` (per-chain, space-separated
  resnums) with `detectCDRs: false`, OR `detectCDRs: true` + `regions`.
- For a nanobody (single chain) the light-chain CDRs are simply skipped.
- **Cysteine is omitted by default** (`omitAAs: "C"`) - override only if you intentionally
  want disulfides.

### immunebuilder

- **Sequence-only, no file** - fully runnable via `submitJob` with inline text, validates
  fast. `modelType` maps to ABodyBuilder2 / NanoBodyBuilder2 / TCRBuilder2.
- For `Nanobody`, only `sequence1` is used; `sequence2` is ignored (drop it).
- Sequences are sanitized to letters only, so stray whitespace/numbers are tolerated.
