# Tamarind Bio: results read-back reference

The post-submit surface: how to read a job's status, find and download its outputs, interpret its metrics, score it against a reference, and feed it into the next job by reference. Endpoint shapes are in `tamarind-submit-and-poll/references/api_reference.md`; this file is the read-back-specific detail. The live `getJobSchema(<tool>)` is authoritative for any tool's parameters.

## Status read

`GET /jobs?jobName=<name>` (or MCP `getJobs(jobName)`) returns the **job row directly**, no `jobs` wrapper. The list query (no `jobName`, or `?batch=`) returns `{"jobs": [...]}` instead, so don't index `["jobs"][0]` on a by-name read.

Each row carries `JobName`, `Type`, `JobStatus`, `Created` / `Started` / `Completed`, `Settings` (JSON string), `Score` (JSON string, tool metrics), and (for Premium-tier accounts) `WeightedHours` (the billing unit, one number per job that scales with runtime and GPU tier).

- A **single job** is done on `JobStatus` (`Complete` / `Stopped` / `Deleted` / `Failed` are terminal).
- A **batch parent** (`Type: "batch"`) is done on `batchStatus` (`Running` -> `Aggregating` -> `Complete`, or `AggregationFailed` with `AggregationError`). Subjobs reach `Complete` BEFORE the parent aggregates, so read `batchStatus` on the parent, never the subjob `JobStatus`. Discriminate by `Type == "batch"` (or presence of `batchStatus`), not by a `statuses` tally (a single job's by-name row can also carry `statuses`).

For a `Stopped` job, `getJobLogs(jobName)` (MCP) returns the failure tail (bad input, OOM, timeout, budget). Read it before re-running.

## Jobs are addressable by name (re-attach across sessions)

A job name is a durable server-side handle. The process that submits does not have to be the one that reads back: persist the name, then `getJobs` / `wait` / `download` it from any later process. `wait` re-derives state from the live row each poll, so a fresh wait against an already-`Running` (or already-`Complete`) job is safe, with no client-side state to lose. The platform is the source of truth, keyed by name.

## Two file surfaces (do not confuse them)

| Surface | What it returns | Use for |
|---|---|---|
| MCP `listJobFiles(jobName)` | One job's output files: each `{name, size, s3Path}` | Enumerating a job's outputs AND getting the `s3Path` to chain with |
| REST `GET /files` | A flat list of your account's UPLOADED filenames, account-wide | Confirming an upload's registered bare name |

REST `/files` does **not** scope to a job, so per-job output enumeration is MCP-only. The bundled client's `list_job_files` raises with that message rather than returning the account-wide list and letting you mistake it for outputs.

## Two-step result download

`POST /result` with `{"jobName": "<name>"}` returns the presigned URL as a JSON-encoded string (quoted; `.strip('"')` to unquote). GET that URL for the zip:

```python
url = requests.post(f"{BASE}/result", headers=H, json={"jobName": "my-fold"}).text.strip('"')
open("my-fold.zip", "wb").write(requests.get(url).content)
```

Optional body fields: `fileName` (one file instead of the whole zip), `pdbsOnly: true` (PDB outputs only), `jobEmail` (a teammate's job, if permitted). A complete batch parent also exposes `resultUrl` directly on its by-name row.

## Metrics (the `Score` field + structure files)

`Score` is a **JSON string**, parse it. Keys are tool-family dependent; read the keys, don't assume them. Outputs are non-deterministic (seed / model / MSA), so reason about the shape and direction, not golden numbers.

| Metric | Scale | Direction | Notes |
|---|---|---|---|
| pLDDT | 0-100 | higher better | per-residue / mean local confidence; stored in the PDB B-factor column. >70 well-modeled, >90 high |
| pTM | 0-1 | higher better | global fold confidence |
| PAE | Angstroms | lower better | predicted aligned error matrix; low off-diagonal blocks = confident interface placement |
| ipTM | 0-1 | higher better | interface predicted TM-score (complex); ~0.6 a common acceptable cutoff |
| ipSAE | 0-1 | higher better | interface score from AF/Boltz confidence outputs; ranks predicted interfaces |
| pDockQ | 0-1 | higher better | predicted DockQ from one structure; ~0.23 conventional acceptable-interface floor |
| affinity | tool-specific | tool-specific | docking score (kcal/mol, more negative better) or predicted pKd/probability; read the tool's own key + direction |

The bundled scripts handle the column-name aliasing (CSV spellings differ across Boltz / Chai / AlphaFold / Protenix):

- `parse_boltz_confidence.py <dir-or-zip>` -> per-model pLDDT/pTM/ipTM/ipSAE/pDockQ ranked by the tool's own selection metric, low-confidence interfaces flagged (`--iptm-cutoff`, `--json`).
- `extract_docking_poses.py <dir>` -> per-pose affinity (Vina/gnina/smina, lower better) or confidence (DiffDock, higher better), ranked; writes the top-N pose files (`--top`, `--out`, `--json`).
- `summarize_binder_metrics.py <dir>` -> designs ranked by interface metric, with max / 10th-best / fraction-above-cutoff (`--metric`, `--cutoff`, `--json`).

Verify the artifact, not just the metric: a passing CSV can sit next to stub or identical structures. Open one real output (PDB/CIF/SDF) and check coords + sequence + atom count for a consequential result.

## Scoring and alignment tools (result QC)

These are normal jobs (submit via `tamarind-submit-and-poll`, read back here). Every file param takes a **bare uploaded filename** or a **prior job's `s3Path`** (chain by reference, section below). Params below are from live `getJobSchema`; re-fetch to confirm.

- **`dockq`**: grade a model complex against a native reference (DockQ + Fnat / iRMSD / LRMSD). Inputs: `modelFile`, `nativeFile` (both pdb), optional `allowedMismatches` (bump for small model-vs-native sequence differences AFTER the chains map; wrong chain correspondence scores wrong rather than erroring).
- **`pdockq`**: predict a DockQ-style score from a SINGLE complex, no reference. Input: `pdbFile`.
- **`ipsae`**: interface scoring (ipSAE / iCS) from folding-job confidence outputs. `inputType` is `af2` (needs `pdbFile` + `jsonFile`) or `boltz` (needs `cifFile` + `npzFile` + `plddtFile` + `confidenceFile`); `pae_cutoff` / `dist_cutoff` default 10. The inputs are exactly a fold job's outputs, so this is the canonical fold-then-score chain.
- **`molprobity`**: structure-geometry validation (clashes, rotamers, Ramachandran). Input: `pdbFile`.
- **`us-align`**: pairwise structural superposition + TM-score (proteins and nucleic acids). Inputs: `pdbFile1`, `pdbFile2`, `mm_opt` (monomer / multi-chain oligomer / circularly-permuted / fNS / sNS).
- **`rmsd-calculator`**: single pairwise RMSD. Inputs: `pdbFile1`, `pdbFile2`, `rmsdType` (`protein` / `ligand`); set `specifyChains: true` to add per-chain `alignChains*` / `rmsdChains*` (protein) or `rmsdLigand*` (ligand) fields.
- **`protein-metrics`** (COMPSS): ensemble pLM + inverse-folding likelihood scoring (ESM-IF / ProteinMPNN / ESM-1v) to rank and filter designed proteins before wet-lab testing; doubles as a developability read. `metricType` is `Single Sequence Metrics` (needs `sequence`) or `Structure Metrics` (needs `pdbFile`).
- **`pdbsum`**: structural summary diagrams (chains, DNA, ligands, metals). Input: `pdbFile`.

These eight are the established, most-run QC / scoring tools. For one not listed, discover it live with `getAvailableTools` (filter by the relevant function/tag), then `getJobSchema(<tool>)` for its params.

## Chain by reference, not by value

`listJobFiles(jobName)` returns each output's `s3Path`, and that `s3Path` is accepted **directly** as a file-typed setting on the next `submitJob` (no download-then-reupload). Three reference forms for a file-typed field:

1. `s3Path` from `listJobFiles`: best for chaining, zero round-trip.
2. `JobName/relative/path.ext`: a prior job's output by path (the no-MCP form).
3. A bare uploaded filename (`target.pdb`): after `upload_file` (which returns the bare name).

Foot-gun: a plain string that is NOT a real path is treated as **inline file content**; an **email-prefixed** key (`{email}/{filename}`, the S3 key) double-prefixes and 400s as `"The following files have not been uploaded: <email>/<file>"`. Use the bare name or the `s3Path`, never the email-prefixed form.
