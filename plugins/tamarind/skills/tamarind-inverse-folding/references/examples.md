# Inverse folding and PLMs: validated payloads, chaining, what fails

The freshest example for any tool is the `exampleJob` that MCP `getJobSchema(<tool>)` returns (a `{jobName, type, settings}` built from each param's example/default, with file params as placeholders). It is the best starting point, but **run `validateJob` on it before submitting**: it is assembled from per-param examples, not a guaranteed-valid payload. The payloads below are a `validateJob`-confirmed fallback for REST callers or a worked example. Tool schemas evolve; if one stops validating, re-fetch with `getJobSchema(<tool>)`.

`BASE = "https://app.tamarind.bio/api"`, `HEADERS = {"x-api-key": <key>}`. Settings go in the `settings` field of a `submitJob` / `POST /submit-job` call.

**File params (`pdbFile`) need a real file value:** the **bare filename** of an uploaded file (`backbone.pdb`, NOT email-prefixed), a prior-job output path (`JobName/out/x.pdb`), or inline PDB text (multi-line `ATOM`/`HETATM` records). A `backbone.pdb` placeholder is NOT valid until you upload a real structure and pass its bare name; `validateJob` does a real file-existence check and returns `valid:false` until then. Sequence params (`sequence`) take the amino-acid string directly, so a PLM payload is directly runnable with no upload.

## Validated input payloads (settings only)

### ProteinMPNN, redesign selected residues
```json
{"pdbFile": "backbone.pdb",
 "designedResidues": {"B": "26 27 28 29 30 31 32"},
 "numSequences": 4, "temperature": 0.1, "modelType": "proteinmpnn", "omitAAs": "C"}
```
`designedResidues` are PDB author numbers, space-separated within a chain. An empty value for a chain (`{"B": ""}`) redesigns that whole chain. Switch `modelType` to `solublempnn` / `hypermpnn` / `abmpnn` / `ligandmpnn` for the soluble / thermostable / antibody / cofactor-aware variant without changing tools.

### LigandMPNN, design around a fixed cofactor
```json
{"pdbFile": "enzyme_with_substrate.pdb",
 "designedResidues": {"A": "60 61 62 63 64 65 66"},
 "numSequences": 4, "temperature": 0.1, "omitAAs": "C"}
```
The uploaded PDB MUST contain the ligand/metal/nucleic-acid HETATM (or a separate chain). Strip it and LigandMPNN silently degenerates to plain ProteinMPNN.

### ESM-IF1, single-chain language-model inverse folding
```json
{"pdbFile": "backbone_renum.pdb", "chain": "A", "designedResidues": "62-70", "numSequences": 10}
```
`designedResidues` is a comma-separated RANGE string scoped to the single `chain` (not a per-chain dict). Renumber the chain 1..N before upload: ESM-IF1 expects 1..N indices, the opposite of the MPNN author-number rule.

### ESM-C 6B, mutational scan (sequence-only, directly runnable)
```json
{"task": "scan", "sequence": "MKTIIALSYIFCLVFADYKDDDDK"}
```
`task: embeddings` instead returns per-residue 2560-dim vectors and adds `outputFormat` / `layerPreset`.

### ESM2 embeddings (sequence-only, directly runnable)
```json
{"sequence": "QIVLTQSPAIMSASPGEKVTMTCSASSSVSYMNWYQQKSGTSPKRWIYDTSKLASGVPAHFRGSGSGTSYSLTISGMEAEDAATYYCQQWSSNPFTFGSGTKLEIN",
 "model": "esm2_t33_650M_UR50D", "outputFormat": "pt"}
```
`model` is the full size ladder (8M up to 15B); bigger = richer but more cost/time. Writes both pooled and per-residue tensors.

### ESM-C embeddings, pick a layer (sequence-only, directly runnable)
```json
{"sequence": "MKTIIALSYIFCLVFAD", "model": "esmc-600m", "outputFormat": "pt", "layer": "last"}
```
`layer` accepts `last` / `first` / a 1-indexed integer. Separate multimer chains with `:` (remapped to ESM-C's `|`).

### ProtT5-XL embeddings (sequence-only, directly runnable)
```json
{"sequence": "QIVLTQSPAIMSASPGEKVTMTCSASSSVSYMNWYQQKSGTSPKRWIYDTSKLASGVPAHFRGSGSGTSYSLTISGMEAEDAATYYCQQWSSNPFTFGSGTKLEIN"}
```
Fewest knobs (just `sequence`). Writes per-residue embeddings ONLY (no pooled vector); mean-pool yourself if a downstream step needs one per-sequence vector.

## Upload a backbone, then submit (the common first step for inverse folding)

Inverse folders need an uploaded structure first; PLMs do not (sequence is a string):

```python
import os, requests
BASE, HEADERS = "https://app.tamarind.bio/api", {"x-api-key": os.environ["TAMARIND_API_KEY"]}

# REST: PUT the file; reference it by the BARE filename afterward (NOT email-prefixed)
with open("my_backbone.pdb", "rb") as fh:
    requests.put(f"{BASE}/upload/my_backbone.pdb", headers=HEADERS, data=fh).raise_for_status()

requests.post(f"{BASE}/submit-job", headers=HEADERS, json={
    "jobName": "pmpnn-redesign", "type": "proteinmpnn",
    "settings": {"pdbFile": "my_backbone.pdb",
                 "designedResidues": {"B": "26 27 28 29 30 31 32"},
                 "numSequences": 4, "temperature": 0.1, "modelType": "proteinmpnn"},
}).raise_for_status()
```

MCP variant: `uploadFile("my_backbone.pdb")` returns a presigned URL, `curl -X PUT -T my_backbone.pdb "<url>"`, then pass the bare `"my_backbone.pdb"` as `pdbFile`.

## Chain: design sequences, then fold them back to verify

Inverse folding emits SEQUENCES, so verifying them is a fold step. Fold a designed sequence by passing it as a `sequence`, NOT through a file/template field. The cleanest design-then-fold chain is MCP `submitBatch(fromJob=...)`, which reads a completed design job's generated sequences and folds each as one job:

```
# proteinmpnn designs sequences (poll to Complete), then fold every one in one batch call:
submitBatch(batchName="fold-designs", type="esmfold", fromJob="my-proteinmpnn-job")
```

Do NOT route a designed sequence through a structural-template file param (e.g. an AlphaFold `templateFiles`): that is a structural template (gated, `.cif`-only, a list), not "fold this sequence." To fold a sequence, pass `sequence`. Use `listJobFiles(jobName)` to discover a job's exact output paths (`s3Path`) when you need to chain a FILE output. See `tamarind-submit-and-poll` references for the full chaining rules.

## What fails (and the exact signal)

- **MPNN `designedResidues` numbered 1..N instead of author numbers.** ProteinMPNN/LigandMPNN map the tokens to PDB author numbers directly; pre-renumbering to 1..N selects the wrong residues. (ESM-IF1 is the reverse: it REQUIRES 1..N.)
- **MPNN hotspot/residue separator wrong.** `designedResidues` is SPACE-separated within a chain (`"26 27 28"`), not comma-joined.
- **ESM-IF1 `designedResidues` as a per-chain dict.** It is a comma-separated RANGE string (`"62-70"`) scoped to the single `chain`, not the MPNN per-chain dict shape.
- **ESM-IF1 on a non-renumbered PDB.** A backbone starting at a nonzero residue number shifts the `62-70` selection. Renumber to 1..N first.
- **LigandMPNN with the ligand stripped.** No error, but the design silently ignores the (now absent) cofactor. Keep the HETATM/cofactor in the uploaded PDB.
- **A file param given a bare non-filename string** is treated as INLINE file content, not a reference. Point at an uploaded file by its **bare filename** (`backbone.pdb`, NOT the `{email}/backbone.pdb` S3 key, which 400s as `"... has not been uploaded"`), or `JobName/...` for a prior job's output.
- **Sending `verifySequences` (proteinmpnn) over the API.** It is tagged `exclude:["api","pipelines","batch"]`; it is a UI-only next-step field. Omit it.
- **Confusing `task: scan` with a ddG.** ESM-C 6B `scan` is a per-position LIKELIHOOD matrix (in-silico DMS), not a structure-conditioned ddG; for fold-stability ddG use `thermompnn` / `proteinmpnn-ddg` / `rosetta-ddg-prediction` (in `tamarind-developability`).
- **Building a submit from `validateJob`'s `normalized` blob.** `normalized` is informational (defaults filled in, sometimes platform-managed fields). Submit the clean `settings` you validated.

## Output shapes (describe, don't expect golden numbers)

PLM and inverse-folding outputs depend on seed / model / temperature, so reason about ranking and shape.

- **Inverse folding** (proteinmpnn / ligandmpnn / esm-if1): a FASTA of designed sequences (`seqs/...fa`) + a `metrics.csv` (per-sequence ProteinMPNN score / global score / recovery). Each header carries the sampling temperature and score. Rank by score, then fold the top designs back to verify (fold the designed sequence as a `sequence`, not a template).
- **Embeddings** (esm-embeddings / esmc-embeddings / prot-t5-embeddings): a `.pt`/`.json` tensor archive. ESM2 and ESM-C write BOTH pooled and per-residue; ProtT5 writes per-residue ONLY. Feed these to a downstream predictor / clustering / probe; there is no "score" to rank.
- **Masked-LM scan** (esmc-6b `scan` / esm2 `scan` / esmc-scan / esm-scan / amplify): a per-position x AA log-likelihood matrix (CSV/JSON). Rank candidate mutations by the matrix; a higher likelihood for a substitution = more tolerated.
- **Job row `Score`** carries the tool metrics; **`WeightedHours`** is the billing unit (weighted hours; GPU tools cost more per wall-hour than CPU tools, and the 6B/15B models are the slow/expensive end). Enumerate exact filenames with `listJobFiles(jobName)` before downloading; do not hardcode names, which vary by tool and version.
