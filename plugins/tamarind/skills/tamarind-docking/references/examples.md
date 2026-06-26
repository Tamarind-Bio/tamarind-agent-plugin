# Tamarind docking: validated examples & output shapes

The freshest example for any tool is the `exampleJob` field that `getJobSchema(<tool>)` returns (an `{jobName, type, settings}` built from each param's example/default). It is the best starting point, but **run `validateJob` on it before submitting**: it is assembled from per-param examples, not a guaranteed-valid payload. The payloads below are a `validateJob`-confirmed fallback for REST callers or a worked example. Schemas evolve, so if one stops validating, re-fetch with `getJobSchema(<tool>)` / `GET /tools`. The receptor / ligand here are a benign, well-known research target (a kinase with an approved inhibitor); swap your own.

File params (`receptorFile`, `proteinFile`, `ligandFile`, `wildtypeFile`, `mutantFile`) need a real file value: the **bare filename** of an uploaded file (`receptor.pdb`, NOT email-prefixed), a prior-job output path (`JobName/out/x.pdb`), or inline file content. A plain string in a file field is treated as INLINE content. The `1iep.pdb` / `6w70.pdb` names below are recognized platform example files, so the payloads validate as-is; for your own structure, upload first and pass the returned bare name.

`BASE = "https://app.tamarind.bio/api"`, `HEADERS = {"x-api-key": <key>}`.

## Self-check (run this first)

Read-only + dry-run, no submission, no cost. Confirms the discover -> schema -> validate loop end to end:

```python
import os, requests
BASE, HEADERS = "https://app.tamarind.bio/api", {"x-api-key": os.environ["TAMARIND_API_KEY"]}

# 1. discovery reachable?
tools = requests.get(f"{BASE}/tools", headers=HEADERS).json()
assert isinstance(tools, list) and any(t["name"] == "autodock-vina" for t in tools), "tools endpoint"

# 2. validate a known-good payload (MCP validateJob; skip if REST-only) -> expect {"valid": true, ...}
```

With the MCP server: `validateJob(jobName="selfcheck", type="diffdock", settings={"proteinFile": "6w70.pdb", "ligandFormat": "SMILES", "ligandSmiles": "CC(=O)Oc1ccccc1C(=O)O"})` -> `valid: true`.

## Validated input payloads

Each below returned `valid:true` from `validateJob` against the live API (except `prodigy` / `binding-ddg`, which are schema-correct but file-gated, see the note on each).

### Autodock Vina, dock a SDF ligand into a known pocket box
```json
{ "receptorFile": "1iep.pdb",
  "ligandFormat": "sdf",
  "ligandFile": "ligand.sdf",
  "boxX": 15.19, "boxY": 53.903, "boxZ": 16.917,
  "width": 20, "height": 20, "depth": 20,
  "exhaustiveness": 8 }
```
`receptorFile` (not `proteinFile`) is the protein. `ligandFormat` is **lowercase** (`"sdf"` / `"smiles"`). The bounding box is all-required: a center (`boxX/Y/Z`) plus dimensions (`width/height/depth`). The center defaults to `0,0,0`, which misses the protein, so supply real coordinates from a known ligand centroid, a pocket residue centroid, or a pocket-detection job. Size the box to the pocket (~20-30 Angstroms), not the protein.

### Autodock Vina, SMILES library screen against one receptor box
```json
{ "receptorFile": "1iep.pdb",
  "ligandFormat": "smiles",
  "ligandSmiles": "Cc1ccc(cc1Nc2nccc(n2)c3cccnc3)NC(=O)c4ccc(cc4)CN5CCN(CC5)C",
  "boxX": 15.19, "boxY": 53.903, "boxZ": 16.917,
  "width": 20, "height": 20, "depth": 20,
  "exhaustiveness": 8 }
```
`ligandFormat:"smiles"` switches the conditional field to `ligandSmiles`. Pass one SMILES, or upload a `.smi`/`.csv` with one SMILES per row to dock MANY ligands against the same receptor box (the cheap way to screen). SMILES are converted to a single 3D conformer with OpenBabel, so for multi-stereocenter / strained-ring / macrocyclic ligands pre-generate conformers and submit as SDF instead. `validateJob`-confirmed.

### DiffDock, blind docking with a SMILES ligand (no box)
```json
{ "proteinFile": "6w70.pdb",
  "ligandFormat": "SMILES",
  "ligandSmiles": "CC(=O)Oc1ccccc1C(=O)O" }
```
DiffDock uses `proteinFile` (not `receptorFile`) and a DIFFERENT `ligandFormat` enum: `"SMILES"` (capital) or `"sdf/mol2 file"`, NOT Vina's lowercase strings. No box, it finds the site itself. The SMILES must be a single connected ligand (a `.` for disconnected fragments / salts is rejected). For an SDF/MOL2 ligand, set `ligandFormat:"sdf/mol2 file"` and `ligandFile`. `validateJob`-confirmed.

### GNINA, CNN-rescored dock (SDF ligand only)
```json
{ "proteinFile": "1iep.pdb",
  "ligandFile": "ligand.sdf",
  "boxX": 15.19, "boxY": 53.903, "boxZ": 16.917,
  "width": 20, "height": 20, "depth": 20,
  "cnnScoring": "rescore",
  "exhaustiveness": 8,
  "wholeProtein": false,
  "scoreOnly": false }
```
gnina takes an SDF ligand only (no SMILES branch); convert a SMILES to a 3D SDF first. `cnnScoring` (`none`/`rescore`/`refinement`/`metrorefine`) sets how much CNN scoring is applied. Set `wholeProtein:true` for blind whole-protein docking (the box is then ignored). `validateJob`-confirmed.

### GNINA, score an existing pose without re-docking
```json
{ "proteinFile": "1iep.pdb",
  "ligandFile": "pose.sdf",
  "boxX": 15.19, "boxY": 53.903, "boxZ": 16.917,
  "width": 20, "height": 20, "depth": 20,
  "scoreOnly": true }
```
`scoreOnly:true` returns the CNN affinity + pose score for the INPUT conformation as-is, without docking. Use it to rescore a DiffDock or cofold pose. (Pass an SDF that already holds the pose you want scored.)

### PRODIGY, absolute protein-protein affinity from one complex
```json
{ "proteinFile": "ppi_complex.pdb" }
```
The only field is the COMPLEX structure (both partners in one PDB). PRODIGY returns dG + Kd; it does not dock, the structure must already contain the bound pose. Schema-correct, but `validateJob` returns `valid:false` ("File ... has not been uploaded") until you upload the PDB, which is the expected file-gated response, not a settings error.

### Binding ddG, effect of a mutation on binding
```json
{ "wildtypeFile": "wildtype_complex.pdb",
  "mutantFile": "mutant_complex.pdb" }
```
Compares a wildtype vs mutant COMPLEX (a delta). The two PDBs must be SAME LENGTH (a paired-structure delta; an indel or chain-count mismatch misaligns). Output is a single ddG float (negative = mutation stabilizes binding). Schema-correct, file-gated until both PDBs are uploaded.

### Batch, screen many ligands through one docker
```json
{ "batchName": "vina-screen-1", "type": "autodock-vina",
  "jobNames": ["lig1", "lig2"],
  "settings": [
    { "receptorFile": "1iep.pdb", "ligandFormat": "smiles", "ligandSmiles": "CC(=O)Oc1ccccc1C(=O)O",
      "boxX": 15.19, "boxY": 53.903, "boxZ": 16.917, "width": 20, "height": 20, "depth": 20 },
    { "receptorFile": "1iep.pdb", "ligandFormat": "smiles", "ligandSmiles": "CCO",
      "boxX": 15.19, "boxY": 53.903, "boxZ": 16.917, "width": 20, "height": 20, "depth": 20 } ] }
```
One subjob per ligand against the same receptor box. Poll the batch PARENT on `batchStatus` (not subjob `JobStatus`). For a single-receptor screen, Vina's CSV-of-SMILES path is the lighter alternative to a batch. See `tamarind-batch`.

## What fails (and the exact error), confirmed live

- **A docking job with the box left at the origin** (`boxX/Y/Z` all 0) -> validates fine but the search misses the protein and returns garbage or times out. Not a validation error, a SILENT mis-dock; always set a real box center or use `wholeProtein` / an ML docker.
- **Copying DiffDock's `ligandFormat:"SMILES"` into Autodock Vina** -> Vina's enum is lowercase `"smiles"`; the capital string is invalid. The receptor field also differs (`receptorFile` vs `proteinFile`). Read each tool's `getJobSchema`; do not copy fields across siblings.
- **A multi-fragment SMILES into DiffDock** (a `.` in `ligandSmiles`, e.g. a salt) -> rejected as not a single connected ligand. Strip counterions first.
- **A SMILES into gnina / smina** -> no SMILES branch in those schemas; the ligand field expects an SDF. Convert to a 3D SDF first.
- **A file param given a bare string that isn't a real path** -> treated as INLINE file content, not a reference. Point at an uploaded file by its bare filename (`receptor.pdb`, NOT email-prefixed), or a prior job's output by `JobName/path/to/file.ext`. An email-prefixed key 400s as not-uploaded.

## Output shapes (describe, don't expect exact values)

Outputs depend on the tool family, so reason about the metric SHAPE, not golden numbers.

- **Box / physics dockers** (Vina, smina): the results zip has the docked pose(s) (`ligand_out.{sdf,pdb,pdbqt}`) and a `log.txt` with the binding-affinity table in kcal/mol per pose. **More negative is better.**
- **gnina:** docked poses (`out/result.sdf`), a combined receptor+ligand PDB, and `out/log.txt` with a CNN affinity + pose score. `scoreOnly` returns the input pose's score with the ligand copied through.
- **DiffDock:** confidence-ranked pose files (`rank*.sdf`), multiple ranks, no physics energy. Higher confidence is better; ordering IS the rank.
- **PRODIGY:** an `output.csv` with predicted binding affinity (dG), dissociation constant (Kd), and interfacial-contact counts.
- **binding-ddg:** a single predicted ddG float on the row `Score` and in a one-row `results.csv`.
- **Job row `Score`** (a JSON STRING on completed jobs): carries the headline metric for the tool family (a docking affinity, a CNN score, a dG/ddG). Read the keys; do not assume.
- **`WeightedHours`** on the row is the billing unit. Classical CPU dockers (Vina/smina) are cheap; the main cost/time blowup is an oversized box. GPU/ML dockers cost more.

Rank and write the top poses with `scripts/extract_docking_poses.py <run-dir>` (auto-detects Vina/gnina/smina affinity vs DiffDock confidence). To learn a specific tool's exact outputs, run one small job and `listJobFiles` it; don't hardcode filenames, which vary by tool and version. And verify at least one actual output pose (ligand intact, sitting in the intended pocket, distinct ranks not byte-identical) before trusting a job, since the score table can pass while the geometry is wrong.
