---
name: tamarind-structure-prediction
description: Predict or co-fold a protein, peptide, nucleic acid, ligand, or biomolecular complex from sequence with Tamarind Bio. Use for AlphaFold-, Boltz-, Chai-, ESMFold-, or Protenix-style structure prediction and confidence interpretation. Not for de novo binder generation, fixed-backbone sequence design, antibody-specific modeling, or docking into a known pocket.
---

# Predict biomolecular structures

Use the live catalog and schema; tool names, versions, and settings change.

## Choose the model family

```bash
tamarind --json tools --function structure-prediction
tamarind --json schema boltz
```

Match the tool to the actual input and output:

- Use a co-folding model such as Boltz, Chai, AlphaFold, or Protenix for multi-chain, ligand, or nucleic-acid complexes when its live schema supports the components.
- Use a fast single-sequence model such as ESMFold2 when speed matters and a single protein fold is sufficient.
- Use an antibody-specific model through `tamarind-antibody` for Fv, VHH, or TCR structure tasks.
- Use `tamarind-docking` when a known receptor structure and a pocket/ligand pose are the central inputs.

Confirm required fields and conditionals with `tamarind --json schema TOOL`. Do not copy a payload between model families.

## Build and validate settings

Represent the input in `settings.yaml`. For file-based YAML, templates, FASTA, or A3M inputs, upload with `tamarind --json files upload PATH` and use the returned bare filename.

```bash
tamarind --json validate TOOL --input settings.yaml --name FOLD_NAME
```

Before submitting, surface choices that materially affect runtime, cost, or interpretation: number of samples/models/batches, MSA use, recycles, model/version, templates/restraints, affinity calculation, and output format. Keep live defaults unless the user intentionally changes them.

For a production canary, minimize input length and independent sample count, but keep the selected model's tuned recycling/diffusion defaults. Do not lower quality parameters to their schema minima solely to save smoke-test cost: a job can complete successfully while producing unusable geometry.

## Run through the canonical lifecycle

Follow `tamarind-submit-and-poll`: confirm scope, submit once, use its filtered bounded wait, inspect `JobStatus`, then use its filtered download helper.

```bash
tamarind --json submit TOOL --input settings.yaml --name FOLD_NAME
# Run tamarind-submit-and-poll's filtered status probe; use wait only for JobStatus.
tamarind --json wait FOLD_NAME --timeout 7200 --poll-interval 15
tamarind --json results FOLD_NAME --download /absolute/path/to/results
```

Never submit during a dry-run request.

## Interpret output

For extracted result directories, rank models with:

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-structure-prediction-skill"
python3 "$SKILL_DIR/scripts/parse_boltz_confidence.py" /absolute/path/to/run --json
```

Resolve `SKILL_DIR` to the directory containing this `SKILL.md`; do not assume the shell is running from the skill directory.

Report local confidence, global fold confidence, and interface confidence separately. A high pLDDT does not by itself prove a correct complex interface; inspect pTM, ipTM, ipSAE, pDockQ, or tool-specific confidence when present. For unambiguously mapped PDB outputs, the helper also checks adjacent protein C-alpha distances. Treat any `geometry_failures` entry as unusable pending inspection. Treat every `geometry_unchecked` entry—including CIF-only or ambiguous multi-model output—as requiring another structure validator or manual inspection before recommendation. This continuity check catches grossly malformed backbones; it is not a substitute for full structural validation.

Read [references/tools.md](references/tools.md) for model-fit caveats and [references/examples.md](references/examples.md) for payload patterns. The live schema overrides stale examples.
