# Tamarind Bio: validated batch payloads and row shapes

Batch payloads are one tool with parallel `jobNames[]` and `settings[]` arrays (same length, same tool, up to 100). The freshest per-tool settings shape is MCP `getJobSchema(<tool>)`; the payloads below are `validateJob`-confirmed examples for the canonical screen tools. Sequences are illustrative; swap your own. The aggregation + `batchStatus` polling are the same regardless of tool, so these examples vary only the per-subjob `settings` shape.

`BASE = "https://app.tamarind.bio/api"`, `HEADERS = {"x-api-key": <key>}`.

## Self-check (run first, no submission, no cost)

Confirms discovery is reachable and validates the SHARED settings shape a batch would multiply, without submitting:

```python
import os, requests
BASE, HEADERS = "https://app.tamarind.bio/api", {"x-api-key": os.environ["TAMARIND_API_KEY"]}

# 1. discovery reachable?
tools = requests.get(f"{BASE}/tools", headers=HEADERS).json()
assert isinstance(tools, list) and any(t["name"] == "alphafold" for t in tools), "tools endpoint"

# 2. validate ONE shared shape (MCP validateJob; skip if REST-only) -> expect {"valid": true, ...}
#    validateJob(jobName="probe", type="alphafold",
#                settings={"sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIE"})
```

Validate the shared shape **once**; it is the shape every subjob inherits.

## Validated batch payloads

### Folding screen (AlphaFold, many sequences)

```json
{ "batchName": "fold-screen",
  "type": "alphafold",
  "jobNames": ["cand-0", "cand-1", "cand-2"],
  "settings": [
    { "sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIE" },
    { "sequence": "AVFLSEDEINRLAKNGYGFGEINKALEAAGYDV" },
    { "sequence": "GEVPQTPKDVMRYLAEHNIPHSQVKTLLGKL" }
  ],
  "weightedHoursBudget": 50 }
```

`jobNames` and `settings` are parallel (index `i` of one matches index `i` of the other). Each subjob inherits the AlphaFold settings shape; only `sequence` varies here. `weightedHoursBudget` caps the whole batch.

### Folding screen with shared knobs (ESMFold2, single-sequence fast mode)

```json
{ "batchName": "esm-screen",
  "type": "esmfold2",
  "jobNames": ["s0", "s1"],
  "settings": [
    { "inputFormat": "sequence", "model": "esmfold2-fast", "sequence": "MKTIIALSYIFCLVFAD" },
    { "inputFormat": "sequence", "model": "esmfold2-fast", "sequence": "MALKSLVLLSLLVLVLLLVRVQPSLG" }
  ] }
```

`model: "esmfold2-fast"` is a **shared knob**: setting it changes the speed/cost of **every** subjob (no MSA encoder, fits smaller GPUs, slight accuracy trade-off). This is the surface-the-cost-multiplier point from SKILL.md step 2: one shared choice multiplies across N. `inputFormat` is required for esmfold2 (as for boltz/chai).

### Docking screen (Autodock Vina, one receptor, a ligand set)

```json
{ "batchName": "vina-screen",
  "type": "autodock-vina",
  "jobNames": ["lig-0", "lig-1"],
  "settings": [
    { "receptorFile": "receptor.pdb", "ligandFormat": "smiles",
      "ligandSmiles": "CC(=O)Oc1ccccc1C(=O)O",
      "boxX": 15.19, "boxY": 53.903, "boxZ": 16.917, "width": 20, "height": 20, "depth": 20 },
    { "receptorFile": "receptor.pdb", "ligandFormat": "smiles",
      "ligandSmiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
      "boxX": 15.19, "boxY": 53.903, "boxZ": 16.917, "width": 20, "height": 20, "depth": 20 }
  ] }
```

The receptor and bounding box are shared across the screen (same pocket); only the ligand varies per subjob. `receptorFile` references an **uploaded file by its bare filename** (`receptor.pdb`, NOT email-prefixed); upload it once with `upload_file`. Autodock Vina's `ligandFormat` enum is **lowercase** (`"smiles"`/`"sdf"`).

### Batch off a design job (MCP fromJob, no arrays)

```
submitBatch(batchName="verify-designs", type="alphafold", fromJob="design-step")
```

`fromJob` is MCP-only: it reads a completed design job's generated sequences and folds each as one subjob, so you don't build the arrays by hand. Over plain REST, parse the design output and build the parallel arrays (see workflows.md recipe 4).

## What fails (and the exact behavior)

- **`jobNames` and `settings` different lengths** -> the arrays are parallel and must align (the client `submit_batch` asserts equal length before the call). Build them from one source so they can't drift.
- **A batch-excluded field in the shared settings** -> a param marked `"exclude": ["api", "batch", "tools"]` in `getJobSchema` (e.g. AlphaFold's `chooseBest`) is a UI/pipeline-only knob the batch path ignores. Don't put it in the shared `settings` expecting per-subjob effect. The `exclude` list is MCP-only (`getJobSchema`), not in REST `/tools`.
- **Two different tools in one batch** -> not allowed; `type` is one tool for the whole batch. Run two batches (or a pipeline).
- **Stopping at "all subjobs Complete"** -> the parent may still be `Aggregating`; the aggregated `resultUrl` only exists once `batchStatus == "Complete"`. Poll the parent, not the subjobs.
- **A file param given a bare non-filename string** -> treated as inline content, not a reference. To point at an uploaded file use its bare filename (not the `{email}/...` S3 key); for a prior job's output use the `JobName/...` path.

## Parent and subjob row shapes (what rank_batch.py consumes)

**Batch parent** (`GET /jobs?jobName=<batchName>`, returns the row directly): `Type: "batch"`, `batchStatus` (`Running`/`Aggregating`/`Complete`/`AggregationFailed`/`Stopped`), a `statuses` subjob tally, and on a Complete parent a presigned `resultUrl`. On `AggregationFailed` the parent carries `AggregationError`.

```json
{ "JobName": "binder-screen", "Type": "batch", "batchStatus": "Complete",
  "statuses": { "Complete": 3, "Running": 0, "In Queue": 0, "Stopped": 0 },
  "resultUrl": "https://...presigned..." }
```

**Subjob rows** (`GET /jobs?batch=<batchName>&includeSubjobs=true` -> `{"jobs": [...]}`): each carries its own `JobName`, `JobStatus`, and `Score` (a JSON STRING of tool metrics), plus `WeightedHours`.

```json
{ "JobName": "binder-screen-cand-1", "JobStatus": "Complete",
  "Score": "{\"plddt\": 88.4, \"ptm\": 0.79, \"iptm\": 0.61}", "WeightedHours": 0.42 }
```

`rank_batch.py` accepts either a dir holding `parent.json` + `subjobs.json`, or a JSON file shaped `{"parent": <parent-row>, "subjobs": [<subjob-row>, ...]}` (or a bare list of subjob rows). It parses each subjob's `Score`, ranks the completed ones by `--metric` (auto-picked when omitted), and writes `ranked_batch.csv`.

## Output shapes (describe, don't expect exact values)

Outputs are non-deterministic (seed/model/MSA), so reason about the shape, not golden numbers.

- **Subjob `Score`** (JSON string): tool-family dependent. Folding subjobs carry `plddt`, `ptm`, and for complexes `iptm` plus interface metrics (`ipSAE_*`, `pDockQ_*`). Docking subjobs carry an affinity/score. Read the keys, don't assume.
- **Batch result zip** (`POST /result` on the parent, or `parent["resultUrl"]`): the aggregated per-subjob artifacts (structures, a combined scores CSV, logs). Use MCP `listJobFiles(<parent-or-subjob>)` to enumerate exact filenames before relying on them.
- **`WeightedHours`** per subjob is the billing unit; the batch's total is the sum across subjobs.
