---
name: tamarind-finetune
description: "Use to fine-tune a model on YOUR labeled data and then run inference with it on Tamarind Bio, no local GPU: train a \"<tool>-finetune\" job to produce a model, then submit the matching \"<tool>-inference\" job with its model setting set to the finetune job's NAME. Covers protein-property predictors (plm/esmc), protein-ligand affinity (boltz-affinity, balm), generative protein LMs (progen2), enzyme design (enzygen2), and small-molecule generation (reinvent). Not for running a stock pretrained model (use the matching domain skill: tamarind-structure-prediction, tamarind-inverse-folding, tamarind-docking), not for first-time key setup (use tamarind-api-setup)."
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: fine-tune on your data, then run inference

Train a model on YOUR labeled data and run it on new inputs, with Tamarind owning the GPUs. The shape is always a **pair**: a `<tool>-finetune` job trains a model from your table and registers it to your account, then a matching `<tool>-inference` job runs that model on new inputs. You never download a checkpoint or provision hardware; the model lives on the platform, keyed by the finetune job's name.

This skill is the connective layer over `tamarind-submit-and-poll`, which owns all execution mechanics (validate, submit, poll to terminal, download, the by-name bare row, the two-step `/result`, the bare-filename file-param rule). It does not re-teach those. It adds the two things that are unique to finetuning and are NOT obvious from the schemas: the **model-name handoff** and the **CSV-column-name settings**. For running a stock pretrained model use the matching domain skill; for first-time key setup use `tamarind-api-setup`.

## The handoff: inference's `model` is the finetune job's NAME (the key gotcha)

A `<tool>-finetune` job registers its trained checkpoint under your account, keyed by the **finetune job's name**. The matching `<tool>-inference` job selects which trained model to run via a `model` setting whose value is **that finetune job's name**.

```
submitJob(jobName="esm2-affinity-v1", type="plm-finetune", settings={...})   # train, poll to Complete
submitJob(jobName="score-new-variants", type="plm-inference",
          settings={"csvFile": "new.csv", "sequenceColumn": "sequence",
                    "model": "esm2-affinity-v1"})                            # model = the finetune job's NAME
```

Three things that trip up an API caller, all verified live:

- **`model` is NOT in the inference tool's REST / `getJobSchema` schema.** In the website UI it is the "My Models" picker, injected by the front end. The published inference schema lists only `csvFile` + `sequenceColumn` (for the PLM pair). So you will not find `model` by reading the schema, you have to know to set it.
- **`validateJob` rejects `model` as `"Unrecognized setting: \"model\""`.** Strict validation runs off the published schema, which doesn't list `model`, so a dry-run of the inference job with `model` present comes back `valid:false` on that field even though the submission will read it. Don't treat that as a real error: validate the inference settings WITHOUT `model` (to confirm `csvFile`/`sequenceColumn` shape), then ADD `model` = the finetune job name on the actual `submitJob`. This is the one case in the plugin where you submit a field `validateJob` won't bless.
- **The finetune job must be `Complete` before inference can find its model.** Poll the finetune job to terminal (`tamarind-submit-and-poll`) and confirm `Complete`, then submit inference. A `Stopped` finetune produced no model.

**Handoff exceptions** (two tools key the model differently, read the schema):

- `reinvent-finetune` (small-molecule generative, the only small-molecule generative finetuner here) is ONE tool with a `task` selector (`train` / `inference` / `scoring`). Inference does not use `model`, it uses **`modelFile`** in the form `"<finetune-job-name>.model"` (or `"reinvent.prior"` for the base prior). Same idea (point at a prior training job), different field + a `.model` suffix.
- `enzygen2` and `mavenets` are also finetune/inference pairs whose inference selects the prior training run by name. Confirm the exact field with `getJobSchema("<tool>-inference")` and the catalog notes in [references/tools.md](references/tools.md).

## CSV column NAMES are settings, not assumptions

Most finetuners read a table (CSV/XLSX) and you must NAME the columns in your file via settings, the wrapper does not guess. Get a name wrong and the wrapper raises a clear error listing the columns it actually found. The column settings differ per tool:

| Tool | Data file | Column settings |
|---|---|---|
| `plm-finetune` | `csvFile` | `sequenceColumn`, `propertyColumn` |
| `esmc-finetune` | `csvFile` | `sequenceColumn` (default `sequence`), `propertyColumn` (default `label`) |
| `balm-finetune` | `csvFile` | `proteinColumn`, `drugColumn`, `labelColumn` |
| `boltz-affinity-finetune` | `trainingDataFile` (.csv/.xlsx) | fixed column NAMES `protein`, `ligand`, `affinity` (+ optional `ligand_type`), not settings |
| `reinvent-finetune` (train) | `data` (.csv) | `smilesCol` |

The data file itself is a **file param**: upload first, then pass the **bare filename** (`training.csv`), never an email-prefixed S3 key and never `s3://...` (the bare-filename rule from `tamarind-submit-and-poll`; an email-prefixed path silently falls to the inline-content branch and fails). A `validateJob` returning `File "x.csv" has not been uploaded` with `source:"static-fallback"` means the field shape is otherwise valid and only the upload is missing, that is the expected dry-run result before you upload.

## Precomputed MSA on the affinity-finetune path (a hard prereq)

`boltz-affinity-finetune` and `boltz-affinity-inference` are structure-aware (they embed each complex with Boltz-2 under the hood), so they want an MSA per protein, but **there is no MSA worker on the finetune path**: MSAs are **precomputed only**. You must generate them yourself and pass them in `a3mFiles`:

- Generate one `.a3m` per **unique protein** with the Tamarind MSA tool (search `msa` in the catalog), one MSA job per distinct protein sequence.
- Each `.a3m`'s **first record is its query sequence**, and the platform matches an a3m to the training rows whose `protein` equals that query sequence, so **filename and order don't matter**, the content does.
- A protein with no matching `.a3m` trains/runs **single-sequence** (lower accuracy), with a warning in the log, not an error.

So the affinity-finetune recipe is: dedupe your `protein` column, run one MSA job per unique sequence, collect the a3m files, upload them, then pass the bare filenames as the `a3mFiles` list. The sequence-only PLM finetuners (`plm`, `esmc`, `progen2`) have NO MSA step.

## The canonical pairs at a glance

Deep notes + when-to-pick + gotchas per tool are in [references/tools.md](references/tools.md); validated payloads in [references/examples.md](references/examples.md).

- **`plm-finetune` / `plm-inference`**: predict a numeric or categorical protein property (affinity, stability, expression) from sequence by finetuning ESM-2 / ProtT5 / ProstT5. LoRA by default. The most battle-tested pair; the general "CSV of sequences plus a measured property" case.
- **`esmc-finetune` / `esmc-inference`**: same property-prediction task on the newer ESM-C backbone, plus `token-classification` (per-residue labels) and `masked-lm` (domain adaptation) that the PLM pair doesn't offer.
- **`boltz-affinity-finetune` / `boltz-affinity-inference`**: highest-fidelity, structure-aware protein-ligand affinity on YOUR chemical series. Heavier (embeds every complex), needs precomputed MSAs (above). Inference is a SINGLE complex (`sequence` + `ligands`).
- **`balm-finetune` / `balm-inference`**: lighter, faster sequence-plus-SMILES affinity regressor (no structure step). Reach for it over boltz-affinity when structure-level fidelity isn't required.
- **`progen2-finetune` / `progen2-inference`**: finetune a GENERATIVE protein LM (ProGen2) on a FASTA of family sequences to SAMPLE new members. A generator, not a property predictor.
- **`enzygen2-finetune` / `enzygen2-inference`**: structure-conditioned enzyme design within an NCBI-taxonomy family; niche JSON-format input.
- **`reinvent-finetune`**: REINVENT4 small-molecule generative engine (the only small-molecule generative finetuner). One tool, `task` = `train` / `inference` / `scoring`; inference selects a prior via `modelFile` (above), not `model`.

Two more finetune-family tools that do NOT use the model-name handoff, named here so they surface:

- **`saprot-finetune`**: supervised finetune of the structure-aware SaProt PLM (SA alphabet = amino-acid tokens + Foldseek 3Di STRUCTURAL tokens, so it needs a 3D structure) on a labeled dataset where structural context helps (stability, structure-dependent function, fitness). The trained checkpoint is saved as a REUSABLE inference tool on the platform, not consumed via a `model` setting. It reads structure tokens as input and does NOT predict structure.
- **`multi-evolve`**: ML-guided directed evolution. Trains neural nets on YOUR DMS / pairwise-combination assay data (~100-200 measurements per round) to rank combinatorial multi-mutants accounting for epistasis, nominates synergistic multi-mutants, and generates MULTI-assembly mutagenic oligos for gene synthesis; a protein-LM zero-shot ensemble nominates beneficial single mutants when you have no assay data yet. An end-to-end workflow, not a finetune/inference pair.

For anything not named here, filter live: `getAvailableTools(function="finetuning")` (or `GET /tools`), read each candidate's `description`, and confirm params with `getJobSchema` before submitting.

## Cost framing

Finetune jobs are GPU jobs and bill in **weighted hours** like any other job: a single number per job that scales with runtime and GPU tier. `epochs`, `samplesPerEpoch`, dataset size, and backbone size (e.g. `esm2_t36_3B` vs `esm2_t33_650M`) all drive cost. Surface the consequential training knobs (backbone, epochs, full-model vs LoRA, samples per epoch) before submitting when the request is open-ended, rather than defaulting silently, per the surface-choices discipline in `tamarind-submit-and-poll`.

## Reference files

- [references/tools.md](references/tools.md): per-pair schema, when-to-pick-this-vs-siblings, and the gotchas (regression normalization, LoRA rank for large data, token-classification label format, single-chain-per-row for affinity, the reinvent `task` selector).
- [references/examples.md](references/examples.md): `validateJob`-confirmed finetune payloads, the inference-with-`model` submit shape (and why it won't dry-run), the precomputed-MSA recipe, and what-fails errors.
