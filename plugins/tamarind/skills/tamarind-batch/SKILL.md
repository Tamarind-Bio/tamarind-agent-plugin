---
name: tamarind-batch
description: "Use to run ONE Tamarind Bio tool across MANY inputs in one call (a library or screen): submit a batch, poll the PARENT's batchStatus (not subjob JobStatus), wait for the aggregation step, then download the aggregated result and rank the subjobs. Covers the parallel jobNames[]/settings[] arrays, gpuType, fromJob chaining off a design job, and the by-file shape for large N. Not for a single input of one tool (use tamarind-submit-and-poll), not for chaining MULTIPLE tools into a server-side DAG (use tamarind-pipeline), not for first-time key setup (use tamarind-api-setup)."
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: batch one tool over many inputs

Run the **same** tool across a library of inputs in one submission (fold 200 designed sequences, dock a ligand set, score a hit list). A batch creates one **parent** job plus one subjob per input; the platform runs the subjobs in parallel, then **aggregates** their outputs into a single downloadable result. For a single input use `tamarind-submit-and-poll`; for a multi-tool chain (design then fold then score) use `tamarind-pipeline`. If `TAMARIND_API_KEY` is unset or a call returns 401, run `tamarind-api-setup` first.

The canonical loop is the single-job loop plus an aggregation wait: **discover -> schema -> validate one settings shape -> confirm the cost multiplier -> submit batch -> poll the PARENT's batchStatus -> download -> rank.**

## The one footgun this skill exists to prevent

**Poll the batch PARENT on `batchStatus`, not the subjobs on `JobStatus`.** Subjobs flip to `Complete` the moment they finish computing, but the parent then spends a few minutes **aggregating** the per-subjob outputs into the final zip. If you watch a subjob (or the `statuses` tally) and stop at "all Complete," you grab the result before the aggregated output exists. The parent's `batchStatus` goes `Running` -> `Aggregating` -> `Complete`, and only a `Complete` parent carries the downloadable `resultUrl`. The bundled `wait_for` auto-detects a batch parent and polls `batchStatus` for you, so the safe path is to wait on the **parent name**.

## Two surfaces (MCP preferred when present, REST is the floor)

This skill works over either surface, same as the rest of the plugin:

- **MCP server** (`https://mcp.tamarind.bio/mcp`, `X-API-Key` header). Prefer it for discovery and validation: `getJobSchema(jobType)` for the full per-tool schema, `validateJob` for a free dry-run on **one** settings shape before you multiply it across the batch, and `submitBatch(batchName, type, settings[], jobNames[])` (it also accepts `fromJob=` for design-chaining, below). Installing this plugin auto-wires the MCP connector with the same `TAMARIND_API_KEY` on both Claude Code and Codex.
- **REST API** (base `https://app.tamarind.bio/api/`, `x-api-key` header). The universal floor: `POST /submit-batch` with parallel arrays, poll `GET /jobs?jobName=<parent>` for `batchStatus`. The bundled client (`scripts/tamarind_client.py`) drives both submit and the batchStatus poll with no MCP at all.

Treat the MCP as an improvement layered on REST, not a prerequisite. Validate one settings shape with `validateJob` when it's present; otherwise let the first subjob surface a settings error.

## The bundled client and ranking script

This skill ships the thin REST client (`scripts/tamarind_client.py`, stdlib + `requests`), its CLI wrapper (`scripts/tamarind_job.py`), and `scripts/rank_batch.py` (ranks completed subjobs by a `Score` metric into a CSV). The client's `submit_batch` and `wait_for` bake in the batch shapes (parallel-array submit, batchStatus-on-parent polling) so you can't reimplement them wrong.

The CLI wrapper covers the single-job lifecycle (`submit`/`wait`/`get`/`download`/`upload`/`run`); **batch submit goes through the `submit_batch` client function** (shown inline below) since it takes parallel arrays. The `wait`/`get`/`download` wrapper commands work on a **parent name** unchanged (the client auto-discriminates batch vs single).

Probe the deps first; install only if the import fails:

```bash
python3 -c "import requests" 2>/dev/null \
  || python3 -m pip install -r scripts/requirements.txt \
  || python3 -m pip install --user --break-system-packages -r scripts/requirements.txt
```

## 1. Build one settings shape, then multiply it

A batch is one tool with parallel `jobNames[]` and `settings[]` arrays (same length, same tool, up to 100 items). Validate **one** representative settings dict first (it is the shape every subjob inherits), then build the arrays:

```python
import sys; sys.path.insert(0, "scripts")          # so the bare import resolves
from tamarind_client import submit_batch, wait_for, download

seqs = {"cand-0": "MKT...", "cand-1": "AVF...", "cand-2": "GEV..."}   # your library
names    = list(seqs)
settings = [{"sequence": s} for s in seqs.values()]   # one dict per input, SAME tool

# (optional, MCP present) validate the SHARED shape once before multiplying it:
#   validateJob(jobName="probe", type="alphafold", settings=settings[0])
#   act on verdict["valid"]; one bad shared field becomes N failed subjobs.

submit_batch("binder-screen", "alphafold", names, settings,
             weighted_hours_budget=50)              # optional cap, see step 2
```

Per-subjob settings can differ (different sequence per row); the **tool** is fixed for the whole batch. To run two different tools, that is two batches (or a pipeline).

Each `jobNames[]` entry is a **bare per-input suffix**: the platform prepends the `batchName` to form the subjob's full name (`batchName-suffix`). So name the entries `cand-0` / `native` / `analog-1`, NOT `binder-screen-cand-0`; repeating the batch name inside an entry produces a doubled prefix (`dock-fad-6nes-dock-fad-native`).

## 2. Surface the cost multiplier before submitting (a structural step)

A batch multiplies one choice across every input, so confirm the consequential settings **before** you submit, not after. This is the same surface-choices discipline as `tamarind-submit-and-poll`, amplified by N: a single shared knob (model/variant, number of samples or seeds, MSA on/off, GPU tier, recycles) changes the result, runtime, and cost of **every** subjob at once. Flagging the wrong default after queueing 200 jobs is 200x the waste.

Tamarind has **no cost-estimate endpoint** (unlike some platforms, there is no dry-run quote). Approximate the spend yourself and surface it:

- Billing is in **weighted hours** (the `WeightedHours` field on a completed row): roughly per-subjob runtime scaled by a GPU-class multiplier, plus an MSA term for MSA-consuming tools. GPU tools cost more than CPU tools; a heavier GPU tier and more samples/seeds/recycles cost more.
- So a batch's rough cost is **N x (per-subjob weighted hours)**. You don't know the exact per-subjob figure up front, but you know the **multiplier is N** and which shared settings push it up.
- Present the meaningful options plus the default you'd otherwise apply, and **cap the batch** with `weightedHoursBudget` (a `403` at submit means the cap was hit). Use it as a guardrail when the per-subjob cost is uncertain.

When the request fully specifies the run (explicit tool, explicit settings, explicit input set), proceed. When it's open-ended, name N, the shared settings that drive cost, and the budget cap, and let the user confirm before you queue the batch.

## 3. Submit, then poll the PARENT on batchStatus

After `submit_batch`, wait on the **parent name** (not a subjob). `wait_for` detects the batch parent and polls `batchStatus`:

```python
parent = wait_for("binder-screen")      # auto-polls batchStatus: Running -> Aggregating -> Complete
print(parent["statuses"])               # quick tally, e.g. {"Complete": 3, "Running": 0, "Stopped": 0}
download("binder-screen")               # a Complete parent carries resultUrl -> binder-screen.zip
```

The parent's `statuses` tally is a quick summary and can lag or under-count on a large batch. For the AUTHORITATIVE per-subjob count + scores, query the subjobs directly with `getJobs(batch=<id>, includeSubjobs=true)` (MCP) rather than trusting the parent row. Always scope a read by `batch=` or `jobName=`; a list-all query can overflow the response even with sequences omitted.

Or via the CLI wrapper (the `wait`/`download` commands take a parent name unchanged):

```bash
python3 scripts/tamarind_job.py wait     binder-screen   # polls batchStatus to a terminal state
python3 scripts/tamarind_job.py download binder-screen   # two-step presigned -> binder-screen.zip
```

The raw-REST equivalent, if you call the API directly:

```python
import os, time, requests
BASE, H = "https://app.tamarind.bio/api", {"x-api-key": os.environ["TAMARIND_API_KEY"]}
while True:
    # ?jobName= returns the parent ROW directly (no "jobs" wrapper)
    parent = requests.get(f"{BASE}/jobs", headers=H, params={"jobName": "binder-screen"}).json()
    bs = parent.get("batchStatus")
    if bs == "Complete":
        break
    if bs in ("Stopped", "AggregationFailed"):
        raise RuntimeError(parent.get("AggregationError", bs))
    time.sleep(15)                       # Running / Aggregating -> keep waiting
open("binder-screen.zip", "wb").write(requests.get(parent["resultUrl"]).content)
```

Run the submit+poll with the agent runtime's non-blocking facility (batches run minutes to hours): Codex (primary) as a FOREGROUND shell command with `yield_time_ms: 1000` (no `&`/`nohup`); Claude Code via Bash with `run_in_background: true`. The parent is addressable by name from any process, so submit, persist the parent name, and re-attach later with `tamarind_job.py wait binder-screen` from a fresh session.

## 4. Rank the subjobs after the parent is Complete

To pick winners, read the **per-subjob** rows (each carries its own `Score`) and rank them. Fetch the subjob rows, save them, and run `rank_batch.py`:

```python
import json, requests
subjobs = requests.get(f"{BASE}/jobs", headers=H,
                       params={"batch": "binder-screen", "includeSubjobs": "true"}).json()
json.dump({"parent": parent, "subjobs": subjobs["jobs"]}, open("binder-screen-rows.json", "w"))
```

```bash
python3 scripts/rank_batch.py binder-screen-rows.json --metric iptm   # higher-is-better by default
python3 scripts/rank_batch.py binder-screen-rows.json --metric pae --ascending   # lower-is-better
```

It prints a ranked candidate -> metric table and writes `ranked_batch.csv`. With no `--metric` it auto-picks the numeric `Score` key common to the most completed subjobs and names it. The downloaded zip (step 3) holds the aggregated artifacts (structures, a scores CSV, logs) for the whole batch; the ranking is the "submit, then rank whatever completed" readout on top of the per-subjob scores.

## 5. Chain off a design job with `fromJob` (MCP)

A sequence-design job (ProteinMPNN, RFdiffusion+MPNN) emits **many** sequences. To fold every one as a batch in a single MCP call, pass `fromJob=` instead of building the arrays by hand: the platform reads the design job's generated sequences and folds each as one subjob.

```
# design-step is a completed proteinmpnn job that produced N sequences
submitBatch(batchName="verify-designs", type="alphafold", fromJob="design-step")
```

This is the cleanest design -> fold chain. Then poll `verify-designs` on `batchStatus` and rank as above. Over plain REST without the MCP, read the design job's output sequences (`listJobFiles` via MCP, or download the FASTA via `/result`) and build the `settings[]` array yourself, one `{"sequence": ...}` per design. Don't pass a designed sequence through a file or template param: a template field is for structural homology, not "fold this sequence" (see `tamarind-submit-and-poll` chaining notes).

## 6. Large N: the by-file batch shape

For a large library, the parallel-array form is unwieldy. When the inputs live in a file (a CSV of sequences, a multi-record FASTA, an SDF of ligands), upload the file and point the batch at it rather than inlining hundreds of array entries. The exact file-driven field is tool-specific, so confirm it with `getJobSchema(jobType)` (look for a CSV/FASTA/list-typed input param), upload with `upload_file` (it returns the **bare filename** to reference, never email-prefixed), and submit. The aggregation + batchStatus polling are identical; only the input-marshalling differs. When in doubt, the parallel `jobNames[]`/`settings[]` form (up to 100) is always available.

## `gpuType` (batch GPU tier)

Some tools/accounts accept an optional `gpuType` on the batch to pick the GPU class the subjobs run on (a heavier tier costs more weighted hours per subjob). It is a per-batch tier knob, **not** a per-tool setting. The batch endpoint DOES support it (it validates the value against a fixed set of GPU tiers and 400s with the accepted list when the value is unknown), but it is absent from `openapi.yaml` and the MCP `submitBatch` schema, so don't hardcode the tier names: let the 400 message (or a small validate) tell you the accepted values for your account, and factor the heavier tier into the cost framing in step 2.

## Batch field exclusions

A tool's full `getJobSchema` can mark some params as **batch-excluded**: a field carrying `"exclude": [..., "batch", ...]` is a UI/pipeline-only knob that the batch path ignores (for example AlphaFold's `chooseBest`, which is `exclude: ["api", "batch", "tools"]`). Don't put a batch-excluded field in your shared `settings` shape expecting it to apply per subjob. The `exclude` list is MCP-only (`getJobSchema`), not in REST `/tools`; when in doubt, validate the shared shape and keep the settings to the tool's real, batch-honored params.

## Status and errors

A batch **parent** reports `batchStatus` (poll this); each **subjob** reports its own `JobStatus`.

| batchStatus | Meaning |
|---|---|
| `Running` | Subjobs computing |
| `Aggregating` | Subjobs done; building the final aggregated output |
| `Complete` | Aggregated result ready (`resultUrl` on the parent) |
| `AggregationFailed` | The aggregation step failed (`AggregationError` carries why) |
| `Stopped` | Batch stopped (failure, budget, manual) |

Treat `Complete` / `AggregationFailed` / `Stopped` as terminal; poll on a 15-30s cadence. Individual subjobs can `Stop` (bad input, OOM, timeout) without failing the whole batch; the parent's `statuses` tally shows how many completed, and `rank_batch.py` ranks the ones that did. A `403` at submit means a `weightedHoursBudget` cap was hit. For a stopped subjob, read its log tail with MCP `getJobLogs(<subjob-name>)`.

## Reference files

- [references/workflows.md](references/workflows.md): end-to-end batch recipes (parallel arrays, fromJob design-chaining, the by-file shape, rank-after-complete, submit-now/check-later for a long screen).
- [references/examples.md](references/examples.md): validated batch payloads (a folding screen, a docking screen), the read-only self-check, what-fails errors, and the parent/subjob row shapes `rank_batch.py` consumes.
