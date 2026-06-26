# Binder design: validated payloads, chaining, what fails

The freshest example for any tool is the `exampleJob` that MCP `getJobSchema(<tool>)` returns (a `{jobName, type, settings}` built from each param's example/default, with file params as placeholders). It is the best starting point, but **run `validateJob` on it before submitting**: it is assembled from per-param examples, not a guaranteed-valid payload. The payloads below are a `validateJob`-confirmed fallback for REST callers or a worked example. Tool schemas evolve; if one stops validating, re-fetch with `getJobSchema(<tool>)`.

`BASE = "https://app.tamarind.bio/api"`, `HEADERS = {"x-api-key": <key>}`. Settings go in the `settings` field of a `submitJob` / `POST /submit-job` call.

**File params (`pdbFile`, `targetFile`) need a real file value:** the **bare filename** of an uploaded file (`target.pdb`, NOT email-prefixed), a prior-job output path (`JobName/out/x.pdb`), or inline PDB text (multi-line `ATOM`/`HETATM` records). The `target.pdb` placeholders below are NOT valid until you upload a real target and pass its bare name. Do not put an amino-acid sequence in a file param: `validateJob` rejects it (`File ... must be of types: ["pdb"]`).

## Validated input payloads (settings only)

### BindCraft, protein target, default mode
```json
{"mode": "default", "pdbFile": "target.pdb", "chains": ["A"],
 "hotspotResidues": {"A": "56-58"}, "numDesigns": 10, "binderLengthRange": "70,120"}
```
Leave `hotspotResidues` out entirely to auto-select hotspots. `numDesigns` is how many must PASS filters, so a hard target can run to `maxRunTime` and stop with fewer (or zero).

### RFdiffusion, Binder Design
```json
{"task": "Binder Design", "pdbFile": "target.pdb", "targetChains": ["A"],
 "binderLength": "60-100", "binderHotspots": {"A": "45 47 52"}, "numDesigns": 8, "verify": true}
```
`binderHotspots` is **space-separated** within a chain (not comma). `verify: true` runs ProteinMPNN + AlphaFold scoring on the designs.

### RFdiffusion3, protein binder (all-atom)
```json
{"task": "protein-binder-design", "pdbFile": "target.pdb", "targetChains": ["A"],
 "binderLength": "80,120", "hotspots": {"A": "45 47 52"}, "numDesigns": 4}
```
For a small-molecule target, switch `task` to `small-molecule-binder-design`, add `ligands` (the ligand codes in the PDB) and `smBinderConditions`; for a nucleic-acid target use `na-binder-design`; for an enzyme active site use `enzyme-design`. `binderLength` is `"min,max"`.

### BoltzGen, de novo nanobody against a protein
```json
{"binderType": "de-novo-nanobody", "targetFile": "target.pdb", "targetChains": ["A"],
 "scaffold": "default", "numDesigns": 10}
```
`scaffold: "default"` uses bundled VHH frameworks. `runIpsae` defaults true (per-complex ipSAE/pDockQ). Set `skipRefolding: true` only if you accept ranking on the original (non-refolded) structures, and then verify by pulling a real PDB.

### RFpeptides, macrocyclic binder
```json
{"pdbFile": "target.pdb", "targetChains": ["A"], "binderLength": "12-18",
 "binderHotspots": {"A": "48 50 51 52 62 65"}, "numDesigns": 8, "temperature": 50}
```
`temperature` is the diffusion-step count, not a sampling temperature.

### PepMLM, linear peptide binder (sequence-only, directly runnable)
```json
{"targetSequence": "MQRGKVKWFNNEKGYGFIEVEGGSDVFVHFTAIQGEGFKTLEEGQEVSFEIVQGNRGPQAANVVKE",
 "peptideLength": 15, "numDesigns": 8}
```
`numDesigns` is a dropdown: one of `[1,2,4,8,16,32]`.

## Upload a target, then submit (the common first step)

Every structure-target binder tool needs an uploaded target PDB first:

```python
import os, requests
BASE, HEADERS = "https://app.tamarind.bio/api", {"x-api-key": os.environ["TAMARIND_API_KEY"]}

# REST: PUT the file; reference it by the BARE filename afterward (NOT email-prefixed)
with open("my_target.pdb", "rb") as fh:
    requests.put(f"{BASE}/upload/my_target.pdb", headers=HEADERS, data=fh).raise_for_status()

requests.post(f"{BASE}/submit-job", headers=HEADERS, json={
    "jobName": "nb-design", "type": "boltzgen",
    "settings": {"binderType": "de-novo-nanobody", "targetFile": "my_target.pdb",
                 "targetChains": ["A"], "scaffold": "default", "numDesigns": 10},
}).raise_for_status()
```

MCP variant: `uploadFile("my_target.pdb")` returns a presigned URL, `curl -X PUT -T my_target.pdb "<url>"`, then pass the bare `"my_target.pdb"` as `targetFile`.

## Chain: design, then fold/validate the designs

A binder generator that emits SEQUENCES (e.g. a peptide tool, or RFdiffusion's downstream ProteinMPNN step) is folded back by passing each sequence as a `sequence`, NOT through a file/template field. The cleanest design-then-fold chain is MCP `submitBatch(fromJob=...)`, which reads a completed design job's generated sequences and folds each:

```
# design step (poll to Complete), then fold every designed sequence in one batch call:
submitBatch(batchName="fold-designs", type="alphafold", fromJob="my-design-job")
```

For a tool that emits STRUCTURES (BoltzGen / RFdiffusion backbones), chain by **file path**: pass a prior job's output as `JobName/path/to/file.cif` into the next tool's file param, after confirming the param's type with `getJobSchema`/`validateJob`. Use `listJobFiles(jobName)` to discover the exact output paths (`s3Path`), then feed those into the next `submitJob`. See `tamarind-submit-and-poll` references for the full chaining rules.

## What fails (and the exact signal)

- **A required selector left out.** Every binder tool's first field is required (`mode` / `task` / `binderType`); omitting it (or a field that belongs to a different mode) fails validation. `getJobSchema` first and read each param's `tasks` / `binderTypes`.
- **Hotspot separator wrong.** RFdiffusion `binderHotspots`, RFdiffusion3 `hotspots`, and RFpeptides `binderHotspots` are SPACE-separated within a chain. A comma-joined `"45,47,52"` is the wrong shape for these.
- **A file param given a bare non-filename string** is treated as INLINE file content, not a reference. Point at an uploaded file by its **bare filename** (`target.pdb`, NOT the `{email}/target.pdb` S3 key, which 400s as `"... has not been uploaded"`), or `JobName/...` for a prior job's output.
- **PepMLM `numDesigns` as a free integer.** It is a dropdown; only `[1,2,4,8,16,32]` are valid.
- **BoltzGen target with gaps / insertion codes** in its residue numbering raises a clear input error; clean the numbering before submitting.
- **Building a submit from `validateJob`'s `normalized` blob.** `normalized` is informational (defaults filled in, sometimes platform-managed fields). Submit the clean `settings` you validated.

## Output shapes (describe, don't expect golden numbers)

Binder outputs are non-deterministic (seed/model/MSA), so reason about ranking and shape.

- **Job row `Score`** (JSON on completed jobs): interface metrics, family-dependent. Folding-validated designs carry pLDDT/pTM plus ipTM/ipSAE/pDockQ for the interface (higher = more confident). Read the keys present, do not assume.
- **Results zip** per tool: BindCraft `Accepted/` + `final_design_stats.csv`; BoltzGen `final_ranked_designs/` + `all_designs_metrics.csv` + `results_overview.pdf`; RFdiffusion/RFdiffusion3 per-design `.pdb`/`.cif` + a scores CSV. Enumerate with `listJobFiles(jobName)` before downloading.
- **Ranking:** run `scripts/summarize_binder_metrics.py <results-dir>` to rank by the auto-detected interface metric (ipSAE / ipTM / pDockQ / pLDDT) and report max / 10th-best / fraction-above-cutoff. A passing CSV is necessary, not sufficient: pull at least one actual structure and check coordinates, sequence, and atom count (especially for a `skipRefolding` BoltzGen run).
- **`WeightedHours`** on the row is the billing unit (weighted hours; GPU tools cost more per wall-hour than CPU tools).
