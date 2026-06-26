---
name: tamarind-submit-and-poll
description: "Use to run ONE Tamarind Bio tool end to end: validate, submit a single job, poll to a terminal status, and download the results. ALSO the canonical way to CHECK STATUS or WAIT FOR any already-submitted job: poll with the bundled wrapper, never a hand-rolled curl/requests loop. The base job-lifecycle recipe every Tamarind workflow builds on (fold a sequence, dock a ligand, run one design). Not for running ONE tool across MANY inputs (that is a batch, use tamarind-batch), not for chaining MULTIPLE tools into a server-side DAG (use tamarind-pipeline), not for first-time key setup (use tamarind-api-setup)."
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: submit and poll one job

The base lifecycle for running a single Tamarind tool: **validate, submit, poll to terminal, download.** Every domain workflow (fold, dock, design one molecule) is this loop with tool-specific `settings`. For many inputs of one tool use `tamarind-batch`; for a multi-tool chain use `tamarind-pipeline`. If `TAMARIND_API_KEY` is unset or a call returns 401, run `tamarind-api-setup` first.

The canonical order is **discover -> schema -> validate -> submit -> poll -> download.** Do not hardcode tool names or settings; the catalog changes frequently. Fetch the live schema (`GET /tools` or MCP `getJobSchema`) and let `validateJob` confirm the shape.

## Two surfaces (MCP preferred when present, REST is the floor)

Tamarind exposes the same platform two ways, and this skill works over either:

- **MCP server** (`https://mcp.tamarind.bio/mcp`, `X-API-Key` header). When your agent host has the Tamarind MCP, **prefer it for discovery and validation**: `getAvailableTools` to find tools, `getJobSchema(jobType)` for the **full** schema (it includes the `exclude` / `conditionals` gating keys that REST `/tools` trims out, plus an `exampleJob`), and `validateJob` for a free, no-spend dry-run before you submit. Installing this plugin auto-wires that MCP connector with the same `TAMARIND_API_KEY` on both Claude Code and Codex (see `tamarind-api-setup`).
- **REST API** (base `https://app.tamarind.bio/api/`, `x-api-key` header). The universal surface, available everywhere. The bundled REST client below is the **execution floor** for submit/poll/download and works with **no MCP at all** (graceful degradation, no hard dependency).

So: reach for the MCP tools for `getAvailableTools` / `getJobSchema` / `validateJob` when the host has them; otherwise discover via `GET /tools` and submit/poll/download via the bundled REST client. Treat the MCP as an improvement layered on top, not a prerequisite.

## The bundled client

This skill ships a thin REST client at `scripts/tamarind_client.py` (stdlib + `requests` only, reads `TAMARIND_API_KEY` from the environment). It encodes the four shapes below so you don't reimplement them wrong: the by-name bare row, the two-step `/result`, batch-vs-single auto-discrimination in `wait_for`, and the bare-filename upload reference. You can also drive the raw REST API with inline `requests`; the client is a convenience and a correctness guard, not a hard dependency. There is no validate method on the client (validation is the MCP `validateJob`, see below).

**Run it through the CLI wrapper `scripts/tamarind_job.py`, not a bare import.** The client module lives in `scripts/`, so `from tamarind_client import ...` raises `ModuleNotFoundError` from any cwd other than `scripts/` itself. The wrapper sidesteps that: invoke it as a script and Python puts its own directory (`scripts/`) on `sys.path[0]`, so its internal `import tamarind_client` resolves from **any** working directory. So always call:

```bash
python3 scripts/tamarind_job.py <submit|wait|get|download|upload|run> ...
```

(`scripts/` is the path from the skill root; use the absolute or full relative path to `tamarind_job.py` if your cwd is elsewhere, the import still resolves.) The `from tamarind_client import ...` snippets below are illustrative of the API; if you want to call those functions inline rather than via the wrapper, you must first `cd` into `scripts/` (or add it to `sys.path`) so the bare import resolves.

Probe the deps first; install only if the import fails:

```bash
python3 -c "import requests" 2>/dev/null \
  || python3 -m pip install -r scripts/requirements.txt \
  || python3 -m pip install --user --break-system-packages -r scripts/requirements.txt
```

On a system-managed Python (macOS Homebrew, recent Debian/Ubuntu) a bare `pip install` aborts with `error: externally-managed-environment` (PEP 668). The `--user --break-system-packages` fallback installs into your user site without touching the system env; or use a venv (`python3 -m venv .venv && . .venv/bin/activate && pip install -r scripts/requirements.txt`) and run the wrapper from it. `requests` is the only runtime dependency.

## 1. Validate before submitting (improvement, not a hard blocker)

When your agent host has the Tamarind MCP server, dry-run first to catch the first bad field with no spend. `validateJob` runs the exact `/submit-job` validation without submitting:

```
getJobSchema(jobType="boltz")               # learn required fields + an exampleJob
my_settings = {"inputFormat": "sequence", "sequence": "MKT...:EVQ..."}
verdict = validateJob(jobName="my-fold", type="boltz", settings=my_settings)
# verdict["valid"] is the signal you act on; verdict["error"] is the first problem to fix.
```

Two notes that prevent false stalls:

- The response may carry a `source` field (e.g. `"static-fallback"`). That labels how the tool's **schema** was resolved (built-in tools always report `static-fallback`); it does **not** mean the validator was unavailable. Act on `valid`, not `source`.
- `validateJob` echoes a `normalized` view with defaults filled in. Submit the **same clean settings you validated**, not the `normalized` echo (it can carry defaults and platform-managed fields you didn't set).
- A **file-typed** param (`pdbFile`, `receptorFile`, `targetFile`, ...) is checked against your file store, so `validateJob` returns `valid:false` ("... has not been uploaded") until the file actually exists, even when the settings SHAPE is correct (`missing_fields: []`). That is a real not-uploaded signal, not a payload error: upload the file first and pass its bare name (or validate against a file already in your store), then re-validate. Don't read it as a broken payload.

`validateJob` is MCP-only and it is the authority when present, but it is **an improvement, not a gate.** If the MCP is absent, or a dry-run is slow (passing **inline** file content makes `validateJob` upload it synchronously before validating), skip it and let `submit-job` validate on the real submission. Don't block the run on a missing or slow validate.

## 2. Surface consequential choices before submitting

When the request fully specifies what to run, proceed. But when it's open-ended, or a setting materially changes the results, runtime, or cost (model/variant, number of samples or seeds, MSA on/off, GPU tier), present the meaningful options plus the default you'd otherwise apply and let the user pick **before** you submit, rather than choosing silently and reporting it after the job is queued. `getJobSchema` and `validateJob`'s `normalized` show exactly which knobs you'd be filling in on the user's behalf, so flag the few worth a quick confirm.

## 3. Submit, poll, download (via the CLI wrapper)

**Poll with the wrapper, never hand-roll a status loop.** Use `tamarind_job.py wait <name>` (or the client's `wait_for`) for every poll; do NOT write your own `curl`/`requests` loop against `/jobs`. The wrapper already encodes the by-name bare-row shape, batch-vs-single discrimination, terminal-status detection on `Complete`/`Stopped`/`Deleted`/`Failed`, and a sane 15-30s cadence; a hand-rolled loop re-implements all four and gets at least one wrong (the classic miss: polling `JobStatus` on a batch parent, which never flips because the parent reports `batchStatus`).

Drive the lifecycle through `scripts/tamarind_job.py` so the sibling `import tamarind_client` resolves from any cwd. Settings are a JSON string (or `@settings.json`):

```bash
python3 scripts/tamarind_job.py submit my-fold boltz \
  '{"inputFormat": "sequence", "sequence": "MKT...:EVQ..."}'
python3 scripts/tamarind_job.py wait     my-fold     # polls JobStatus to a terminal state; prints the row
python3 scripts/tamarind_job.py download my-fold     # two-step presigned -> my-fold.zip
# or all three at once:
python3 scripts/tamarind_job.py run my-fold boltz @settings.json
```

The wrapper just calls the client functions (`submit_job`, `wait_for`, `download`, `get_job`, `upload_file`). The equivalent in Python, if you have already `cd`'d into `scripts/` (or added it to `sys.path`) so the bare import resolves:

```python
from tamarind_client import submit_job, wait_for, download   # only resolves from scripts/

submit_job("my-fold", "boltz",
           {"inputFormat": "sequence", "sequence": "MKT...:EVQ..."})
row = wait_for("my-fold")            # polls JobStatus to a terminal state
download("my-fold")                  # two-step presigned -> my-fold.zip
print(row.get("Score"))             # tool metrics (pLDDT/pTM/ipTM for folding)
```

`wait_for` polls on a 15-30s cadence and returns the final row, raising on `Stopped`/`Failed`. It auto-discriminates a batch parent from a single job (it polls `batchStatus` on a parent), so the same call is safe even if you later point it at a batch name. For a `Stopped` job, read the tail with MCP `getJobLogs(jobName)` to see why (bad input, OOM, timeout, budget).

Run the submit+poll with the agent runtime's non-blocking facility, since jobs run minutes to hours:

- **Codex (primary):** run the script as a FOREGROUND shell command with `yield_time_ms: 1000`. Do NOT append `&` or `nohup` (the tool runner may reap shell-backgrounded descendants before output flushes).
- **Claude Code:** run it via Bash with `run_in_background: true`.

Jobs are addressable by name from any process, so you can submit, persist the job name, and re-attach later with `tamarind_job.py get`/`wait` from a fresh session (see `references/workflows.md`).

In permission-gated agents (Claude Code), keep each call a top-level command that starts with `python3 scripts/tamarind_job.py ...` or `python3 -c "..."`; prefer concrete arguments over `sh -c`, inline env assignments, aliases, or pipelines unless the user already allowed that exact form.

## The four shapes the client bakes in

These are the API behaviors the spec doesn't make obvious. The client handles them; know them if you call REST directly. Full detail in [references/api_reference.md](references/api_reference.md).

### by-name `/jobs` returns a bare row

`GET /jobs?jobName=<name>` returns the job **row object directly**, no `jobs` wrapper. The list query (no `jobName`, or `?batch=`) returns `{"jobs": [...]}`. Don't index `["jobs"][0]` on the by-name response.

### `/result` is a two-step download

`POST /result` returns a presigned URL as a **bare string** (not JSON). GET that URL for the actual zip:

```python
url = requests.post(f"{BASE}/result", headers=H, json={"jobName": "my-fold"}).text.strip('"')
open("my-fold.zip", "wb").write(requests.get(url).content)
```

### file params reference a BARE filename

Tools with a file parameter (`proteinFile`, `receptorFile`, `csvFile`, ...) take input three ways: upload first then reference by **bare filename**; reference a prior job's output by the `JobName/path/to/file.ext` path; or send inline file content as the field value.

Foot-gun: a plain string in a file-typed field is treated as **inline content**, not a path to an existing object. To point at an already-uploaded file, use the **bare filename** only (e.g. `"proteinFile": "target.pdb"`). Do **NOT** email-prefix it: passing `{email}/{filename}` (the underlying S3 key) double-prefixes the lookup and `submit-job` 400s with `"The following files have not been uploaded: <email>/<file>"`. Upload with the client (`upload_file` returns the bare name) or `PUT /upload/{filename}`; confirm the registered name with `getFiles` / `GET /files` (a flat list of bare names).

### batch parents poll on `batchStatus`

A single job reports `JobStatus`; a batch **parent** (`Type: "batch"`) reports `batchStatus` and aggregates after subjobs finish. That is the `tamarind-batch` surface, not this one, but `wait_for` discriminates automatically so a stray batch name won't loop forever.

## Job status lifecycle

| Status | Meaning |
|---|---|
| `In Queue` | Accepted, waiting for capacity |
| `Running` | Executing on a worker |
| `Complete` | Finished successfully (results available) |
| `Stopped` | Failure, timeout, manual stop, or budget |
| `Deleted` | Deleted out-of-band |

Treat `Complete` / `Stopped` / `Deleted` (and `Failed`) as terminal and break the poll loop on **any** terminal status, not just `Complete`/`Stopped` (a job that goes `Deleted` mid-poll would otherwise loop forever). Completed jobs carry a `Score` (tool-specific metrics) and `WeightedHours` (the usage unit billed per job).

## Errors

| Code | Meaning | Action |
|---|---|---|
| 400 | Bad request / invalid settings | Re-check against the schema; `validateJob` first |
| 401 | Unauthorized | Check `x-api-key` (run `tamarind-api-setup`) |
| 403 | Budget exceeded | Lower scope or raise the budget |
| 429 | Rate limited | Back off and retry |
| 500 | Server error | Retry; if persistent, contact support |

## Reference files

- [references/api_reference.md](references/api_reference.md): the submit/poll/result/jobs/files surface and the non-obvious shapes (by-name bare row, two-step result, file-handling rules).
- [references/workflows.md](references/workflows.md): end-to-end recipes: fold a sequence, validate-before-submit, upload + reference a file, and submit-now/check-later for long jobs.
- [references/examples.md](references/examples.md): validated input payloads per tool (AlphaFold, Boltz, DiffDock, Autodock Vina, ProteinMPNN, batch), the read-only self-check, what-fails errors, and output shapes.
