# Tamarind structure-prediction tools

Per-tool detail for the folders this skill covers. `getJobSchema(<tool>)` is the authority for required fields, options, bounds, and version-gating; this file captures when-to-pick and the gotchas the schema does not spell out. Schemas evolve, so re-fetch if a payload stops validating. Filter the live catalog with `getAvailableTools(function="structure-prediction")`.

A note that applies to every file-typed param below (`templateFiles`, `a3mFiles`, `yamlFile`, `initialGuess`): reference an uploaded file by its **bare filename** (e.g. `template.cif`), never an email-prefixed S3 key. Upload first, then pass the returned bare name. A raw string in a file param is treated as inline file CONTENT, not a reference. See `tamarind-submit-and-poll/references/api_reference.md`.

---

## boltz (Boltz-2)

Predict a biomolecular complex (proteins + nucleic acids + small-molecule ligands together) and, optionally, its small-molecule binding affinity. An open AlphaFold3-class cofolding model, so it is the default when a ligand, DNA/RNA, or a protein-protein interface is in play, not just a single chain.

Pick boltz when:
- You want protein + small-molecule cofolding AND a binding-affinity number. `predictAffinity:true` (gated on `version:"2.2.1"`) is unique to boltz in this bucket.
- For a plain single-chain monomer with no ligand, `alphafold` or `esmfold2` is faster and cheaper.
- For antibody-antigen interfaces specifically, `protenix` reports stronger results.
- `chai` is the sibling AF3 reproduction with the same complex scope but no affinity head; run it for a consensus second opinion or its glycan support.

Schema highlights (from `getJobSchema`):
- Required: `inputFormat` (`"sequence"` | `"list"` | `"molecules"` | `"yaml"`; the UI exposes `sequence` and `yaml`). For `inputFormat="sequence"`, `sequence` is required (`:` separates chains). For `yaml`, `yamlFile` (`.yaml`/`.yml`) is required.
- Ligands: `addLigands:true`, then `ligands` (list; each entry a bare CCD code or a SMILES string, `:`-separated to put multiple in one prediction). DNA/RNA via `addDNA`/`addRNA` + `dna`/`rna`, or as `proteins`/`dnas`/`rnas` lists in `list` mode.
- Affinity: `predictAffinity:true` (needs `version:"2.2.1"`). `binderChain` optionally overrides which chain affinity is scored for; it defaults to the ligand's chain, and chains are assigned in input order (2 proteins + 1 ligand makes the ligand chain C).
- Sampling: `numSamples` (default 5, up to 200), `numBatches` (parallel batches, default 1), `numRecycles` (default 3), `stepScale` (default 1.638; lower = more diversity), `seed`.
- Restraints / advanced: `pocketRestraints`, `contactRestraints`, `bonds` (covalent), `modifications` (PTMs), `cyclicPeptide`, `usePotentials` (inference-time physical potentials), `method` (condition on an experimental method).
- MSA: `useMSA` (default true), `msaDatabase` (`uniref` | `swissprot` | `uniref+swissprot`), `maxMsaSeqs`. Precomputed MSA: `a3mFiles` (`.a3m`) + `a3mMapping` (`a3mName` -> `boltzChainID`). Custom templates: `templateFiles` (`.cif`) + `templateMapping`. These file/template/a3m params are gated on `version:"2.2.1"`.
- `version` (default `2.2.1`; also `1.0.0`, `0.4.0`), `outputType` (`pdb` | `mmcif`), `runIpsae` (default true; IPSAE interface metrics for protein-protein complexes).

Gotchas:
- `chooseBest` is pipeline-only (`exclude:["api","batch","tools"]`); do not pass it over the API.
- A precomputed a3m is matched to a chain by its QUERY SEQUENCE (the a3m's first sequence must equal that chain's sequence), not by filename; you still map files to chains explicitly with `a3mMapping`. MSA generation is skipped for any chain you supply an a3m for.
- `useBoltzServer` and `predictProteinAffinity` (protein-protein affinity on the hosted server) are gated behind a feature flag and are not generally available to external API users. Do not rely on them; for small-molecule affinity use `predictAffinity` on the standard tool.

Output: predicted structures (PDB or mmCIF per `outputType`), per-model confidence (pLDDT/pTM/ipTM), a `-scores.csv` (all models) plus a best-model CSV, IPSAE metrics when `runIpsae`, and an affinity score when `predictAffinity` is on. Multi-sample jobs rank models by confidence.

---

## alphafold (AlphaFold / ColabFold)

Predict a protein monomer or multimer from sequence with the ColabFold (AlphaFold2) pipeline: MSA, optional templates, recycling, and optional Amber relaxation. This is the AF2-specific path, NOT the general default. For new proteins-only work the AF3-class `boltz` is the platform default (AF2 is superseded for most new prediction), so reach for alphafold only when you specifically need AF2/ColabFold weights or behavior.

Pick alphafold when:
- You specifically need AF2/ColabFold weights: reproducing AF2 results, matching an AF2-trained downstream model, full MSA + template control, tuned recycles / MSA depth, an `initialGuess` refine, or an AF2-dependent pipeline (e.g. AF2-based hallucination, EvoPro AF2+ProteinMPNN evolution). For general-purpose new proteins-only prediction prefer the AF3-class `boltz`. alphafold does NOT handle small-molecule ligands or nucleic acids; for those use `boltz`/`chai`/`protenix`/`esmfold2`.
- For a fast, MSA-free single-sequence fold, use `esmfold2` or `omegafold`.
- For conformational ensembles, use the AF-derivative family (`af-traj`, `afcluster`, `af2rave`, `alphaflow`, `afsample`).
- For very large complexes assembled from pairwise predictions, use `combfold`.

Schema highlights:
- Required: `sequence` (amino acids, `:`-separated for multimer chains, up to 5000 residues). No separate multimer flag; chain count drives it.
- `numModels` (string dropdown `"1"`-`"5"`, default `"5"`), `numRecycles` (0-20, default 3), `numRelax` (Amber-relax N models, 0-5, default 0).
- MSA: `useMSA` (default true; off = single-sequence mode), `pairMode` (`paired`/`unpaired`/`unpaired_paired`), `msaDatabase`, `maxMsa` (cluster:extra-seq presets like `508:2048`; lower to add uncertainty), `logan` (BFVD Logan MSA).
- Templates: `templateMode` (`pdb100` default | `custom` | `none`); `templateFiles` (`.cif`, list, gated on `templateMode:"custom"`); `bfvdTemplates` (gated on `templateMode:"pdb100"`).
- `initialGuess` (`.pdb`/`.cif`): seed atom positions instead of a random start (ColabFold `--initial-guess`), useful for refining a known or designed structure.
- `modelType` (`auto` default -> `alphafold2_ptm` for monomer, `alphafold2_multimer_v3` for complex; also explicit AF2 multimer versions, `deepfold_v1`), `randomSeed`, `recycleEarlyStopTolerance`, `ipsaeScoring`.

Gotchas:
- `chooseBest` is pipeline-only (`exclude:["api","batch","tools"]`); do not pass it over the API.
- Templates are only applied when the template input is non-empty; an empty template set is skipped silently.

Output: ranked PDB models (rank_001 = best), per-residue pLDDT, PAE arrays/plots, pTM/ipTM, MSA coverage plots, a scores CSV.

---

## esmfold2 (ESMFold2)

Fast structure prediction for proteins and protein/DNA/RNA/ligand complexes from a language-model folding trunk: the pick when you want a quick fold without waiting on MSA generation. Two variants, full ESMFold2 (48 folding layers + MSA encoder) and ESMFold2-Fast (24 layers, no MSA, ~1.7x faster).

Pick esmfold2 when:
- Speed matters: single-sequence or shallow-MSA folding that returns quickly. Use `model:"esmfold2-fast"` for the fastest path and smaller GPUs (slight accuracy trade-off, ~3% DockQ on antibody-antigen per the upstream paper).
- It does support small-molecule + nucleic-acid complexes via `inputFormat:"molecules"`, overlapping boltz/chai there, but for the highest-accuracy ligand/affinity work prefer `boltz` (affinity) or `protenix` (antibody-antigen).
- For the original single-sequence ESMFold (older, protein-only), `esmfold` is the predecessor; esmfold2 supersedes it for most uses.
- Length cap: total length across chains is 2000 residues; longer inputs OOM the folding trunk. For larger single chains, `alphafold` (5000 cap) is the path.

Schema highlights:
- `inputFormat` (`sequence` default | `molecules` | `yaml`).
- `sequence` (required for `sequence` mode; `:`-separated chains; up to 2000 residues).
- `molecules` (required for `molecules` mode; list of `{type, sequence, chain}`; ligands take a SMILES or CCD code in `sequence`). `yamlFile` for `yaml` mode.
- `model` (`esmfold2` default | `esmfold2-fast`).
- MSA: `useMSA` (default true; only applies to full esmfold2), `msaMaxDepth` (default 1024, 0 = no cap; gated on `useMSA` + full model). `esmfold2-fast` force-disables MSA, so `useMSA`/`msaMaxDepth` are ignored for the fast variant.
- `numLoops` (recycling loops, default 3, 1-20; paper uses 10), `diffusionSteps` (default 14, 1-200; paper uses 68), `numSamples` (default 1), `seed`.
- `outputType` (`pdb` default | `cif`), `modifications` (PTMs), `saveRawTensors` (PAE/distogram/coordinate `.pt` files, off by default; can be 100 MB to GBs per sample).

Output: one PDB (or CIF) per diffusion sample plus a confidence JSON per sample; optional raw tensors when `saveRawTensors`.

---

## protenix (Protenix-v2)

Predict protein / nucleic-acid / small-molecule complexes with an AlphaFold3-class model, notable for strong antibody-antigen interface accuracy. The pick when the headline target is a hard interface or a restraint-guided complex.

Pick protenix when:
- The target is an antibody-antigen complex or another difficult interface, where it reports major gains over AF3-class baselines.
- For protein-small-molecule cofolding where you also want affinity, use `boltz` (protenix has no affinity head).
- For a second AF3-reproduction model to consensus against, `chai`, `openfold`, `intfold`, `rf3` are the siblings.
- It supports pocket/contact/covalent restraints natively (use the constraint model variant for pocket/contact restraints).

Schema highlights:
- Required: `inputFormat` (`sequence` default | `list`). `sequence` required in `sequence` mode (`:`-separated chains, up to 2048 residues). `list` mode uses `proteins`/`rnas`/`dnas` lists.
- Ligands: `addLigands:true`, then `ligands`. Protenix prefixes CCD codes with `CCD_` (e.g. `CCD_ATP:CCD_MG`), or pass raw SMILES; `:`-separated for multiple.
- Sampling: `numSamples` (default 5, up to 100), `numBatches` (default 1, up to 1000), `numRecycles` (default 10), `seed`.
- `useTemplate` (PDB search; gated off for the two `*_v0.5.0` models), `useGuidance` (training-free physics-aware guidance for ligand plausibility, chirality/planarity/stereochemistry; raises compute, best for ligand jobs).
- Restraints: `pocketRestraints`, `contactRestraints`, `covalentRestraints`, `restraintsMinDistance`/`restraintsMaxDistance`.
- `model` (`protenix-v2` default, 464M params; `protenix_base_20250630_v1.0.0` (2025 data), `protenix_base_constraint_v0.5.0` (supports pocket/contact restraints), plus the v1.0.0/v0.5.0 default variants). Use the constraint model when applying pocket/contact restraints.

Gotchas:
- Ligands use the `CCD_<code>` prefix (distinct from boltz's bare CCD codes), so a ligand value is not portable from boltz to protenix.

Output: predicted complex structures (CIF), per-sample confidence (pLDDT/pTM/ipTM), a scores CSV; ranked across samples.

---

## chai (Chai-1)

Predict protein / nucleic-acid / small-molecule (and glycan) complexes with an AlphaFold3-reproduction model. A solid general cofolding choice, with the option to skip MSA and use a language-model embedding for ~90% of the accuracy at lower latency.

Pick chai when:
- General complex prediction including glycans (its `molecules` type list uniquely includes `glycan`), or as a second AF3-class model alongside boltz/protenix for consensus.
- For binding affinity, use `boltz` (chai has no affinity head).
- For antibody-antigen interfaces, prefer `protenix`.
- The `useMSA:false` mode (language-model statistics instead of a real MSA) is chai's fast lane: quick complex prediction at ~90% accuracy.

Schema highlights:
- Required: `inputFormat` (`sequence` default | `molecules` | `list`). `sequence` required in `sequence` mode (`:`-separated chains, up to 2048 residues). `molecules` mode supports `protein`/`ligand`/`dna`/`rna`/`glycan` entity types.
- Ligands: pass `ligands` directly (list of SMILES, `:`-separated for multiple); chai has no `addLigands` param to gate on (unlike boltz/protenix).
- MSA: `useMSA` (default true; false = ESM language-model embedding, faster), `msaDatabase`, `logan` (BFVD Logan MSA).
- Templates: `pdb100Templates` (gated on `useMSA`), `templateFiles` (`.cif`; gated on `pdb100Templates:false`) + `templateMapping` (`templateName`/`chaiChainID`/`templateChainID`).
- Restraints: `pocketRestraints`, `contactRestraints`, `covalentRestraints`, `restraintsMinDistance`/`restraintsMaxDistance`. `modifications` (PTMs, molecules mode).
- Sampling: `numSamples` (default 5, up to 200; processed in batches of 5), `numTrunkSamples` (default 1, up to 20; total structures = numTrunkSamples x numSamples), `numBatches` (default 1), `numRecycles` (default 3), `seed`.

Gotchas:
- Custom-template chain mapping is required when using `templateFiles` (fill in `templateMapping`), and `templateFiles` is gated on `pdb100Templates:false`.

Output: predicted complex structures (CIF), per-sample confidence (aggregate + per-residue), a scores CSV; ranked across the numTrunkSamples x numSamples set.

---

## msa (Multiple Sequence Alignment)

Generate an MSA for a sequence. You rarely call this for a one-off fold (the accurate folders generate it for you), but it is the primer behind `boltz`/`alphafold`/`chai`/`protenix`, and useful to inspect MSA depth, reuse one alignment, or prime a folder with no built-in MSA worker.

Schema highlights:
- Required: `sequence` (`:`-separated for a complex).
- `msaDatabase` (`uniref` default | `swissprot` | `uniref+swissprot`).
- `monomer_msa` (default false): generate a separate MSA per chain vs one for the whole complex.
- `templateMode` (`none` default | `pdb100`): optionally also run a PDB100 template search and emit a downloadable `templates.m8`.

Precomputed-MSA note: boltz/chai accept uploaded `.a3m` alignments (`a3mFiles`) in place of generating them, **matched to a chain by query sequence, not filename** (the a3m's first sequence must equal that chain's sequence), with an explicit file-to-chain map. There is no MSA worker on every path, so precomputed a3m is the way to supply an alignment where one is not auto-generated.

---

## Wider catalog (confirm params live)

One line each; `getAvailableTools(function="structure-prediction")` to enumerate, `getJobSchema(<tool>)` for params.

AF3-class / general complex cofolding (consensus alternatives):
- `openfold` (OpenFold3): AF3 reproduction for protein/nucleic-acid/small-molecule complexes.
- `intfold` (IntelliFold-2): AF3-class complex prediction matching or surpassing AF3.
- `rf3` (RoseTTAFold-3): RosettaFold's AF3 reproduction; a structurally independent model.

Single-sequence / language-model folding:
- `esmfold` (ESMFold): original single-sequence protein folding; fast, no MSA, protein-only; superseded by `esmfold2`.
- `omegafold` (OmegaFold): MSA-free single-sequence prediction; the pick for orphan sequences with no good MSA.

Large assemblies:
- `combfold` (CombFold): AlphaFold-Multimer on subunit pairs plus combinatorial assembly from sequence; the pick when the complex is too big for a single cofold pass. MSA-dependent.

Restraint-guided complexes:
- `alphalink2` (AlphaLink2): complex structure prediction from crosslinking mass-spec (XL-MS) restraints. For pocket/contact restraints without XL-MS data, boltz/chai/protenix expose them directly.

Conformational ensembles / multiple states (AlphaFold derivatives, distribution over a fold):
- `alphaflow` (AlphaFlow): AF fine-tuned with a flow-matching objective for conformational diversity.
- `af-traj` (AF-Traj): alternate conformations via subsampled-MSA AlphaFold2.
- `afcluster` (AF Cluster): multiple conformations by clustering the MSA into sub-alignments; surfaces fold-switching.
- `af2rave` (AF2Rave): diverse structures via reduced-MSA AlphaFold2 plus enhanced sampling.
- `bioemu` (BioEmu): emulate the equilibrium conformational ensemble (Boltzmann-weighted) of a protein. Its primary function facet is `molecular-dynamics` (it is dual-tagged), so filter `getAvailableTools(function="molecular-dynamics")` if it does not surface under structure-prediction; monomer-only.
- `afsample` (AFSample2): heavy-sampling AlphaFold for higher-accuracy multimer prediction on a hard complex.
- `af-unmasked` (AF Unmasked): structure prediction seeded from multimeric templates / a partial complex.

Cyclic peptides:
- `highfold` (HighFold): head-to-tail cyclic-peptide structure prediction, where linear folders mis-model the closure. boltz also has a `cyclicPeptide` flag.

De novo backbone generation (sequence-FREE generators, design-adjacent, not sequence-to-structure folding) -> see `tamarind-binder-design`:
- `genie3` (Genie3), `frameflow` (FrameFlow): SE(3) diffusion / flow-matching backbone generators.
