# Tamarind Custom Tool format

The source folder is uploaded as one archive. Keep these files at its root:

```text
Dockerfile
run.sh
config.json
...tool source...
```

Never include `.git/`, virtual environments, `__pycache__`, local caches, `.env`, `.npmrc`, `.pypirc`, `.netrc`, or other credentials. Stage a clean copy when the checkout contains material that must not be uploaded.

## Runtime contract

| Fact | Value |
|---|---|
| Working directory | `/app` |
| Entry point | `bash -c "source /shared/env && bash run.sh"` |
| Scalar inputs | Environment variables named exactly as `inputs[].name` |
| File inputs | Read-only absolute paths beneath `/app/inputs/` |
| Durable outputs | `/app/out/` |
| Runtime network | Blocked |
| Image-build network | Available |

## `config.json`

`displayName` and `inputs` are required. The object rejects unknown properties.

| Field | Shape | Purpose |
|---|---|---|
| `displayName` | string | Tool-picker label |
| `description` | string | Short tool-card explanation |
| `functions` | string array | Capability bullets |
| `gpuType` | enum | `None`, `T4`, `L4`, `L40S`, `A10`, or `A100` |
| `memory` | string | For example `8Gi`, `32Gi`, or `90Gi` |
| `cpu` | integer | 1 through 8 |
| `homeDiskGi` | integer | Writable working disk, 1 through 50 GiB |
| `maxRuntimeSeconds` | integer | Per-job wall-clock cap |
| `envVars` | object | Uppercase runtime constants with string values |
| `estTime` | string | Expected runtime shown to users |
| `paperUrl` | string | Paper link |
| `tags` | string array | Searchable tags |
| `inputs` | array | User-facing input form |
| `taskType` | enum | `generate`, `score`, or `structure-prediction` |
| `producedOutputs` | array | Declared pipeline outputs |

## Inputs

Each input requires `name` and `type`. Names match `^[A-Za-z][A-Za-z0-9_]*$` and become case-sensitive environment-variable names. `run.sh` must read the exact same spelling.

Do not use shell-owned names such as `PATH`, `HOME`, `IFS`, `PWD`, `SHELL`, `UID`, `EUID`, `PPID`, or `BASH*`. Prefix them instead, such as `TOOL_PATH`.

Every input may also define `displayName`, `required`, and `descr`.

| Type | Additional fields |
|---|---|
| `file` | Required lowercase `extension` array |
| `pdb`, `sdf` | Optional `extension` |
| `sequence` | Optional `default` and `usesMsa` |
| `smiles`, `text`, `boolean` | Optional `default` |
| `number` | Optional `default`, bounds, and batching fields |
| `dropdown` | Required `options`; optional `default` |

Use `usesMsa` only when the model consumes the platform-provided alignment. It adds an MSA stage and cost to every job.

## Outputs

Each `producedOutputs` entry requires a `type` of `pdb`, `sequence`, `csv`, or `json`. It may include `name`, `descr`, and a `path` glob relative to `/app/out/`. Omitting this field is legal but prevents pipeline consumers from selecting declared outputs.

```json
{
  "displayName": "Sequence summary",
  "description": "Summarizes a protein sequence",
  "gpuType": "None",
  "memory": "8Gi",
  "cpu": 1,
  "inputs": [
    {
      "name": "SEQUENCE",
      "type": "sequence",
      "displayName": "Protein sequence",
      "required": true
    }
  ],
  "producedOutputs": [{"type": "csv", "name": "summary"}]
}
```

Run `tamarind --json custom-tools validate FOLDER` before upload. It catches archive hazards, missing adapter files, invalid local JSON, and likely runtime-network calls. Build admission performs the authoritative full contract validation.
