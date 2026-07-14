# Tamarind CLI contract used by this plugin

The plugin requires `tamarind-cli>=0.2.0` and tests against the latest published release. Treat the executable as a subprocess protocol; do not import its Python modules.

## Global output contract

Global options precede the command:

```bash
tamarind --json COMMAND
tamarind --no-json COMMAND
```

Successful non-TTY commands default to JSON. Errors and Typer usage failures are structured JSON on stderr, so branch on the exit code before parsing the appropriate stream.

| Exit | Meaning |
|---|---|
| 0 | Command completed; inspect payload fields |
| 1 | Generic client or API failure |
| 2 | Usage or destructive-action confirmation |
| 3 | Authentication |
| 4 | Resource not found |
| 5 | Validation |
| 6 | Rate limit |
| 7 | Local wait timeout |
| 8 | Budget or quota |
| 9 | Remote job reached an unsuccessful terminal state |

Explicit authentication failures are exit 3, explicit budget/quota exhaustion is exit 8, and generic access-policy failures remain exit 1. Stop and surface non-auth failures without re-authenticating, retrying, or resubmitting.

## Discovery and validation

```bash
tamarind --json tools --function FUNCTION --modality MODALITY
tamarind --json schema TOOL
tamarind --json validate TOOL --input settings.yaml --name JOB_NAME
```

Validation returns `valid` and may return `normalized`. Submit the original settings, not the normalized echo.

## Job lifecycle

```bash
tamarind --json submit TOOL --input settings.yaml --name JOB_NAME
tamarind --json status JOB_NAME
tamarind --json wait JOB_NAME --timeout 3600 --poll-interval 15
tamarind --json logs JOB_NAME --max-lines 200
tamarind --json results JOB_NAME --download /absolute/output
```

Use a finite wait timeout for both jobs and batch parents. Exit 7 means still active at the local deadline; exit 9 means an unsuccessful terminal status. CLI 0.2 keeps presigned URLs out of normal result/status output and sanitizes transfer failures.

## Files

```bash
tamarind --json files upload /absolute/path/input.pdb
tamarind --json files list --search input.pdb
```

Use the returned bare `filename` in a file-typed setting. Do not use email-prefixed object keys or `s3://` URLs.

## Retry boundary

The CLI exposes no idempotency key, and job-name idempotency is not documented. This does not block one validated, authorized initial client-side submission attempt. It means the client cannot promise server-side exactly-once execution.

After an ambiguous submit response, query `status JOB_NAME` and do not invoke `submit` or `batch` again on network, rate-limit, or local timeout errors.
