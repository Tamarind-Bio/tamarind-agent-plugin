# Tamarind CLI contract used by this plugin

The plugin targets `tamarind-cli>=0.1.4,<0.2`. Treat the executable as a subprocess protocol; do not import its Python modules.

## Global output contract

Global options precede the command:

```bash
tamarind --json COMMAND
tamarind --no-json COMMAND
```

Successful non-TTY commands default to JSON. Errors and Typer usage failures are text on stderr, so branch on the exit code before parsing stdout.

| Exit | Meaning |
|---|---|
| 0 | Command completed; inspect payload fields |
| 2 | Usage or destructive-action confirmation |
| 3 | Authentication |
| 4 | Resource not found |
| 5 | Validation |
| 6 | Rate limit |
| 7 | Local wait timeout |
| 8 | Budget or quota in newer compatible CLI releases |

CLI 0.1.4 reports every HTTP 403 as exit 3. Inspect stderr before changing credentials: messages about budget, quota, credits, or weighted hours are spend-limit failures, not authentication failures. Stop and surface those failures without retrying or resubmitting.

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
tamarind --json status JOB_NAME | python3 -c 'import json,sys; blocked={"resulturl","downloadurl","presignedurl","uploadurl","headurl"}; scrub=lambda v: [scrub(x) for x in v] if isinstance(v,list) else {k:scrub(x) for k,x in v.items() if k.lower() not in blocked} if isinstance(v,dict) else v; print(json.dumps(scrub(json.load(sys.stdin))))'
# Only when the filtered probe carries JobStatus, not batchStatus:
tamarind --json wait JOB_NAME --timeout 3600 --poll-interval 15
tamarind --json logs JOB_NAME --max-lines 200
tamarind --no-json results JOB_NAME --download /absolute/output
```

Use the exact filtered status probe from the parent `SKILL.md`: if it carries `batchStatus`, schedule bounded one-shot probes instead of calling CLI 0.1.4's waiter. For a single job, `wait` may exit 0 for a terminal failure, so inspect `JobStatus`. Use `--no-json` for downloads because CLI 0.1 otherwise includes the presigned URL in output.

## Files

```bash
tamarind --json files upload /absolute/path/input.pdb
tamarind --json files list --search input.pdb
```

Use the returned bare `filename` in a file-typed setting. Do not use email-prefixed object keys or `s3://` URLs.

## Retry boundary

Job-name idempotency is not documented. After an ambiguous submit response, query `status JOB_NAME` before any retry. Never automatically retry `submit` or `batch` on network, rate-limit, or local timeout errors.
