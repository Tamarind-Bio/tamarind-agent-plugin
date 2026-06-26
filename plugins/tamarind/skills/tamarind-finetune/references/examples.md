# Tamarind Bio finetune: validated payloads and what fails

The freshest example for any tool is the `exampleJob` field MCP `getJobSchema("<tool>")` returns; run `validateJob` on it before submitting. The payloads below are `validateJob`-confirmed for field shape (the only blocker on a clean dry-run is the file-not-yet-uploaded error, which is expected before you upload). Schemas drift, so re-fetch with `getJobSchema` if one stops validating. Sequences/SMILES here are illustrative; swap your own.

`BASE = "https://app.tamarind.bio/api"`, `HEADERS = {"x-api-key": <key>}`. All data files are file params: upload first, then reference by **bare filename** (never email-prefixed, never `s3://...`), per the file-input rules in `tamarind-submit-and-poll`.

## The finetune-then-inference shape (the model-name handoff)

```python
# 1. TRAIN: produce a model, keyed by this job's NAME ("esm2-affinity-v1")
submitJob(jobName="esm2-affinity-v1", type="plm-finetune", settings={
    "task": "regression", "baseModel": "facebook/esm2_t33_650M_UR50D",
    "csvFile": "training.csv", "sequenceColumn": "sequence",
    "propertyColumn": "affinity", "epochs": 20, "loraRank": 8, "loraAlpha": 16,
})
# poll esm2-affinity-v1 to Complete (tamarind-submit-and-poll) BEFORE inference

# 2. INFER: run that model on new sequences. model = the finetune job's NAME.
submitJob(jobName="score-new-variants", type="plm-inference", settings={
    "csvFile": "new_variants.csv", "sequenceColumn": "sequence",
    "model": "esm2-affinity-v1",          # NOT in the published schema; set it anyway
})
```

**`model` will not pass `validateJob`.** A dry-run of the inference job with `model` present returns `valid:false, error:"Unrecognized setting: \"model\""` because the published inference schema does not list `model` (the website injects it from the My Models picker). So:

```python
# validate the inference settings WITHOUT model (confirms csvFile/sequenceColumn shape):
validateJob(jobName="score-new-variants", type="plm-inference",
            settings={"csvFile": "new_variants.csv", "sequenceColumn": "sequence"})
#   -> file-not-uploaded error only (shape OK)  ... then ADD model on the real submitJob.
```

This is the single case in the plugin where you submit a field `validateJob` won't bless. The submission reads `model` and resolves your trained checkpoint.

## Validated finetune payloads

### plm-finetune (regression on ESM-2)
```json
{ "type": "plm-finetune",
  "settings": { "task": "regression", "baseModel": "facebook/esm2_t33_650M_UR50D",
    "csvFile": "training.csv", "sequenceColumn": "sequence", "propertyColumn": "affinity",
    "epochs": 20, "loraRank": 8, "loraAlpha": 16 } }
```
Required: `task`, `baseModel`, `csvFile`, `sequenceColumn`, `propertyColumn`. Normalize a regression property to roughly [-1, 1]. For >1000 rows raise `loraRank` to 8-16 with `loraAlpha` roughly equal to or 2x rank.

### esmc-finetune (classification on ESM-C, LoRA)
```json
{ "type": "esmc-finetune",
  "settings": { "csvFile": "labelled.csv", "sequenceColumn": "sequence", "propertyColumn": "label",
    "baseModel": "esmc-600m", "taskType": "classification", "trainingMode": "LoRA",
    "loraRank": 8, "epochs": 20 } }
```
Required: `csvFile`, `sequenceColumn`, `propertyColumn`. For `taskType: "token-classification"`, `propertyColumn` cells are comma-separated integer labels, one per residue.

### boltz-affinity-finetune (structure-aware affinity, precomputed MSA)
```json
{ "type": "boltz-affinity-finetune",
  "settings": { "trainingDataFile": "binding_data.csv", "a3mFiles": ["target.a3m"],
    "epochs": 10, "samplesPerEpoch": 500, "learningRate": 0.0001 } }
```
`trainingDataFile` columns: `protein` (one chain per row), `ligand` (SMILES or CCD), `affinity` (e.g. log10(IC50)), optional `ligand_type`. `a3mFiles` is one precomputed `.a3m` per unique protein (see the MSA recipe below); omit it to train single-sequence at lower accuracy.

### boltz-affinity-inference (single complex)
```json
{ "type": "boltz-affinity-inference",
  "settings": { "sequence": "TRPNHTIYINNLNEKIKKDELKKSLHAIFSRFGQILDILVSRSLK",
    "ligands": ["CC(=O)Nc1ccc(O)cc1"], "ligandType": "Auto-detect",
    "model": "<finetune-job-name>" } }
```
Required: `sequence`, `ligands`. Do NOT send `predictAffinity` (it is `exclude:["api"]`, always on). `model` = the finetune job's name (won't dry-run validate; set on submit).

### balm-finetune (sequence + SMILES affinity)
```json
{ "type": "balm-finetune",
  "settings": { "csvFile": "kiba.csv", "proteinColumn": "target_sequence",
    "drugColumn": "smiles", "labelColumn": "affinity" } }
```
Required: `csvFile`, `proteinColumn`, `drugColumn`, `labelColumn`.

### progen2-finetune (generative protein LM)
```json
{ "type": "progen2-finetune",
  "settings": { "baseModel": "hugohrban/progen2-small", "fastaFile": "family.fasta", "epochs": 5 } }
```
Required: `baseModel`, `fastaFile`. Trains a generator; inference samples new family members.

### reinvent-finetune (small-molecule generative, the `task` selector)
```json
// train a prior on your SMILES
{ "type": "reinvent-finetune",
  "settings": { "task": "train", "data": "actives.csv", "smilesCol": "SMILES", "modelType": "reinvent" } }
```
```json
// sample from that prior: selects the trained model by modelFile, NOT model
{ "type": "reinvent-finetune",
  "settings": { "task": "inference", "numDesigns": 100, "modelFile": "<train-job-name>.model" } }
```
Required (train): `task`, `data`, `smilesCol`. Inference points at the prior via `modelFile` = `"<jobName>.model"` (or `"reinvent.prior"` for the base prior).

## Precomputed-MSA recipe (boltz-affinity only)

There is no MSA worker on the finetune path, so generate the MSAs yourself:

1. Dedupe the `protein` column of your training table to its unique sequences.
2. Run one Tamarind MSA job per unique sequence (search `msa` in the catalog), poll each to Complete, and collect the output `.a3m`.
3. Upload each `.a3m`, then pass the **bare filenames** as the `a3mFiles` list on the finetune job.

The platform matches each a3m to rows by its first (query) record, so filenames and order don't matter. Any protein with no matching a3m runs single-sequence (lower accuracy), with a log warning, not an error.

## What fails (and the exact error)

- **Inference settings include `model`** -> `validateJob` returns `valid:false, "Unrecognized setting: \"model\""`. Expected: validate without `model`, add it on the real `submitJob` (above).
- **Data file referenced before upload** -> `File "training.csv" has not been uploaded`, with `source:"static-fallback"`. The `source` label is the schema-resolution note (built-in tools always report `static-fallback`), NOT "validator unavailable", so the field shape is fine and only the upload is missing. Upload, then re-validate.
- **Email-prefixed file path** (`{email}/training.csv`) -> treated as inline content, fails the file check. Use the bare filename.
- **Wrong CSV column name** (e.g. `sequenceColumn` doesn't match a real header) -> the wrapper raises a clear `TamarindInputError` listing the columns it actually found. Read the table header and set the column settings to match.
- **Regression property not normalized** (large raw values) -> training loss diverges; normalize the property column to roughly [-1, 1] first.
- **Inference submitted before the finetune job is `Complete`** -> the model isn't registered yet. Poll the finetune job to `Complete` first; a `Stopped` finetune produced no model.

## Output shapes (describe, don't expect exact values)

- **plm/esmc inference**: the input CSV with predictions appended (`predicted` for regression / per-residue tokens, or per-class probability columns for classification).
- **boltz-affinity inference**: a predicted affinity score + binding probability per complex.
- **balm inference**: an inference-results CSV.
- **progen2 / reinvent inference**: generated sequences / SMILES.
- Use MCP `listJobFiles(jobName)` to enumerate exact output filenames before downloading; they vary by tool and version.
