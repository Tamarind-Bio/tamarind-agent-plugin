---
name: tamarind-api-setup
description: "Use ONCE to set up Tamarind Bio access before running any tool: get an API key, export TAMARIND_API_KEY, verify it works with a first call, and learn the REST vs MCP surfaces plus the canonical live sources (llms.txt, openapi.yaml, docs.tamarind.bio). Use when a Tamarind call returns 401, when TAMARIND_API_KEY is unset, or to orient on the platform. Not for running a tool end to end (use tamarind-submit-and-poll), not for discovering which tool fits a goal (use the discovery surface described here)."
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: API setup

Tamarind Bio runs computational-biology tools (structure prediction, protein and antibody design, docking, binding affinity, MSA generation, molecular dynamics) on managed GPUs. You submit sequences or structures through one uniform job API and get back predicted structures, designs, and biophysical scores. No local GPU. One API key, the whole toolbox.

This skill is a one-time setup: get a key, prove it works, and learn the two ways to call the platform plus where the live, machine-readable sources live. Run a tool with `tamarind-submit-and-poll` once setup is green.

## 1. Get an API key

1. Sign in at [app.tamarind.bio](https://app.tamarind.bio) (create an account if you don't have one).
2. Open the account / API settings and create an API key.
3. The key authenticates both surfaces: the REST header is `x-api-key`, the MCP header is `X-API-Key` (same key, same value).

New accounts get a free allotment of weighted-hours so you can try tools without a credit card (the exact terms are on the pricing/account page; check there rather than assuming a number). Usage past the free allotment is billed in weighted hours: a single number per job that scales with runtime and GPU tier (GPU tools cost more than CPU tools, longer runs cost more). To raise limits or buy a subscription, contact Tamarind via [tamarind.bio](https://www.tamarind.bio); for support or to report a bug, use [help.tamarind.bio/en/contact-us](https://help.tamarind.bio/en/contact-us) (don't guess a support email). The `/usage-statistics` endpoint is ORG-scoped, not caller-scoped: it returns every member of your organization's per-tool weighted-hours, so don't read another member's row as your own usage.

## 2. Export the key (never hardcode it)

```bash
export TAMARIND_API_KEY="your_api_key"
```

Read it from the `TAMARIND_API_KEY` environment variable (or a `.env` file loaded with `python-dotenv`). Never paste the key into a script, a notebook cell, or source control. The bundled client (`tamarind-submit-and-poll`'s `tamarind_client.py`) reads this variable for you.

## 3. First-call self-check

Before any real submit, confirm the key works with one cheap read. `GET /tools` lists the catalog and costs nothing:

```bash
curl -s https://app.tamarind.bio/api/tools \
  -H "x-api-key: $TAMARIND_API_KEY" | head -c 400
```

A JSON array back means the key is good. A `401` means the key is missing or wrong (re-check the export and the value). If you get a JSON array, you're set: go to `tamarind-submit-and-poll` to run a tool.

Python equivalent:

```python
import os, requests
r = requests.get("https://app.tamarind.bio/api/tools",
                 headers={"x-api-key": os.environ["TAMARIND_API_KEY"]})
r.raise_for_status()              # 401 here = bad/missing key
print(len(r.json()), "tools available")
```

## 4. Two ways to call Tamarind

**REST (universal).** Base URL `https://app.tamarind.bio/api/`, every request carries the `x-api-key` header. There is **no official Python SDK** (the PyPI package named `tamarind` is an unrelated Neo4j tool, do not `pip install tamarind`). Write plain `requests` calls, or use the bundled REST client, which ships under `tamarind-submit-and-poll/scripts/tamarind_client.py` (driven via that skill's `tamarind_job.py` CLI wrapper). This is the surface every skill builds on.

**MCP (best for AI agents).** Tamarind hosts an MCP server at `https://mcp.tamarind.bio/mcp` (auth via the `X-API-Key` header). When your agent host supports MCP, prefer it for discovery and validation. The agent-friendly tools include:

- `getAvailableTools(modality?, function?, search?)` and `listModalities()` / `listTags()` for the live filter vocabulary
- `getJobSchema(jobType)` for a tool's exact parameter schema plus an `exampleJob` starting payload
- `validateJob(jobName, type, settings)` to dry-run a submission with no spend
- `submitJob` / `submitBatch`, `getJobs`, `getJobLogs`, `listJobFiles`, `getResult`, `uploadFile`

**Installing this plugin auto-wires the Tamarind MCP connector** (`mcp.tamarind.bio`) using the same `TAMARIND_API_KEY` you exported above, so on a host that supports MCP the discovery and validation tools are ready with no extra setup. This works on both Claude Code and Codex (the plugin ships the right header-auth config for each). The MCP is preferred for discovery and validation; REST is the universal floor.

The MCP is an **improvement, not a requirement**: every skill works over plain REST alone if a host lacks MCP support. Where the MCP is present, prefer `getAvailableTools` / `getJobSchema` for discovery and `validateJob` before submitting (see `tamarind-submit-and-poll`). MCP query tools (`getJobs`, `getResult`, `listJobFiles`) are scoped to the authenticated account.

## 5. Canonical live sources (fetch these, don't trust a stale copy)

Tool names, schemas, and endpoints change often. Prefer fetching the live source at runtime over any hardcoded list:

- **`https://app.tamarind.bio/llms.txt`**: LLM index: links to the spec, the API docs, and the MCP guide.
- **`https://app.tamarind.bio/openapi.yaml`**: OpenAPI 3.0 spec for the core job endpoints (submit-job, submit-batch, jobs, result, upload, files, delete-job, delete-file). Fetch it for exact request/response shapes. Discovery/management endpoints (`/tools`, `/usage-statistics`, pipelines) are not in it: use the REST/MCP discovery tools for those.
- **`https://docs.tamarind.bio/llms.txt`**: documentation index; every page has a `.md` form (e.g. `docs.tamarind.bio/tamarind/api.md`, `/tamarind/batch.md`).
- **Live tool discovery**: `GET /tools` (REST) or MCP `getAvailableTools` + `getJobSchema(jobType)` are the source of truth for what tools exist and their parameters.

## Next

Setup green? Run a tool end to end with **`tamarind-submit-and-poll`** (validate, submit, poll to terminal, download).
