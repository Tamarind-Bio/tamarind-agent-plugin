# Tamarind Bio finetune tools: schema, when-to-pick, gotchas

Pull the live schema with `getJobSchema("<tool>")` (or `GET /tools`) before submitting; schemas drift. This file captures the non-obvious behaviors and the pick-the-right-pair reasoning. Every pair follows the same handoff: train `<tool>-finetune`, then run `<tool>-inference` with `model` set to the finetune job's name (the exceptions, `reinvent` and any tool that keys differently, are flagged below). See [examples.md](examples.md) for payloads.

## plm-finetune / plm-inference (Finetune Protein Language Model)

Predict a numeric or categorical property of a protein from its sequence (binding affinity, thermostability, expression, activity, binder/non-binder) by finetuning a pretrained ESM-2 / ProtT5 / ProstT5 backbone on your labeled sequence-to-property table. LoRA by default (small adapters, low VRAM); full-model finetuning optional.

**Pick this** for the general "I have a CSV of sequences plus a measured property, train a predictor" case on ESM-2 / ProtT5. It is the most-used, best-tuned finetuner here. Want the newer ESM-C backbone, per-residue labels, or masked-LM domain adaptation? Use `esmc-finetune`. Property depends on a protein AND a small-molecule ligand? Use `balm-finetune` (sequence + SMILES) or `boltz-affinity-finetune` (structure-aware, higher fidelity). Want to GENERATE new family members rather than score existing ones? Use `progen2-finetune` (a generative LM, not a regressor).

Finetune schema. Required: `task` (`regression` | `classification`), `baseModel` (dropdown: `facebook/esm2_t6_8M_UR50D`, `_t12_35M_`, `_t30_150M_`, `_t33_650M_` [default], `_t36_3B_UR50D`, `Rostlab/prot_t5_xl_uniref50`, `Rostlab/ProstT5`), `csvFile`, `sequenceColumn`, `propertyColumn`. Key optional: `epochs` (20), `learningRate` (3e-4, LoRA-tuned), `batchSize` (1), `gradientAccumulation` (8; effective batch = batch x accumulation, recommended 8), `dropout` (0.2), `seed` (42), `fullModelTraining` (false), `loraRank` (4), `loraAlpha` (1), `mixedPrecision` (true), `deepspeed` (false), `earlyStoppingPatience` (5), `valBatchSize` (16).

Inference schema. `csvFile` + `sequenceColumn`, plus the injected `model` = the finetune job name (not in the published schema; see the SKILL handoff section). Output appends predicted values / class probabilities.

Gotchas:
- **Regression: normalize your property to roughly [-1, 1].** Large raw values diverge the loss.
- **One non-numeric cell in the property column** (an Excel `#DIV/0!`) makes pandas read the whole column as strings and the trainer crashes at step 0 for regression. The wrapper rejects this at submit with the offending values listed.
- **`learningRate` default 3e-4 is LoRA-tuned.** For `fullModelTraining` use 1e-5 to 5e-5 or it diverges.
- **LoRA defaults (`loraRank=4`, `loraAlpha=1`) are for small data.** Datasets over ~1000 training rows want rank 8-16 with alpha roughly equal to or 2x rank.
- **Tiny single-protein datasets saturate** (predictions compress toward the mean), a small-data capacity ceiling, not a bug.
- The backbone setting is `baseModel`, not `plmModel` (a different setting on binder-design tools).

## esmc-finetune / esmc-inference (ESMC Finetune)

Finetune the newer-generation ESM-C backbone for per-sequence regression/classification, per-RESIDUE (`token-classification`) labeling, or `masked-lm` domain adaptation.

**Pick this** over `plm-finetune` when you specifically want ESM-C, OR a task the PLM pair doesn't offer: `token-classification` (per-residue labels, e.g. secondary structure / binding-site annotation) or `masked-lm` (continue pretraining ESM-C on your domain corpus, no labels needed for the LM objective). For straightforward per-sequence property prediction on ESM-2 / ProtT5 with the most battle-tested loop, `plm-finetune` is the safer default.

Finetune schema. Required: `csvFile`, `sequenceColumn` (default `sequence`), `propertyColumn` (default `label`). Key optional: `baseModel` (`esmc-300m` | `esmc-600m` [default]; 6B not available at launch), `taskType` (`regression` [default] | `classification` | `token-classification` | `masked-lm`), `trainingMode` (`LoRA` [default] | `Full`), `epochs` (20), `learningRate` (3e-4), `batchSize` (2), `gradientAccumulation` (4), `loraRank` (8; applies only when `trainingMode=LoRA`, ignored for `Full`), `dropout` (0.1), `maxLength` (1024), `seed` (42).

Inference schema. `csvFile` + `sequenceColumn` + the injected `model`. Appends `predicted` (regression/tokens) or per-class probability columns.

Gotchas:
- **For `token-classification` the property column holds COMMA-SEPARATED integer labels, one per residue.**
- The wrapper drops NaN rows and rejects a training CSV with fewer than 2 usable rows.
- `loraRank` is conditional on `trainingMode=LoRA`.

## boltz-affinity-finetune / boltz-affinity-inference (Boltz-2 Affinity)

Improve protein-ligand binding-affinity prediction on YOUR chemical series by finetuning the Boltz-2 affinity head on measured protein+ligand+affinity rows. Structure-aware (it embeds every complex with Boltz-2), so it captures binding-pocket geometry a sequence-only regressor cannot.

**Pick this** for the highest-fidelity, structure-aware affinity model when binding geometry matters and you can afford the heavier compute. For a lighter, faster sequence+SMILES regressor (no structure step) use `balm-finetune`. For a per-sequence protein property with no ligand use `plm`/`esmc`. For a one-off affinity prediction without training, use the base `boltz` cofolding tool with affinity (in `tamarind-structure-prediction` / `tamarind-docking`), not this pair.

Finetune schema. Required: `trainingDataFile` (.csv or .xlsx), one row per protein-ligand complex with columns `protein` (ONE chain per row), `ligand` (SMILES or a CCD code), `affinity` (measured value, e.g. log10(IC50)). Optional `ligand_type` column (`smiles`/`ccd`) disambiguates a CCD code that also parses as SMILES (CO, NA, NO). Key optional settings: `a3mFiles` (.a3m list, precomputed MSAs, see below), `epochs` (10), `samplesPerEpoch` (500, tune to dataset size), `learningRate` (1e-4).

Inference schema. A SINGLE complex: `sequence` (required; `:` for multimer chainbreaks), `ligands` (required SMILES list), optional `ligandType` (`Auto-detect`/`SMILES`/`CCD`), `a3mFiles` (per-chain MSA list), `binderChain`, plus the injected `model`. Returns a predicted affinity score + binding probability. **`predictAffinity` is `exclude:["api"]`** (always-on for affinity inference), so do NOT send it over the API.

Gotchas:
- **MSAs are PRECOMPUTED ONLY, no MSA worker on the finetune path.** Generate one `.a3m` per unique protein with the Tamarind MSA tool; each a3m's first record is its query sequence and is matched to rows by that sequence (filename/order don't matter). No a3m means single-sequence training (lower accuracy) with a log warning. (See the SKILL "Precomputed MSA" section.)
- **One protein chain per row only.** `:`-joined multi-chain cells are rejected.
- Ligand SMILES-vs-CCD is auto-detected via RDKit validity; the optional `ligand_type` column overrides it. The table is read keeping NA tokens literal, so CCD codes like `NA` (sodium) survive.

## balm-finetune / balm-inference (Finetune BALM)

Finetune BALM for protein-ligand binding-affinity regression from SEQUENCE + SMILES (no structure step).

**Pick this** as the lighter, faster alternative to `boltz-affinity-finetune` when structure-level fidelity isn't required.

Finetune schema. Required: `csvFile`, `proteinColumn`, `drugColumn`, `labelColumn`. Inference runs a trained BALM model and writes an inference-results CSV; it selects the model by the injected `model` = the finetune job name.

## progen2-finetune / progen2-inference (ProGen2 Finetuning)

Finetune a GENERATIVE protein LM (ProGen2 small/medium/large/xlarge/oas) on a FASTA of family sequences to SAMPLE new members.

**Pick this** to generate sequences in a family (family-conditioned de novo generation), NOT to score a property (that's `plm`/`esmc`).

Finetune schema. Required: `baseModel` (`hugohrban/progen2-small` [default] / `-medium` / `-large` / `-xlarge` / `-oas`), `fastaFile` (.fasta). Optional: `epochs` (5). Inference generates new sequences from the finetuned model (or a base ProGen2); selects the model by the injected `model` = the finetune job name. No MSA step (sequence-only).

## enzygen2-finetune / enzygen2-inference (EnzyGen2 Finetuning)

Finetune EnzyGen2 on a specific ENZYME FAMILY for structure-conditioned enzyme design. Niche, JSON-format input.

Finetune schema. Required: `dataFile` (EnzyGen2-format JSON keyed by NCBI taxonomy IDs, with train/valid splits, sequences, C-alpha coords, motif indices; all keys are used for training), `proteinTask` (an NCBI taxonomy ID present in the JSON, e.g. `77133`). Optional: `epochs` (50), `learningRate`, `maxUpdate`, `dropout` (all sweepable). Inference generates enzyme sequences/structures from the finetuned model; confirm how it keys the prior run with `getJobSchema("enzygen2-inference")`.

## reinvent-finetune (REINVENT4, small-molecule generative)

The only small-molecule generative finetuner here. ONE tool with a `task` selector, not a finetune/inference pair: `train` finetunes a generative prior on a CSV of SMILES (optionally multi-stage RL with scoring components + diversity filters), `inference` samples new molecules from a prior or a custom finetuned `.model`, `scoring` scores a SMILES file.

**Pick this** for de novo small-molecule design, molecule optimization, scaffold decoration, linker/peptide design.

Schema highlights. `task` (`train` [default] / `inference` / `scoring`, required). Train: `data` (.csv, required), `smilesCol` (required), `modelType` (`reinvent` [default] / `mol2mol` / `libinvent` / `linkinvent` / `pepinvent`), `num_epochs` (50, reinvent only), plus RL knobs (`stages`, `scoringComponents`, `sigma`, `diversityFilter`, `max_steps`). Inference: `numDesigns` (100), **`modelFile`** = `"<train-job-name>.model"` (or `"reinvent.prior"` for the base prior), `modelType`. Scoring: `scoringSmilesFile`, `scoringComponents`.

**Handoff difference.** Inference selects the trained prior via **`modelFile`** in the `"<jobName>.model"` form, NOT a `model` setting. Same concept as the protein pairs (point at a prior training job by name), different field name and a `.model` suffix.

## saprot-finetune (SaProt Finetuning, no model-name handoff)

Finetune SaProt, a BERT-style structure-aware protein LM whose vocabulary combines the 20 amino acids with Foldseek 3Di STRUCTURAL tokens (pretrained on ~40M sequence/structure pairs), on your labeled data. The trained checkpoint is saved as a REUSABLE inference tool on the platform, so there is no `model`-name handoff like the pairs above.

**Pick this** when 3D structural context should help the supervised task (stability, structure-dependent function, fitness) and a zero-shot SaProt score or generic embeddings aren't enough. NOT a structure predictor (it consumes structure tokens as INPUT). For sequence-only property prediction use `plm` / `esmc`; for antibody-specific finetuning use an antibody PLM; for protein-ligand affinity use `balm` / `boltz-affinity`.

Gotchas:
- **Needs a 3D structure** to derive the 3Di tokens. If you only have sequence, predict a structure first (e.g. AlphaFold) and tokenize that.
- Pull `getJobSchema("saprot-finetune")` for the exact structure-file / column settings before submitting.

## multi-evolve (MULTI-evolve, end-to-end workflow, no model-name handoff)

End-to-end ML-guided directed evolution (Arc Institute, Science 2026). Trains fully-connected neural nets on deep-mutational-scanning or pairwise-combination assay data to predict combinatorial-variant fitness, nominates synergistic multi-mutants that capture epistasis, and emits MULTI-assembly mutagenic oligos for gene synthesis of the nominated variants. With no assay data yet, a protein-LM zero-shot ensemble nominates beneficial single mutants to seed the first round.

**Pick this** to engineer hyperactive variants of enzymes, genome editors, or therapeutics where stacking single beneficial mutations isn't enough and you have (or can collect) ~100-200 measurements per round. NOT for pure zero-shot scoring without the evolution / oligo workflow (use a PLM such as `esm2` / `amplify`), de novo binder design, or structure-based interface ddG. A self-contained workflow, not a finetune/inference pair, so there is no `model` handoff. Confirm input format with `getJobSchema("multi-evolve")`.
