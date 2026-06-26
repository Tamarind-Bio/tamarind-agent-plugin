# Tamarind Bio submit-and-poll recipes

End-to-end single-job examples. They use the bundled client (`scripts/tamarind_client.py`), which reads `TAMARIND_API_KEY` from the environment and encodes the by-name bare row, the two-step `/result`, and batch-vs-single auto-discrimination. For exact request/response shapes, fetch `https://app.tamarind.bio/openapi.yaml`. The canonical loop is always **discover -> schema -> validate -> submit -> poll -> download.**

**Two ways to call the client.** The copy-paste-safe path is the CLI wrapper `scripts/tamarind_job.py`, runnable from any cwd:

```bash
python3 scripts/tamarind_job.py submit <name> <tool> '<settings-json>'   # or @settings.json
python3 scripts/tamarind_job.py wait     <name>                          # poll to terminal
python3 scripts/tamarind_job.py download <name>                          # -> <name>.zip
python3 scripts/tamarind_job.py upload   <local-path>                    # -> bare filename
python3 scripts/tamarind_job.py run      <name> <tool> @settings.json    # submit + wait + download
```

The `from tamarind_client import ...` snippets in the recipes below show the underlying functions, but a bare import **only resolves from inside `scripts/`** (the module lives there). To run those snippets inline, first `cd` into the skill's `scripts/` dir (or add it to `sys.path`); otherwise drive the same calls through the wrapper above.

For raw `requests` instead of the client, every call is `BASE = "https://app.tamarind.bio/api"` with `HEADERS = {"x-api-key": os.environ["TAMARIND_API_KEY"]}`.

## 1. Fold a single sequence end to end

```python
from tamarind_client import submit_job, wait_for, download

# (optional) validate first when the MCP is present:
#   getJobSchema(jobType="alphafold")
#   validateJob(jobName="ubiquitin-fold", type="alphafold", settings={...})
# act on verdict["valid"]; submit your OWN settings, not verdict["normalized"].

submit_job("ubiquitin-fold", "alphafold", {
    "sequence": "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG",
    "numModels": "5",
    "numRecycles": 3,
    "useMSA": True,
})

row = wait_for("ubiquitin-fold")     # polls JobStatus to a terminal state, 15-30s cadence
print("status:", row["JobStatus"], "score:", row.get("Score"))

download("ubiquitin-fold")           # two-step presigned -> ubiquitin-fold.zip
```

A multimer in AlphaFold is one `sequence` with chains joined by `:` (`"EVQL...:DIQM...:MKT..."`). Other folders need more fields: `boltz`/`chai` require `inputFormat` (`"sequence"`/`"list"`/`"molecules"`/`"yaml"`), e.g. `{"inputFormat": "sequence", "sequence": "...:..."}`. Always confirm required fields with `getJobSchema`/`validateJob` first; don't assume `sequence` alone is enough.

### The same loop in raw requests (no client)

```python
import os, time, requests
BASE = "https://app.tamarind.bio/api"
HEADERS = {"x-api-key": os.environ["TAMARIND_API_KEY"]}

requests.post(f"{BASE}/submit-job", headers=HEADERS, json={
    "jobName": "ubiquitin-fold", "type": "alphafold",
    "settings": {"sequence": "MQIFVKT...RGG"},
}).raise_for_status()

while True:
    # by-name returns the row DIRECTLY (no "jobs" wrapper)
    row = requests.get(f"{BASE}/jobs", headers=HEADERS,
                       params={"jobName": "ubiquitin-fold"}).json()
    if row["JobStatus"] in ("Complete", "Stopped", "Deleted"):   # break on ANY terminal
        break
    time.sleep(30)

url = requests.post(f"{BASE}/result", headers=HEADERS,
                    json={"jobName": "ubiquitin-fold"}).text.strip('"')
open("ubiquitin-fold.zip", "wb").write(requests.get(url).content)
```

## 2. Upload a structure, then submit a job that uses it

A file param references the **bare filename**, never the email-prefixed S3 key and never inline content.

```python
from tamarind_client import upload_file, submit_job, wait_for, download

name = upload_file("target.pdb")        # returns the bare name "target.pdb"
submit_job("dock-run", "diffdock", {
    "proteinFile": name,                # bare filename, NOT inline content, NOT email-prefixed
    "ligandFormat": "SMILES",            # required; gates ligandSmiles vs ligandFile
    "ligandSmiles": "CC(=O)Oc1ccccc1C(=O)O",
})
wait_for("dock-run")
download("dock-run")
```

For `autodock-vina` instead of DiffDock, the same upload-then-reference flow applies but the settings differ: it docks into a fixed pocket, so it needs `receptorFile` plus a bounding box (`boxX/Y/Z`, `width/height/depth`) and a **lowercase** `ligandFormat` (`"smiles"`/`"sdf"`). Run `getJobSchema("autodock-vina")` for the full shape.

Reminder: a bare *non-filename* string in a file-typed field is uploaded as inline content. To point at an existing uploaded file, use its bare filename, NOT the `{email}/{filename}` S3-key form (which `submit-job` 400s as `"... has not been uploaded"`). Confirm the registered name with `getFiles` / `GET /files`. For a prior job's output, reference it by the `JobName/path/to/file.ext` path.

## 3. Submit now, check back later (non-blocking, long jobs)

Bio jobs run for minutes to hours, so you don't have to hold a blocking poll loop open. Jobs are addressable by `jobName` from any process: submit, **persist the names**, and reconnect in a separate session to collect results.

```python
# --- Session 1: submit and save the names ---
import json
from tamarind_client import submit_job

seqs = {"cand-a": "MKT...", "cand-b": "AVF...", "cand-c": "GEV..."}
for name, seq in seqs.items():
    submit_job(name, "alphafold", {"sequence": seq})
json.dump(list(seqs), open("pending_jobs.json", "w"))
print("submitted; check back later")
```

```python
# --- Session 2 (later, fresh process): collect whatever finished ---
import json
from tamarind_client import get_job, download

names = json.load(open("pending_jobs.json"))
done, pending = [], []
for name in names:
    row = get_job(name)                 # bare row, by-name
    (done if row["JobStatus"] in ("Complete", "Stopped", "Deleted") else pending).append(name)

print(f"{len(done)} terminal, {len(pending)} still running")
for name in done:
    download(name)
```

Re-run session 2 until `pending` is empty.

## 4. Debug a stopped job

A `Stopped` status with no `Score` usually means a failure (bad input, OOM, timeout, budget). With the MCP, read the tail: `getJobLogs("dock-run")`. A `403` at submit means a budget cap was hit.

## Notes

- **Polling cadence:** 15-30s. `Complete`, `Stopped`, `Deleted` (and `Failed`) are terminal; break the loop on any of them.
- **Scores:** completed folding jobs return pLDDT / pTM / ipTM (and interface metrics like ipSAE / pDockQ for complexes) in the `Score` field.
- **Many inputs of one tool** -> `tamarind-batch` (poll the parent's `batchStatus`). **A multi-tool chain** -> `tamarind-pipeline`.
