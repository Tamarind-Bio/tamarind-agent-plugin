# CLI workflow recipes

All recipes use an explicit settings file, a durable job name, a bounded wait, and status inspection.

## Authorization and retry decisions

| User request / state | Action |
|---|---|
| “Run one small paid job”; validated settings stay within that scope | Submit once, even without an idempotency key or pre-submission cost estimate |
| Authorized run has no estimate and no numeric cost cap | State that preflight cost is unavailable, submit once, and report actual weighted hours afterward |
| “Run only if it costs at most X”; X cannot be verified | Stop and ask; do not submit |
| Dry run, validation-only request, or setup smoke check | Validate only; do not submit |
| Authorized settings materially change after validation | Reconfirm the changed scope |
| Initial submit response is ambiguous | Query the durable job name; do not retry the submit command |

One client-side submission attempt is not a server-side exactly-once guarantee.

## Sequence-only fold

`settings.yaml`:

```yaml
inputFormat: sequence
sequence: GYAGYAGYAGYAGYAGYAGYAGYA
numSamples: 1
```

No-spend validation:

```bash
tamarind --json schema boltz
tamarind --json validate boltz --input settings.yaml --name fold-example
```

Only after the exact run is authorized:

```bash
tamarind --json submit boltz --input settings.yaml --name fold-example
# Probe durable status first; wait when an active JobStatus or batchStatus is present.
tamarind --json wait fold-example --timeout 7200 --poll-interval 15
tamarind --json results fold-example --download /absolute/path/to/results
```

## Upload a structure, then run a structure-based tool

```bash
tamarind --json files upload /absolute/path/target.pdb
tamarind --json files list --search target.pdb
```

Put the returned `filename` in the tool's live-schema field, validate, then use the same submit/wait/download sequence.

## Submit now, recover later

```bash
tamarind --json submit TOOL --input settings.yaml --name durable-name
```

Persist `durable-name`. In another task or process:

```bash
tamarind --json status durable-name
# CLI 0.2 waits on either an active JobStatus or batchStatus.
tamarind --json wait durable-name --timeout 1800 --poll-interval 15
```

Do not create a new job merely because the first local process ended.

## Diagnose a terminal failure

```bash
tamarind --json status durable-name
tamarind --json logs durable-name --max-lines 200
```

Fix the payload against the current schema and ask before submitting a replacement run.
