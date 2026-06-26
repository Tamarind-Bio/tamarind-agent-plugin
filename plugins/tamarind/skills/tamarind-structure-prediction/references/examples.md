# Tamarind structure-prediction: validated examples & output shapes

The freshest example for any folder is the `exampleJob` field that `getJobSchema(<tool>)` returns (an `{jobName, type, settings}` built from each param's example/default). It is the best starting point, but **run `validateJob` on it before submitting**: it is assembled from per-param examples, not a guaranteed-valid payload. The payloads below are a `validateJob`-confirmed fallback for REST callers or a worked example. Schemas evolve, so if one stops validating, re-fetch with `getJobSchema(<tool>)` / `GET /tools`. Sequences here are illustrative; swap your own.

`BASE = "https://app.tamarind.bio/api"`, `HEADERS = {"x-api-key": <key>}`.

## Self-check (run this first)

Read-only + dry-run, no submission, no cost. Confirms the discover -> schema -> validate loop end to end:

```python
import os, requests
BASE, HEADERS = "https://app.tamarind.bio/api", {"x-api-key": os.environ["TAMARIND_API_KEY"]}

# 1. discovery reachable?
tools = requests.get(f"{BASE}/tools", headers=HEADERS).json()
assert isinstance(tools, list) and any(t["name"] == "alphafold" for t in tools), "tools endpoint"

# 2. validate a known-good payload (MCP validateJob; skip if REST-only) -> expect {"valid": true, ...}
```

With the MCP server: `validateJob(jobName="selfcheck", type="alphafold", settings={"sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIE"})` -> `valid: true`.

## Validated input payloads

Each below returned `valid:true` from `validateJob` against the live API.

### AlphaFold, monomer
```json
{ "sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKR",
  "numModels": "1", "numRecycles": 3, "msaDatabase": "uniref" }
```
Only `sequence` is required; everything else has a default. `numModels` is a string dropdown (`"1"`-`"5"`).

### AlphaFold, multimer (colon-separated chains)
```json
{ "sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIE:DIQMTQSPSSLSASVGDRVTITCRASQSISSYLN" }
```
Join chains with `:`. There is no separate "multimer" flag; the chain count drives it.

### Boltz-2, sequence mode
```json
{ "inputFormat": "sequence",
  "sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALP" }
```
`inputFormat` is **required** (`"sequence"` / `"list"` / `"molecules"` / `"yaml"`). Omitting it fails (see "What fails" below).

### Boltz-2, protein + SMILES ligand + binding affinity
```json
{ "inputFormat": "sequence",
  "sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALP",
  "addLigands": true,
  "ligands": ["CC(=O)Oc1ccccc1C(=O)O"],
  "predictAffinity": true,
  "version": "2.2.1",
  "numSamples": 5 }
```
`addLigands:true` gates the `ligands` list (bare CCD codes or SMILES, `:`-separated for multiple in one prediction). `predictAffinity` needs `version:"2.2.1"`; it scores the ligand's chain by default (`binderChain` overrides, chains assigned in input order). boltz is the only folder here with an affinity head.

### ESMFold2, fast single-sequence fold
```json
{ "inputFormat": "sequence", "sequence": "MKTIIALSYIFCLVFAD", "model": "esmfold2", "numLoops": 3 }
```
`model` is `esmfold2` (full) or `esmfold2-fast` (no MSA, faster, smaller GPU). Total length across chains is capped at 2000 residues. For a faster MSA-free run on the full model, set `useMSA:false`.

### Protenix-v2, complex (strong on antibody-antigen interfaces)
```json
{ "inputFormat": "sequence",
  "sequence": "TRPNHTIYINNLNEKIKKDELKKSLHAIFSRFGQILDILVSRSLK:MRGQAFVIFKEVSSATNALRSMQGFPFYDKPMRIQYAKTDSDIIAKM",
  "numSamples": 5, "numRecycles": 10 }
```
Required `inputFormat` (`"sequence"` / `"list"`). For ligands, set `addLigands:true` and prefix CCD codes with `CCD_` (e.g. `CCD_ATP:CCD_MG`), or pass raw SMILES. The constraint model variant adds pocket/contact restraints.

### Chai-1, complex
```json
{ "inputFormat": "sequence",
  "sequence": "TRPNHTIYINNLNEKIKKDELKKSLHAIFSRFGQILDILVSRSLK:MRGQAFVIFKEVSSATNALRSMQGFPFYDKPMRIQYAKTDSDIIAKM",
  "msaDatabase": "uniref" }
```
Set `useMSA:false` to swap the real MSA for a language-model embedding (~90% accuracy, faster). `molecules` mode adds a `glycan` entity type. Total structures = `numTrunkSamples` x `numSamples`.

### Precomputed MSA (boltz) instead of generating one
```json
{ "inputFormat": "sequence",
  "sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIE:DIQMTQSPSSLSASVGDRVTITCRASQSISSYLN",
  "version": "2.2.1",
  "a3mFiles": ["chain_a.a3m", "chain_b.a3m"],
  "a3mMapping": [ {"a3mName": "chain_a.a3m", "boltzChainID": "A"},
                  {"a3mName": "chain_b.a3m", "boltzChainID": "B"} ] }
```
Upload each `.a3m` first (reference by bare filename). **An a3m is matched to its chain by query sequence, not by filename**: the first sequence in `chain_a.a3m` must equal chain A's sequence. MSA generation is skipped for any chain you supply an a3m for. `a3mFiles`/`a3mMapping` are gated on `version:"2.2.1"` (confirm with `getJobSchema`).

### Batch, same folder, many sequences
```json
{ "batchName": "fold-screen-1", "type": "alphafold",
  "jobNames": ["seq1", "seq2"],
  "settings": [ { "sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIE" },
                { "sequence": "DIQMTQSPSSLSASVGDRVTITCRASQSISSYLN" } ] }
```
Poll the batch PARENT on `batchStatus` (not subjob `JobStatus`). See `tamarind-batch`.

## What fails (and the exact error), confirmed live

- **Boltz without `inputFormat`** -> `valid:false`, `Missing required boltz field "inputFormat"`. `sequence` alone is not enough for boltz/chai/protenix; always check required fields with `getJobSchema` first.
- **Building a submit from validateJob's `normalized` blob** -> `normalized` is informational (defaults filled in, sometimes platform-managed fields). Submit the clean `settings` you validated, not the normalized echo.
- **A file param (`templateFiles`, `a3mFiles`, `initialGuess`) given a bare string that isn't a real path** -> treated as INLINE file content, not a reference. Point at an uploaded file by its bare filename (`template.cif`, NOT email-prefixed), or reference a prior job's output by the `JobName/path/to/file.ext` form. An email-prefixed key 400s as not-uploaded.
- **A ligand value copied from boltz into protenix** -> protenix needs the `CCD_` prefix on CCD codes (`CCD_ATP`), so a bare `ATP` will not resolve. SMILES strings are portable; CCD codes are not.

## Output shapes (describe, don't expect exact values)

Outputs are non-deterministic (seed / model / MSA), so reason about the SHAPE, not golden numbers.

- **Job row `Score`** (a JSON STRING on completed jobs): for folding (alphafold/boltz/chai/esmfold2/protenix) carries `plddt`, `ptm`, and for complexes `iptm` plus interface metrics (ipSAE, pDockQ). Higher pLDDT/pTM = more confident; ipTM/ipSAE/pDockQ gauge interface quality. A boltz affinity job adds an affinity score.
- **Results zip** (`POST /result` -> presigned URL -> GET): typically the structure files (`rank_*.pdb` / `*.cif`), a per-model scores CSV, and logs. Use `listJobFiles(jobName)` (MCP) to enumerate exact filenames before downloading.
- **`WeightedHours`** on the row is the billing unit (it scales with runtime and GPU tier; GPU folders cost more than CPU tools, and `numSamples`/`numModels`/`numBatches` multiply it).

Rank and flag the models with `scripts/parse_boltz_confidence.py <run-dir>` (works across boltz/chai/alphafold/protenix/esmfold2 output). To learn a specific folder's exact outputs, run one small job and `listJobFiles` it; don't hardcode filenames, which vary by tool and version. And verify at least one actual output structure (chain count, sequence, atom count) before trusting a job, since the metrics CSV can pass while the structure is wrong.
