---
name: tamarind-results-analysis
description: "Use to read back a Tamarind Bio job after it runs: check status, fetch and interpret the confidence metrics (pLDDT, pTM, PAE, ipTM, ipSAE, pDockQ, binding affinity), list and download the output files, score a result against a reference (DockQ, MolProbity, US-align, RMSD), and chain an output into the next job by s3Path reference instead of downloading and re-uploading. Also re-attach to a still-running job by name from a fresh session. Not for submitting a job (use tamarind-submit-and-poll), not for running ONE tool across MANY inputs (use tamarind-batch)."
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: read back and analyze results

A third of an agent's job on Tamarind is reading results back. This skill covers the post-submit half of the loop: **check status, interpret metrics, list and download files, score the result, and chain it forward.** It does not submit jobs (that is `tamarind-submit-and-poll`); it reads the job a submit produced and turns it into a decision or the next job's input.

Jobs are **addressable by name from any process**, so you can read back a job submitted in another session, or re-attach to one still running, with nothing but its name (see "Re-attach to a running job" below). If `TAMARIND_API_KEY` is unset or a call returns 401, run `tamarind-api-setup` first.

## Two surfaces (MCP preferred when present, REST is the floor)

- **MCP server** (`https://mcp.tamarind.bio/mcp`, `X-API-Key` header). When the host has the Tamarind MCP, prefer it for the read-back: `getJobs(jobName)` for status, `getJobLogs(jobName)` for the failure tail, `listJobFiles(jobName)` for the per-job output list **and the `s3Path` you chain with**, `getResult` / `getJobFile` for downloads. Only the MCP can enumerate a single job's outputs (REST `/files` is account-wide, see below).
- **REST API** (base `https://app.tamarind.bio/api/`, `x-api-key` header). The universal floor. The bundled client below does status, the two-step result download, and uploads over plain REST with no MCP at all. Per-job file enumeration is the one read-back capability REST can't do; the client raises and points you at the MCP for it.

## The bundled client

This skill ships the thin REST client at `scripts/tamarind_client.py` (stdlib + `requests`, reads `TAMARIND_API_KEY`) plus three analysis scripts (`parse_boltz_confidence.py`, `extract_docking_poses.py`, `summarize_binder_metrics.py`) and their shared helpers (`_common.py`). **Run the client through the CLI wrapper `scripts/tamarind_job.py`, not a bare import** (the module lives in `scripts/`, so `from tamarind_client import ...` only resolves from `scripts/` itself; the wrapper puts its own dir on `sys.path[0]` so it works from any cwd):

```bash
python3 scripts/tamarind_job.py get      my-fold      # one status read, prints the row
python3 scripts/tamarind_job.py wait     my-fold      # poll to terminal, prints the final row
python3 scripts/tamarind_job.py download my-fold      # two-step presigned -> my-fold.zip
```

Probe the deps first; install only if the import fails:

```bash
python3 -c "import requests" 2>/dev/null \
  || python3 -m pip install -r scripts/requirements.txt \
  || python3 -m pip install --user --break-system-packages -r scripts/requirements.txt
```

The structure-parsing analysis scripts also need `gemmi` + `numpy`:

```bash
python3 -c "import gemmi, numpy" 2>/dev/null \
  || python3 -m pip install -r scripts/requirements.txt \
  || python3 -m pip install --user --break-system-packages -r scripts/requirements.txt
```

## 1. Check status

`getJobs(jobName)` (MCP) or `GET /jobs?jobName=<name>` returns the job **row directly** (no `jobs` wrapper, do not index `["jobs"][0]`). A single job carries `JobStatus`; a batch **parent** (`Type: "batch"`) carries `batchStatus` and aggregates after the subjobs finish, so read `batchStatus` on a batch, not subjob `JobStatus`.

| Status | Meaning |
|---|---|
| `In Queue` | Accepted, waiting for capacity |
| `Running` | Executing on a worker |
| `Complete` | Finished, results available |
| `Stopped` | Failure, timeout, manual stop, or budget |
| `Deleted` | Deleted out-of-band |

Treat `Complete` / `Stopped` / `Deleted` (and `Failed`) as terminal. For a `Stopped` job, read the tail with MCP `getJobLogs(jobName)` to see why (bad input, OOM, timeout, budget) before re-running. A completed row carries `Score` (tool metrics, a JSON string), `WeightedHours` (the billing unit), and timing fields.

**Scope every read; large results offload to a file.** Always pass `jobName=` (or `batch=`) on `getJobs`. A wide unscoped `getJobs` (over a big account) or a batch whose subjobs carry long per-residue `Score` arrays, and occasionally a large `getJobSchema`, can exceed the MCP result token cap. When that happens the MCP saves the full result to a local file and returns a pointer (`result (NNN characters) exceeds maximum allowed tokens. Output saved to <path>`). Do NOT try to re-read the whole payload: `jq`/`grep` the saved file for just the fields you need (a row's `JobStatus`, a schema's required params). `getJobs` already drops the bulky `Sequence`/`Settings` input blob by default, so the offload comes from the retained `Score` field over many rows, scoping the read is what avoids it.

## 2. Re-attach to a running job by name (across sessions)

A job name is a durable handle, so the submitting process does not have to be the one that reads it back. Submit in one session, persist the job name, and read or finish-waiting from a fresh session, another machine, or after a restart:

```bash
# session A (or another skill): submit, then record the name somewhere durable
python3 scripts/tamarind_job.py get my-fold        # confirm it exists

# session B, hours later, different process:
python3 scripts/tamarind_job.py wait my-fold       # resumes polling to terminal
python3 scripts/tamarind_job.py download my-fold   # then pull the result
```

`wait` re-derives state from the live row each poll, so it is safe to start a fresh wait against a job already `Running` (or already `Complete`, it returns immediately). It auto-discriminates a batch parent from a single job, so the same `wait my-batch` is correct for a batch name too. There is no client-side state to lose: the platform is the source of truth, keyed by name.

## 3. List and download output files

Two different "files" surfaces, do not confuse them:

- **Per-job outputs**: MCP `listJobFiles(jobName)` returns each output file with its size and **`s3Path`** (the field you chain with, see below). This is the only way to enumerate one job's outputs.
- **Account-wide uploads**: REST `GET /files` is a flat list of your uploaded filenames across the whole account, **not** a job's outputs. The bundled `list_job_files` raises on purpose and points you at the MCP, rather than silently returning the wrong list. There is **no REST per-job file-list endpoint** (a hand-rolled `POST /list-job-files` returns non-JSON); per-job enumeration is MCP `listJobFiles` only.

Download the whole result, or one file:

```bash
python3 scripts/tamarind_job.py download my-fold              # whole zip -> my-fold.zip
# one file or PDBs-only via the client's result_url(file_name=..., pdbs_only=True)
```

`download` is the two-step presigned flow: `POST /result` returns a presigned URL as a **bare string**, then a GET on that URL pulls the bytes. Filenames vary by tool and version, so `listJobFiles` first and read the real names rather than hardcoding them.

## 4. Fetch and interpret metrics

The completed row's `Score` is a **JSON string** (parse it, it is not a nested object). The keys are tool-family dependent, so read the keys rather than assuming them. The recurring confidence metrics:

| Metric | Scale | Reads as |
|---|---|---|
| pLDDT | 0-100 | Per-residue / mean local confidence (stored in the PDB B-factor column). Higher is better; >70 is generally well-modeled, >90 high. |
| pTM | 0-1 | Global fold confidence. Higher is better. |
| PAE | Angstroms | Predicted aligned error between residue pairs (a matrix). LOWER is better; low off-diagonal blocks mean a confidently-placed interface. |
| ipTM | 0-1 | Interface predicted TM-score (complex interface confidence). Higher is better; a common acceptable cutoff is ~0.6. |
| ipSAE | 0-1 | Interface score from AlphaFold/Boltz confidence outputs. Higher is better; ranks predicted interfaces. |
| pDockQ | 0-1 | Predicted DockQ (interface quality estimate from one structure). Higher is better; ~0.23 is a conventional acceptable-interface floor. |
| affinity | tool-specific | Binding affinity (docking score in kcal/mol where MORE NEGATIVE is better, or a predicted pKd/probability). Read the tool's own key and direction. |

The bundled scripts parse and rank these for you so you don't hand-roll the column-name aliasing (CSV spellings differ across Boltz, Chai, AlphaFold, Protenix):

```bash
# structure prediction / co-folding: per-model pLDDT/pTM/ipTM/ipSAE/pDockQ, ranked, low-interface flagged
# (the analysis scripts take the unzipped result DIRECTORY, not the .zip)
unzip -q my-fold.zip -d my-fold/
python3 scripts/parse_boltz_confidence.py my-fold/
python3 scripts/parse_boltz_confidence.py my-fold/ --iptm-cutoff 0.6 --json

# docking: per-pose affinity (Vina/gnina) or confidence (DiffDock), ranked; writes top-N poses
python3 scripts/extract_docking_poses.py dock-run/ --top 5

# binder / antibody design: rank designs by interface metric, report max + 10th-best + frac above cutoff
python3 scripts/summarize_binder_metrics.py design-run/ --metric ipsae --cutoff 0.7
```

For a per-residue read straight off the structure, `_common.residue_plddt(chain)` returns the mean B-factor (= pLDDT) per residue from a downloaded CIF/PDB.

**Verify the artifact, not just the metric.** A passing metrics CSV can sit next to stub or identical output structures, so for a consequential result open at least one actual output (PDB/CIF/SDF) and sanity-check coordinates, sequence, and atom count, rather than trusting the CSV alone.

## 5. Score a result against a reference (the QC and alignment tools)

When you want a number for "how good is this structure" beyond the model's own confidence, submit one of these scoring tools (they are normal jobs, run them via `tamarind-submit-and-poll`, then read the result back here). All take a **bare uploaded filename** or, better, a **prior job's `s3Path`** for chaining (section 6). Confirm exact params live with `getJobSchema(<tool>)`; the live schema is authoritative.

| Tool | Use it to | Key inputs (from live `getJobSchema`) |
|---|---|---|
| `dockq` | Grade a model complex against a native/reference complex (CAPRI-style: DockQ + Fnat/iRMSD/LRMSD) | `modelFile`, `nativeFile` (both pdb), optional `allowedMismatches` |
| `pdockq` | Predict a DockQ-style interface score from a SINGLE complex (no reference needed) | `pdbFile` |
| `ipsae` | Interface scoring (ipSAE/iCS) from AlphaFold or Boltz confidence outputs | `inputType` (`af2`/`boltz`); af2 needs `pdbFile`+`jsonFile`, boltz needs `cifFile`+`npzFile`+`plddtFile`+`confidenceFile`; `pae_cutoff`/`dist_cutoff` (default 10) |
| `molprobity` | Validate structure geometry (clashes, rotamers, Ramachandran) | `pdbFile` |
| `us-align` | Pairwise structural superposition + TM-score (proteins and nucleic acids) | `pdbFile1`, `pdbFile2`, `mm_opt` (monomer vs multi-chain vs circular-permuted) |
| `rmsd-calculator` | Single pairwise RMSD between two structures (protein or ligand) | `pdbFile1`, `pdbFile2`, `rmsdType` (`protein`/`ligand`); per-chain via `specifyChains` |
| `protein-metrics` | Rank/filter designed proteins (COMPSS) with an ensemble of pLM + inverse-folding likelihoods (ESM-IF / ProteinMPNN / ESM-1v); a design-filter scorer that also doubles as a developability read | `metricType` (`Single Sequence Metrics` needs `sequence`; `Structure Metrics` needs `pdbFile`) |
| `pdbsum` | Structural summary diagrams (chains, DNA, ligands, metals) | `pdbFile` |

The `ipsae` inputs come straight from a folding job's outputs (the AF2 `pdbFile`+metrics `jsonFile`, or the Boltz `cifFile`+`npzFile`+`plddtFile`+`confidenceFile`), so it is the natural fold-then-score chain. `dockq` needs the right chain correspondence between model and native, or the score is wrong rather than erroring; bump `allowedMismatches` for small sequence differences (tags, point mutations) only after the chains map.

These eight are the established, most-run QC / scoring tools. For one not in this table, discover it live with `getAvailableTools` (filter by the relevant function/tag), then `getJobSchema(<tool>)` for its params.

## 6. Chain an output into the next job by reference (not by value)

The key efficiency move: do **not** download a prior job's output and re-upload it. `listJobFiles(jobName)` returns an `s3Path` per file, and that `s3Path` is accepted directly as a file-typed setting on the next job:

```python
files = listJobFiles("my-fold")                 # MCP: each entry has name, size, s3Path
pdb = next(f["s3Path"] for f in files["files"] if f["name"].endswith(".pdb"))
submitJob("score-it", "molprobity", {"pdbFile": pdb})   # chain by reference
```

Three ways to reference a file in a file-typed setting (`pdbFile`, `modelFile`, `receptorFile`, ...):

1. **`s3Path` from `listJobFiles`** (best for chaining, no download/upload round-trip).
2. **A prior job's output path** `JobName/relative/path.ext` (the by-path form when you don't have the MCP).
3. **A bare uploaded filename** `target.pdb` (after uploading; the client's `upload_file` returns this bare name).

Foot-gun: a plain string in a file-typed field that is NOT a real path is treated as **inline file content**, not a reference, and an **email-prefixed** key (`{email}/{filename}`, the underlying S3 key) double-prefixes the lookup and 400s as `"The following files have not been uploaded: <email>/<file>"`. Use the bare filename or the `s3Path`, never the email-prefixed key.

## Errors

| Code | Meaning | Action |
|---|---|---|
| 400 | Bad request (e.g. a file ref that doesn't resolve) | Re-check the file reference (s3Path / bare name, not email-prefixed) |
| 401 | Unauthorized | Check `x-api-key` (run `tamarind-api-setup`) |
| 404 | Unknown job/file | Check the job name; `getJobs` to confirm it exists |
| 429 | Rate limited | Back off and retry |
| 500 | Server error | Retry; if persistent, contact support |

## Reference files

- [references/results.md](references/results.md): the read-back surface (status fields, the two file surfaces, the two-step result, the metric table + directions, the scoring/alignment tools, and the s3Path chaining rule).
- [references/examples.md](references/examples.md): worked read-back recipes (parse a fold, score against a reference, chain fold -> ipsae by s3Path, re-attach by name) and the output shapes per tool family.
