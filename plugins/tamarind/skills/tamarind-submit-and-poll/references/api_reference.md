# Tamarind Bio REST API reference (submit / poll / result surface)

**Spec:** the OpenAPI spec at `https://app.tamarind.bio/openapi.yaml` (3.0, auth `ApiKeyAuth`) covers the core job endpoints (`/submit-job`, `/submit-batch`, `/jobs`, `/result`, `/upload/{filename}`, `/files`, `/delete-job`, `/delete-file`). Fetch it for exact shapes. It does **not** include the discovery/management endpoints (`/tools`, `/usage-statistics`, pipelines, `/stop-job`): for those, use this file plus the live MCP `getAvailableTools`/`getJobSchema`/`getJobs`. This file adds the behaviors no spec spells out (response-shape-by-query, two-step result download, REST-vs-MCP field differences) for the single-job lifecycle.

Base URL: `https://app.tamarind.bio/api/`
Authentication: `x-api-key: <YOUR_KEY>` header on every request.
Interactive docs: [app.tamarind.bio/api-docs](https://app.tamarind.bio/api-docs) · markdown docs at [docs.tamarind.bio](https://docs.tamarind.bio)

There is no official Python SDK. Call the API with `requests` (Python) or `curl`, or use the bundled `tamarind_client.py`. An MCP server (`https://mcp.tamarind.bio/mcp`, `X-API-Key` header) exposes the same operations with agent-friendly schemas.

## Endpoints (single-job lifecycle)

| Method | Path | Purpose |
|---|---|---|
| GET | `/tools` | List available tools and their inline parameter schemas. Returns the **full list** (no server-side filtering, filter client-side). |
| POST | `/submit-job` | Submit one job. Body: `jobName`, `type`, `settings` (+ optional `projectTag`). |
| GET | `/jobs` | Inspect a job. Query: `jobName` (by-name, bare row), or list (no `jobName`). |
| POST | `/result` | Get a presigned download URL for results (two-step, see below). Body: `jobName` (+ optional `fileName`, `pdbsOnly`). |
| POST | `/stop-job` | Stop a running or queued job. Body: `jobName`. |
| PUT | `/upload/{filename}` | Upload a file (`--data-binary`; add `?folder=` to file it). Or get a presigned URL via MCP `uploadFile`. |
| GET | `/files` | List your account's uploaded files as a flat array of filename strings. Does **not** enumerate a job's outputs (use MCP `listJobFiles` for that). |

## Request shapes

### GET /tools

Returns a JSON **array**. Each element: `{name, displayName, description, github, paper, settings}` where `settings` is the tool's inline parameter schema. In each `settings` param, only `name` and `required` are guaranteed; `type`, `default`, `description`, `options` appear only when applicable (about 60% carry `type`). Read them with `param.get("type")`, not `param["type"]`. The REST list is not filtered by query params, so filter client-side on `name`/`displayName`/`description`. (The advanced gating keys `exclude` and `conditionals` appear **only in MCP `getJobSchema`**, not in REST `/tools`.)

### POST /submit-job

```json
{
  "jobName": "my-protein-analysis",
  "type": "alphafold",
  "settings": { "sequence": "MKT...", "numRecycles": 3 },
  "projectTag": "proj_xxxxxxxx"
}
```

- `jobName`: unique, `^[a-zA-Z0-9_-]+$`, 1-100 chars.
- `type`: a tool name from `/tools`. The list changes often; never hardcode.
- `settings`: tool-specific; match the schema from `/tools` (or MCP `getJobSchema`). Some tools require more than `sequence` (e.g. `boltz` requires `inputFormat`); run `validateJob` to get the first missing field.
- `projectTag`: optional `proj_...` ProjectId.

Response (200): a confirmation string like `myJobName submitted to queue.`

### GET /jobs (response shape depends on the query)

- **By-name** (`?jobName=<name>`) -> the **job row object directly** (no `jobs` wrapper). Don't index `["jobs"][0]`.
- **List** (no `jobName`) -> `{ "jobs": [...], "startKey": "...", "statuses": {...} }`.

Each job row includes `JobName`, `Type`, `JobStatus`, `Created`, `Started`, `Completed`, `Settings` (JSON string), `Score` (JSON string, tool metrics), and `WeightedHours` (present for Premium-tier accounts). A batch **parent** row has `Type: "batch"` and carries `batchStatus` (poll that, not subjob `JobStatus`); fetched by name, a complete parent also includes a presigned `resultUrl`. Discriminate batch vs single by `Type == "batch"` (or presence of `batchStatus`), **not** by `statuses` (a single job's by-name row can carry a `statuses` tally too).

### POST /result (two-step download)

POST returns the presigned URL as a JSON-encoded string (the URL wrapped in double quotes), so `.strip('"')` to unquote. Fetch that URL with a second GET to download the results zip:

```python
url = requests.post(f"{BASE}/result", headers=H, json={"jobName": "myJob"}).text.strip('"')
open("myJob.zip", "wb").write(requests.get(url).content)
```

Optional body fields: `fileName` (one file instead of the zip), `pdbsOnly: true` (PDB outputs only).

## Status codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 400 | Bad request: invalid parameters/settings |
| 401 | Unauthorized: invalid/missing `x-api-key` |
| 403 | Budget exceeded (org/team) |
| 429 | Rate limited |
| 404 | Not found (e.g. unknown job) |
| 500 | Server error |

## Field-handling rules

**REST and MCP expose different fields.** The REST `/tools` entry gives a trimmed per-param view (`{name, type, required, default, description, options}`). The advanced gating keys `exclude` and `conditionals` appear **only** in MCP `getJobSchema`, not in REST `/tools`. So don't try to hand-derive what to strip from REST schema keys; they aren't there. The reliable guard on both surfaces is **`validateJob`** (MCP), which runs `/submit-job`'s exact validation without submitting and returns the first error.

- **Build your submit from your own settings, not `validateJob`'s `normalized` output.** `normalized` is informational (defaults filled in, sometimes platform-managed fields). Submit the same clean settings you validated.
- **Platform-internal routing fields**: `submit_method`, `monomer_msa`, `msa` are set by the platform. Never pass them.
- **File-typed fields with a plain string value are treated as INLINE CONTENT**, not a path. To reference an **uploaded file**, use its **bare filename** (`target.pdb`); the platform scopes it to your account, so do NOT email-prefix it. The `{email}/{filename}` form is the underlying S3 key, and passing it makes `submit-job` 400 with `"The following files have not been uploaded: <email>/<file>"`. To reference a **prior job's output**, use `JobName/path/to/file.ext`. Confirm the exact registered name with `getFiles` / `GET /files`.

## Authentication and secrets

- Read the key from `TAMARIND_API_KEY` (env or `.env`); never hardcode or commit it.
- The same key authenticates REST (`x-api-key`) and the MCP server (`X-API-Key`).
- Query operations are scoped to the authenticated account.
