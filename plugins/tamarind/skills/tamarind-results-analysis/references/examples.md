# Tamarind Bio: read-back recipes and output shapes

Worked recipes for reading a job back, scoring it, and chaining it forward. `BASE = "https://app.tamarind.bio/api"`, `HEADERS = {"x-api-key": os.environ["TAMARIND_API_KEY"]}`. The MCP variants (`getJobs` / `listJobFiles` / `getJobLogs`) are preferred where the host has them; the REST/client variants are the floor. Sequences and job names here are illustrative; swap your own.

## Self-check (read-only, no cost)

Confirms the read-back loop works against a job you already have. Replace `my-job` with a real completed job name on your account:

```bash
python3 scripts/tamarind_job.py get my-job        # prints the row; JobStatus should be Complete
python3 scripts/tamarind_job.py download my-job   # two-step presigned -> my-job.zip
```

A row with `"JobStatus": "Complete"` and a non-empty `Score` means the loop is good. A 401 means the key is missing or wrong (run `tamarind-api-setup`).

## Recipe 1: read status, then interpret a fold's metrics

```bash
# 1. status (by-name row, no jobs wrapper)
python3 scripts/tamarind_job.py get my-fold

# 2. if Complete, download, unzip, and parse the per-model confidence
python3 scripts/tamarind_job.py download my-fold          # -> my-fold.zip
unzip -q my-fold.zip -d my-fold/                          # scripts take the DIRECTORY, not the .zip
python3 scripts/parse_boltz_confidence.py my-fold/         # ranked pLDDT/pTM/ipTM/ipSAE/pDockQ
python3 scripts/parse_boltz_confidence.py my-fold/ --iptm-cutoff 0.6 --json
```

The parse output ranks models by the tool's own selection metric (Boltz/Chai `confidence_score`, falling back to pTM) and flags any model whose interface confidence (ipTM/ipSAE below the cutoff, or pDockQ below ~0.23) is weak. For a complex, a high pLDDT with a low ipTM means the chains fold well individually but the interface is uncertain.

Reading `Score` directly off the row instead of the zip:

```python
import os, json, requests
BASE, H = "https://app.tamarind.bio/api", {"x-api-key": os.environ["TAMARIND_API_KEY"]}
row = requests.get(f"{BASE}/jobs", headers=H, params={"jobName": "my-fold"}).json()  # bare row
score = json.loads(row["Score"])           # Score is a JSON STRING, parse it
print(score.get("plddt"), score.get("ptm"), score.get("iptm"))   # read keys, don't assume
```

## Recipe 2: read a Stopped job's failure tail

```python
# MCP host:
logs = getJobLogs("my-fold")               # the worker's failure tail
# REST floor: the row's status + reason; download isn't available for a Stopped job
row = requests.get(f"{BASE}/jobs", headers=H, params={"jobName": "my-fold"}).json()
print(row["JobStatus"])                     # "Stopped"
```

A `Stopped` status with an OOM/timeout tail means re-running as-is repeats it; fix the input (or raise the budget / runtime) before re-submitting one test job, not the whole batch.

## Recipe 3: list outputs and download one file by its real name

```python
files = listJobFiles("my-fold")            # MCP: [{name, size, s3Path}, ...]
for f in files["files"]:
    print(f["name"], f["size"])
# download just the ranked-1 structure (two-step result with fileName)
url = requests.post(f"{BASE}/result", headers=H,
                    json={"jobName": "my-fold", "fileName": "rank_1.pdb"}).text.strip('"')
open("rank_1.pdb", "wb").write(requests.get(url).content)
```

Filenames vary by tool and version, so `listJobFiles` first and read the real names. REST `GET /files` is the WRONG call here (it lists account-wide uploads, not this job's outputs).

## Recipe 4: score a structure against a reference (DockQ)

`dockq` grades a model complex against a native one. Upload both (or chain a model from a prior job by `s3Path`), submit via `tamarind-submit-and-poll`, then read the score back here.

```json
{ "jobName": "grade-my-complex", "type": "dockq",
  "settings": { "modelFile": "model.pdb", "nativeFile": "native.pdb", "allowedMismatches": 0 } }
```

Chain identity/order between model and native must match, or the score is wrong rather than erroring. `allowedMismatches` covers small sequence differences (tags, point mutations) only after the chains correspond. The completed `Score` carries DockQ plus Fnat / iRMSD / LRMSD.

## Recipe 5: fold then score the interface (ipsae) by s3Path chaining

`ipsae` reads a folding job's confidence outputs directly. After an AlphaFold-style fold completes, point `ipsae` at its output files by `s3Path`, no download/upload:

```python
files = listJobFiles("my-fold")            # the AF2 fold's outputs
def path(suffix):
    return next(f["s3Path"] for f in files["files"] if f["name"].endswith(suffix))

submitJob("score-interface", "ipsae", {
    "inputType": "af2",
    "pdbFile":  path(".pdb"),               # chain by reference (s3Path), not by value
    "jsonFile": path(".json"),              # AF2 metrics JSON
    "pae_cutoff": 10, "dist_cutoff": 10,
})
```

For a Boltz fold use `inputType: "boltz"` and chain `cifFile` + `npzFile` + `plddtFile` + `confidenceFile` from the Boltz outputs the same way. Then read `score-interface` back with Recipe 1.

## Recipe 6: re-attach to a running job from a fresh session

```bash
# the job was submitted elsewhere; you have only its name
python3 scripts/tamarind_job.py get my-long-job          # In Queue / Running / Complete?
python3 scripts/tamarind_job.py wait my-long-job         # resumes polling to terminal
python3 scripts/tamarind_job.py download my-long-job     # then pull the result
```

`wait` is safe to start against an already-`Running` job (it re-reads the live row each poll) and returns immediately if the job is already terminal. The same `wait my-batch` is correct for a batch parent name (it auto-polls `batchStatus`).

## Recipe 7: chain any prior output forward by reference

The general move for any file-typed next-job setting (`pdbFile`, `modelFile`, `receptorFile`, ...):

```python
files = listJobFiles("design-run")
pdb = next(f["s3Path"] for f in files["files"] if f["name"].endswith(".pdb"))
submitJob("qc-the-design", "molprobity", {"pdbFile": pdb})   # s3Path straight in, no round-trip
```

Do NOT email-prefix a file reference: `{email}/{filename}` is the S3 key and 400s as not-uploaded. Use the `s3Path`, a `JobName/path.ext` output path, or a bare uploaded filename.

## Output shapes (describe, don't expect exact values)

- **Job row `Score`** (JSON string on completed jobs): tool-family dependent.
  - Folding (alphafold / boltz / chai / esmfold / protenix): `plddt`, `ptm`, and for complexes `iptm` plus interface metrics (`ipSAE_*`, `pDockQ_*`).
  - Scoring tools (dockq / pdockq / ipsae / molprobity / us-align / rmsd-calculator): the tool's own score keys (DockQ + components, ipSAE values, TM-score, RMSD, MolProbity score / clashscore).
  - Other families carry their own metrics; read the keys.
- **Results zip** (`POST /result` -> presigned URL -> GET): per-tool, typically structure files (`rank_*.pdb` / `*.cif`), a scores CSV, and logs. `listJobFiles(jobName)` enumerates the exact names.
- **`WeightedHours`** on the row is the billing unit (one number per job scaling with runtime + GPU tier).

To learn a specific tool's exact outputs, run one small job and `listJobFiles` it; don't hardcode filenames, which vary by tool and version.
