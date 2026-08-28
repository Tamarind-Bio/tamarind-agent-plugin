# The Tamarind custom-tool format

`config.json` is `additionalProperties: false`, so an invented key is a hard failure. Validate with
`deployCustomTool(validateOnly=True)`, which checks the archive against the server's own contract -
this plugin has no HTTP client and must not fetch a schema itself. The summary below can lag the
server; `validateOnly` cannot.

## Archive layout

```text
my-tool/
├── Dockerfile      required
├── run.sh          required - the orchestrator's entry point
├── config.json     required - the declarative tool contract
└── ...             your code, at whatever paths run.sh expects
```

Never include `.git/`, virtualenvs, `__pycache__`, cached weights, or secret files
(`.env`, `.npmrc`, `.pypirc`, `.netrc`) in the map or folder you upload — the archive is
taken verbatim. **Omit them from the upload; do not delete them from the user's checkout.**
If the source tree cannot be uploaded without them, copy the tree to a staging directory and
prune that, leaving the original repository untouched.

## Runtime contract

| Fact | Value |
|---|---|
| Working directory | `/app` |
| Entry point | `bash -c "source /shared/env && bash run.sh"` |
| Scalar inputs | environment variables named exactly as `inputs[].name` |
| File inputs | absolute paths in their env vars, mounted read-only under `/app/inputs/` |
| Outputs | `/app/out/` - anything else is discarded |
| Network at runtime | none |
| Network at build time | available, so the `Dockerfile` may install and download |

## config.json fields

Only `displayName` and `inputs` are required.

| Field | Type | Notes |
|---|---|---|
| `displayName` | string | shown in the tool picker |
| `description` | string | one-liner on the tool card |
| `functions` | string array | long-description bullets, one string each |
| `gpuType` | enum | `None`, `T4`, `L4`, `L40S`, `A10`, `A100` |
| `memory` | string | for example `8Gi`, `32Gi` |
| `cpu` | integer | 1 to 8 |
| `homeDiskGi` | integer | 1 to 50, working-directory disk |
| `maxRuntimeSeconds` | integer | per-tool wall-clock cap; absent means the platform default |
| `envVars` | object | uppercase keys only, string values, passed at runtime |
| `estTime` | string | `H:M:S`, drives the runtime chip |
| `paperUrl` | string | surfaced as the Paper link |
| `tags` | string array | free-form |
| `inputs` | array | the user-facing form; see below |
| `taskType` | enum | `generate`, `score`, or `structure-prediction` |
| `producedOutputs` | array | declares outputs so pipelines can chain the tool |

## inputs[]

Every entry needs `name` and `type`. `name` must match `^[A-Za-z][A-Za-z0-9_]*$` and becomes the
environment variable your `run.sh` reads, **verbatim and case-sensitively** — declare `sequence`
and `run.sh` must expand `$sequence`, not `$SEQUENCE`. Under `set -u` a case mismatch aborts the
job on the first line that reads it, so use SHOUT_CASE in both places and keep them identical.
Optional on every variant: `displayName`, `required`, `descr`.

**Never name an input after a shell variable the launcher needs.** The name becomes an
environment variable sourced before `run.sh`, so schema-valid is not the same as safe:
`UID` is readonly in bash and assigning it exits 1 before your code runs, and `PATH`
replaces the search path so `bash run.sh` itself fails with `command not found`. Both
are the natural SHOUT_CASE conversion of `--uid` and `--path`. Avoid `PATH`, `HOME`,
`IFS`, `PWD`, `SHELL`, `UID`, `EUID`, `PPID`, `BASH*`, and anything else the shell owns;
prefix instead - `TOOL_PATH`, `INPUT_UID`.

| `type` | Also required | Also accepts |
|---|---|---|
| `file` | `extension` (non-empty array of lowercase extensions) | |
| `pdb` | | `extension` |
| `sdf` | | `extension` |
| `sequence` | | `default`, `usesMsa` |
| `smiles` | | `default` |
| `text` | | `default` |
| `number` | | `default`, `lowerBound`, `upperBound`, `designBatching`, `designsPerBatch` |
| `boolean` | | `default` |
| `dropdown` | `options` | `default` |

`usesMsa` is valid only on a `sequence` input and only once per tool. It runs the platform MSA
stage first and delivers one unpaired alignment per chain at `inputs/msas/N.a3m`, 1-indexed, where
chains are the field's colon-separated parts. It adds MSA time to every job's cost, so set it only
when the model genuinely consumes an alignment.

Prefer a specific type over `text`. A `pdb` input gives the user a structure picker; the same field
declared `text` gives them a free-text box and a class of runtime failures.

## producedOutputs[]

Each entry requires `type`, one of `pdb`, `sequence`, `csv`, or `json`, plus optional `name`,
`descr`, and `path` (a glob relative to the output directory).

```json
"producedOutputs": [
  { "type": "pdb", "name": "structure" },
  { "type": "csv", "name": "results", "descr": "Per-design scores" }
]
```

Omitting `producedOutputs` is legal - the tool simply never appears as a valid upstream in the
pipeline builder. You can add outputs later without rebuilding the image.

## Minimal example

```json
{
  "displayName": "Sequence summary",
  "description": "Summarizes a protein sequence",
  "gpuType": "None",
  "memory": "8Gi",
  "cpu": 1,
  "inputs": [
    { "name": "SEQUENCE", "type": "sequence", "displayName": "Protein sequence", "required": true }
  ],
  "producedOutputs": [{ "type": "csv", "name": "summary" }]
}
```

## What is validated where

- **By `deployCustomTool(validateOnly=True)`**: `Dockerfile` present, `run.sh` present (warning
  if absent), `config.json` parses as a JSON object, and archive paths are safe. This spends no
  build and mutates nothing, but it is **not** a local check — `files` and `binaryFiles` travel
  to the server either way.
- **By the server, at build admission**: everything else, including the full `config.json`
  contract. A clean `validateOnly` report is necessary but not sufficient.

Editing `config.json` and editing the Config tab in the web UI are equivalent; both write the same
tool record, and neither mints a version on its own.
