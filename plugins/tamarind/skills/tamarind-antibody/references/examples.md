# Tamarind Bio: antibody example payloads

The freshest example for any tool is the `exampleJob` that MCP `getJobSchema(<tool>)`
returns: a `{jobName, type, settings}` assembled from each param's example/default (file
params get placeholder names). It is the best starting point, but **run `validateJob` on it
before submitting** - it is built from per-param examples, not a guaranteed-valid payload.
The payloads below are a worked fallback for REST callers. Schemas evolve; if one stops
validating, re-fetch with `getJobSchema(<tool>)`. Sequences here are illustrative; swap your
own.

**File params (`targetFile`, `pdbFile`, `antibodyFile`) need a real file value:** the **bare
filename** of an uploaded file (`antigen.pdb`, NOT email-prefixed), a prior-job output path
(`JobName/out/x.pdb`), or inline PDB text (multi-line `ATOM`/`HETATM` records). A `<...>`
placeholder is NOT valid as written; replace it. Don't put an amino-acid sequence in a file
param - a structure goes in a file, a sequence goes in `sequence1` / `sequence2`.

`BASE = "https://app.tamarind.bio/api"`, `HEADERS = {"x-api-key": <key>}`.

## Self-check (run this first, read-only, no cost)

```python
import os, requests
BASE, HEADERS = "https://app.tamarind.bio/api", {"x-api-key": os.environ["TAMARIND_API_KEY"]}
tools = requests.get(f"{BASE}/tools", headers=HEADERS).json()
assert any(t["name"] == "immunebuilder" for t in tools), "antibody tools reachable"
```

With the MCP, `validateJob(jobName="selfcheck", type="immunebuilder", settings={"modelType":"Nanobody","sequence1":"EVQLVESGGGVVQPGGSLRLSCAASGFTFNSYGMHWVRQAPGKGLEWVAFIRYDGGNKYYADSVKGRFTISRDNSKNTLYLQMKSLRAEDTAVYYCANLKDSRYSGSYYDYWGQGTLVTVS"})` returns `valid: true`.

## immunebuilder - antibody Fv (sequence-only, validates fast)

```json
{ "modelType": "Antibody",
  "sequence1": "EVQLVESGGGVVQPGGSLRLSCAASGFTFNSYGMHWVRQAPGKGLEWVAFIRYDGGNKYYADSVKGRFTISRDNSKNTLYLQMKSLRAEDTAVYYCANLKDSRYSGSYYDYWGQGTLVTVS",
  "sequence2": "VIWMTQSPSSLSASVGDRVTITCQASQDIRFYLNWYQQKPGKAPKLLISDASNMETGVPSRFSGSGSGTDFTFTISSLQPEDIATYYCQQYDNLPFTFGPGTKVDFK" }
```

Nanobody: `{"modelType": "Nanobody", "sequence1": "<VHH sequence>"}` (drop `sequence2`).
TCR: `{"modelType": "TCR", "sequence1": "<alpha>", "sequence2": "<beta>"}`. `modelType`
required; `sequence1` always required; `sequence2` required for Antibody + TCR.

## rfantibody - de novo nanobody CDR design against an epitope

```json
{ "task": "nanobody", "framework": "h-NbBCII10",
  "targetFile": "<uploaded-bare-filename-or-inline-PDB-text>",
  "antigenChains": ["A"],
  "hotspots": {"A": "305, 456"},
  "regions": ["hcdr1", "hcdr2", "hcdr3"],
  "numDesigns": 100, "temperature": 0.1 }
```

`task` + `targetFile` + `antigenChains` are required. `hotspots` are passed in ORIGINAL
chain+resnum form (the wrapper remaps to the merged target). Named frameworks
(`h-NbBCII10` nanobody / `hu-4D5-8_Fv` antibody) need no upload; `framework: "custom"`
unlocks `antibodyFile` + `heavyChain`/`lightChain` + custom CDR selection. Per-region length
knobs (`hcdr3Length` etc.) accept a fixed length, a range like `10-15`, or `auto`. Antibody
example: set `task: "antibody"`, `framework: "hu-4D5-8_Fv"`, and add the 3 light CDRs to
`regions`.

## igdesign - wet-lab-validated HCDR3 redesign on a complex

```json
{ "task": "antibody", "pdbFile": "<uploaded-bare-filename-or-inline-PDB-text>",
  "heavyChain": "B", "lightChain": "L", "antigenChain": "A",
  "regions": ["hcdr3"], "condition_on_antigen": true,
  "condition_on_light_chain": false, "numBatches": 1 }
```

A SINGLE `antigenChain` (not a list). `numBatches: 1` = 1000 designs; scale up after a first
pass. For a nanobody set `task: "nanobody"` and drop `lightChain`. IMGT-number the input PDB
if you hand-pick CDRs via `selectCDRIndices`.

## abmpnn - antibody-aware inverse folding (API shape)

```json
{ "pdbFile": "<uploaded-bare-filename-or-inline-PDB-text>",
  "detectCDRs": false,
  "designedResidues": {"B": "26 27 28 29 30 31 32 52 53 54 55 56 95 96 97 98 99 100 101 102"},
  "numSequences": 8, "temperature": 0.2, "omitAAs": "C" }
```

Over the API, do NOT pass `designedChains` (`exclude:["api"]`) or `verifySequences`
(`exclude:["api","pipelines","batch"]`) - both are silently dropped. Use `designedResidues`
(per-chain, space-separated resnums) with `detectCDRs: false`, OR `detectCDRs: true` +
`regions` (a subset of the 14 framework/CDR labels, e.g. `["CDRH1","CDRH2","CDRH3"]`).
Cysteine is omitted by default.

## Worked recipe: de novo design then rank

```bash
# 1. upload the antigen, design 100 nanobody candidates against the epitope
python3 scripts/tamarind_job.py upload antigen.pdb
python3 scripts/tamarind_job.py run rfab-run rfantibody '{"task":"nanobody","framework":"h-NbBCII10","targetFile":"antigen.pdb","antigenChains":["A"],"hotspots":{"A":"305, 456"},"regions":["hcdr1","hcdr2","hcdr3"],"numDesigns":100}'
# (run = submit + poll to terminal + download rfab-run.zip)

# 2. unzip and rank designs by interface confidence
unzip -q rfab-run.zip -d rfab-run
python3 scripts/summarize_binder_metrics.py rfab-run
```

`summarize_binder_metrics.py` ranks by ipSAE / ipTM / pDockQ / pLDDT (whichever the design
CSV carries) and reports max + 10th-best + fraction above a confidence cutoff. When
RFantibody's `calculateEpitopeDistance` is on, also check the min CDR-to-hotspot distance: a
high-scoring design that drifts off the epitope is not the binder you asked for.

## What fails (and why)

- **A sequence in a file param** (`targetFile`/`pdbFile`) is rejected - `validateJob` returns
  a file-type error. A structure goes in a file param; a sequence goes in `sequence1`.
- **An email-prefixed file key** (`{email}/antigen.pdb`) 400s as not-uploaded - it is treated
  as inline content, not a reference. Use the BARE filename.
- **Passing `designedChains` / `verifySequences` to abmpnn over the API** is silently dropped
  (they are `exclude`d for API callers) - use `designedResidues` / `detectCDRs` instead.
- **Building a submit from `validateJob`'s `normalized` echo** - submit the clean settings you
  validated, not the normalized blob (it carries filled-in defaults).

## Output shapes (describe, don't expect exact values)

Outputs are non-deterministic (seed / model / sampling temperature), so reason about the
shape, not golden numbers.

- **rfantibody:** per-design docked antibody/nanobody-antigen complex PDBs, designed CDR
  sequences, RF2 confidence/filter scores, and (when enabled) epitope-distance metrics.
- **igdesign:** a large pool of designed CDR sequences (1000 per batch) with design scores,
  ready for downstream folding/filtering.
- **abmpnn:** FASTA/CSV of designed sequences per backbone with per-sequence scores.
- **immunebuilder:** a single predicted PDB of the variable region (paired Fv, single-domain
  VHH, or paired TCR).
- **Job row `Score`** (JSON string on completed jobs) is tool-family dependent - read the
  keys, don't assume. `WeightedHours` on the row is the billing unit.

To learn a tool's exact output filenames, run one small job and `listJobFiles(jobName)`
before downloading; filenames vary by tool and version.
