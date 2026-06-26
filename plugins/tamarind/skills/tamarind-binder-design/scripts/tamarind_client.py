#!/usr/bin/env python3
"""Thin Tamarind Bio REST client. stdlib + requests only; no SDK.

Reads TAMARIND_API_KEY from the environment. Encodes the non-obvious API shapes
(by-name bare row, two-step /result, batch batchStatus on the parent, bare-filename
file refs) so callers don't reimplement them. See references/api_reference.md for
the full surface and openapi.yaml for exact field lists.
"""
import os, time, requests

BASE = os.environ.get("TAMARIND_API_BASE", "https://app.tamarind.bio/api")
TERMINAL = {"Complete", "Stopped", "Deleted", "Failed"}          # JobStatus terminals
BATCH_TERMINAL = {"Complete", "AggregationFailed", "Stopped"}     # batchStatus terminals


def _headers():
    key = os.environ.get("TAMARIND_API_KEY")
    if not key:
        raise SystemExit("set TAMARIND_API_KEY (env or .env); never hardcode it")
    return {"x-api-key": key}


def submit_job(job_name, job_type, settings, project_tag=None):
    """POST /submit-job. Returns the confirmation text. settings must match the
    tool schema (GET /tools or MCP getJobSchema); validate first if MCP is present."""
    body = {"jobName": job_name, "type": job_type, "settings": settings}
    if project_tag:
        body["projectTag"] = project_tag
    r = requests.post(f"{BASE}/submit-job", headers=_headers(), json=body)
    r.raise_for_status()                # 400 = bad settings, 403 = budget, 401 = key
    return r.text


def submit_batch(batch_name, job_type, job_names, settings_list,
                 max_runtime_seconds=None, weighted_hours_budget=None):
    """POST /submit-batch (parallel-array form; matches MCP submitBatch). job_names
    and settings_list are parallel, same length, same tool. Poll the PARENT after."""
    assert len(job_names) == len(settings_list), "job_names and settings must align"
    body = {"batchName": batch_name, "type": job_type,
            "jobNames": job_names, "settings": settings_list}
    if max_runtime_seconds:    body["maxRuntimeSeconds"] = max_runtime_seconds
    if weighted_hours_budget:  body["weightedHoursBudget"] = weighted_hours_budget
    r = requests.post(f"{BASE}/submit-batch", headers=_headers(), json=body)
    r.raise_for_status()
    return r.text


def get_job(job_name):
    """GET /jobs?jobName= returns the job ROW DIRECTLY (no 'jobs' wrapper). Works for
    a single job AND a batch parent (parent has Type=='batch' + a batchStatus field)."""
    r = requests.get(f"{BASE}/jobs", headers=_headers(), params={"jobName": job_name})
    r.raise_for_status()
    return r.json()                     # bare dict, NOT {"jobs": [...]}


def _is_batch(row):
    return row.get("Type") == "batch" or "batchStatus" in row


def wait_for(job_name, interval=30, timeout=None):
    """Poll to a terminal state. Auto-detects batch vs single: a batch parent is done
    on batchStatus (subjobs go Complete BEFORE the aggregated output is ready), a single
    job on JobStatus. Returns the final row. Raises on Stopped/Failed/AggregationFailed."""
    start = time.time()
    while True:
        row = get_job(job_name)
        if _is_batch(row):
            bs = row.get("batchStatus")
            if bs in BATCH_TERMINAL:
                if bs != "Complete":
                    raise RuntimeError(row.get("AggregationError", bs))
                return row              # complete parent carries resultUrl + statuses
        else:
            st = row.get("JobStatus")
            if st in TERMINAL:
                if st in ("Stopped", "Failed"):
                    raise RuntimeError(f"{job_name}: {st} (read getJobLogs for the tail)")
                return row
        if timeout and time.time() - start > timeout:
            raise TimeoutError(f"{job_name} not terminal after {timeout}s")
        time.sleep(interval)            # 15-30s cadence; Running/Aggregating -> keep waiting


def result_url(job_name, file_name=None, pdbs_only=False):
    """POST /result is TWO-STEP: it returns a presigned URL as a BARE STRING (not JSON).
    A complete batch parent also exposes resultUrl directly on its row."""
    body = {"jobName": job_name}
    if file_name:  body["fileName"] = file_name
    if pdbs_only:  body["pdbsOnly"] = True
    r = requests.post(f"{BASE}/result", headers=_headers(), json=body)
    r.raise_for_status()
    return r.text.strip('"')            # bare URL string


def download(job_name, out_path=None, **kw):
    """Two-step download: get the presigned URL, then GET it for the zip."""
    url = result_url(job_name, **kw)
    out_path = out_path or f"{job_name}.zip"
    r = requests.get(url, stream=True)
    r.raise_for_status()                 # an expired/403 presigned URL is NOT success
    with open(out_path, "wb") as fh:
        for chunk in r.iter_content(chunk_size=1 << 20):  # stream, don't load multi-GB into RAM
            fh.write(chunk)
    return out_path


def list_job_files(job_name):
    """Enumerate a job's OUTPUT files. NOTE: REST GET /files is a flat, account-wide
    filename list and does NOT scope to a job, so file enumeration goes through the MCP
    (listJobFiles -> s3Path). With MCP absent, reference outputs by the 'JobName/path'
    form instead. This wrapper raises to point the caller at the MCP."""
    raise NotImplementedError(
        "REST /files is account-wide, not per-job. Use MCP listJobFiles(jobName), "
        "or reference a prior output by the 'JobName/relative/path.ext' string.")


def upload_file(local_path, registered_name=None, folder=None):
    """PUT /upload/{filename}. Returns the BARE filename to reference in a file-typed
    setting (target.pdb), NOT email-prefixed (the {email}/file S3-key form 400s as
    'not uploaded'), NOT the local path, NOT inline content."""
    name = registered_name or os.path.basename(local_path)
    params = {"folder": folder} if folder else {}
    with open(local_path, "rb") as fh:
        r = requests.put(f"{BASE}/upload/{name}", headers=_headers(),
                         params=params, data=fh)
    r.raise_for_status()
    return name                         # pass this bare name into settings["proteinFile"] etc.
