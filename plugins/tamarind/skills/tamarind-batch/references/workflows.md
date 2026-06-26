# Tamarind Bio batch recipes

End-to-end examples for running ONE tool across MANY inputs. They use the bundled client (`scripts/tamarind_client.py`), which reads `TAMARIND_API_KEY` from the environment and encodes the batch shapes (parallel-array submit, `batchStatus`-on-the-parent polling). For exact request/response shapes, fetch `https://app.tamarind.bio/openapi.yaml`. The canonical loop is **discover -> schema -> validate one shape -> confirm the cost multiplier -> submit -> poll the PARENT -> download -> rank.**

**The import.** `submit_batch` and the rest of the client live in `scripts/`. From any cwd, either add that dir to `sys.path` (`sys.path.insert(0, "scripts")`) or `cd` into `scripts/` first; the single-job `wait`/`get`/`download` commands of the CLI wrapper `scripts/tamarind_job.py` run a **parent name** unchanged. For raw `requests`, every call is `BASE = "https://app.tamarind.bio/api"` with `HEADERS = {"x-api-key": os.environ["TAMARIND_API_KEY"]}`.

## 1. Fold a library of sequences (the core batch)

```python
import sys; sys.path.insert(0, "scripts")
from tamarind_client import submit_batch, wait_for, download

library = {"cand-0": "MKT...", "cand-1": "AVF...", "cand-2": "GEV..."}   # your inputs
names    = list(library)
settings = [{"sequence": s} for s in library.values()]   # one dict per input, SAME tool

# validate the SHARED shape ONCE before multiplying it across N (MCP present):
#   validateJob(jobName="probe", type="alphafold", settings=settings[0]) -> act on verdict["valid"]
# a single bad shared field becomes N failed subjobs, so confirm the shape first.

submit_batch("binder-screen", "alphafold", names, settings,
             weighted_hours_budget=50)            # optional guardrail cap

parent = wait_for("binder-screen")                # auto-polls batchStatus through Aggregating
print(parent["statuses"])                         # subjob tally
download("binder-screen")                         # Complete parent -> binder-screen.zip
```

`numModels`, `useMSA`, and the rest of the tool's settings are shared across every subjob, so each one changes the cost of the **whole** batch (see step 2 of SKILL.md). The tool (`alphafold`) is fixed for the batch; per-subjob `settings` rows may differ (a different sequence each).

## 2. Poll the PARENT, not the subjobs (the footgun, in raw requests)

Subjobs go `Complete` before the aggregated zip exists. Watch the **parent's** `batchStatus`:

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
    time.sleep(15)                                # Running / Aggregating -> keep waiting
# A Complete parent carries a presigned resultUrl + a statuses tally
open("binder-screen.zip", "wb").write(requests.get(parent["resultUrl"]).content)
```

The `statuses` tally on the parent (e.g. `{"Complete": 3, "Running": 0, "Stopped": 0}`) is NOT a reliable "done" signal on its own: it can read all-Complete while the parent is still `Aggregating`. The batchStatus transition `Running -> Aggregating -> Complete` is the authority.

## 3. Rank the subjobs after the parent is Complete

```python
import json, requests
parent  = requests.get(f"{BASE}/jobs", headers=H, params={"jobName": "binder-screen"}).json()
subjobs = requests.get(f"{BASE}/jobs", headers=H,
                       params={"batch": "binder-screen", "includeSubjobs": "true"}).json()
json.dump({"parent": parent, "subjobs": subjobs["jobs"]}, open("binder-screen-rows.json", "w"))
```

```bash
python3 scripts/rank_batch.py binder-screen-rows.json --metric iptm          # higher-is-better
python3 scripts/rank_batch.py binder-screen-rows.json --metric pae --ascending  # lower-is-better
python3 scripts/rank_batch.py binder-screen-rows.json --json                 # machine-readable
```

`rank_batch.py` reads `{"parent": ..., "subjobs": [...]}` (or a bare list of subjob rows, or a dir holding `parent.json` + `subjobs.json`), parses each subjob's `Score` (a JSON string), ranks the completed ones by your `--metric`, and writes `ranked_batch.csv`. With no `--metric` it auto-picks the numeric `Score` key common to the most completed subjobs and names it in the printed summary. Subjobs that did not complete (or have no Score) are listed after the ranked ones.

## 4. Chain off a design job with fromJob (MCP)

A design job (ProteinMPNN, RFdiffusion+MPNN) emits many sequences. Fold every one as a batch in one MCP call:

```
# design-step is a COMPLETED proteinmpnn job that produced N sequences
submitBatch(batchName="verify-designs", type="alphafold", fromJob="design-step")
# then poll verify-designs on batchStatus and rank (steps 2-3)
```

`fromJob` reads the design job's generated sequences and folds each as a subjob. Over plain REST (no MCP), read the design outputs and build the array yourself, one `{"sequence": ...}` per design:

```python
# MCP listJobFiles("design-step") gives s3Path of the FASTA, or download via /result, then:
designed = ["MKT...designed-1", "AVF...designed-2", ...]      # parsed from the design output
names    = [f"fold-{i}" for i in range(len(designed))]
settings = [{"sequence": s} for s in designed]
submit_batch("verify-designs", "alphafold", names, settings)
```

Don't pass a designed sequence through a file/template param: a template field is for structural homology, not "fold this sequence." Fold a sequence by putting it in `sequence`.

## 5. Large N: point the batch at a file

For a big library the parallel arrays get unwieldy. When inputs live in a file (a CSV of sequences, a multi-record FASTA, an SDF of ligands), upload the file and reference it by **bare filename**; the file-driven input param is tool-specific, so confirm it with `getJobSchema(jobType)`:

```python
from tamarind_client import upload_file
name = upload_file("library.csv")            # returns the bare name "library.csv" (NOT email-prefixed)
# inspect getJobSchema(<tool>) for the CSV/FASTA/list-typed input field, then submit a batch that
# references `name` in that field. Aggregation + batchStatus polling are identical to steps 2-3.
```

The exact field name varies by tool (some take `csvFile`, some a FASTA, some a list param), so read the schema rather than guessing. When unsure, the parallel `jobNames[]`/`settings[]` form (up to 100 per call) always works; split a larger library into multiple batches.

## 6. Submit a long screen now, collect later (non-blocking)

A batch parent is addressable by name from any process, so you don't have to hold a blocking poll loop open for a multi-hour screen:

```python
# --- Session 1: submit, save the parent name ---
import json, sys; sys.path.insert(0, "scripts")
from tamarind_client import submit_batch
submit_batch("overnight-screen", "esmfold2",
             [f"cand-{i}" for i in range(80)],
             [{"sequence": s} for s in library])      # library = your 80 sequences
json.dump({"parent": "overnight-screen"}, open("pending_batch.json", "w"))
```

```python
# --- Session 2 (later, fresh process): collect if the parent is Complete ---
import json, sys; sys.path.insert(0, "scripts")
from tamarind_client import get_job, download
name = json.load(open("pending_batch.json"))["parent"]
row = get_job(name)                                   # bare parent row, by-name
if row.get("batchStatus") == "Complete":
    download(name)                                    # -> overnight-screen.zip
else:
    print("still", row.get("batchStatus"))            # Running / Aggregating -> check back
```

Re-run session 2 until the parent is `Complete`. This is the server-driven variant of the single-job submit-now/check-later pattern: poll one parent's `batchStatus` instead of looping job-by-job.

## Notes

- **Polling cadence:** 15-30s. Batch terminals are `Complete` / `AggregationFailed` / `Stopped`.
- **Budget:** `weightedHoursBudget` caps the whole batch; a `403` at submit means the cap was hit. There is no cost-estimate endpoint, so a batch's rough cost is N x per-subjob weighted hours (SKILL.md step 2).
- **Partial failures:** individual subjobs can `Stop` without failing the batch; the parent's `statuses` tally shows how many completed, and `rank_batch.py` ranks those.
- **One tool per batch.** Two different tools is two batches (or a `tamarind-pipeline` DAG).
