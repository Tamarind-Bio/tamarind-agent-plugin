# Batch input examples

Confirm every field with `tamarind --json schema TOOL` before validation or submission.

## Bare list of per-job settings

```yaml
- inputFormat: sequence
  sequence: GYAGYAGYAGYAGYAGYAGYAGYA
  numSamples: 1
- inputFormat: sequence
  sequence: ACDEFGHIKLMNPQRSTVWY
  numSamples: 1
```

Submit with a CLI-supplied parent name:

```bash
tamarind --json batch boltz --input batch.yaml --name fold-screen --prevalidate
```

## Object with explicit subjob names

```yaml
batchName: fold-screen
type: boltz
jobNames:
  - a
  - b
settings:
  - inputFormat: sequence
    sequence: GYAGYAGYAGYAGYAGYAGYAGYA
    numSamples: 1
  - inputFormat: sequence
    sequence: ACDEFGHIKLMNPQRSTVWY
    numSamples: 1
```

Keep `jobNames` and `settings` aligned one-to-one. These entries are bare, unique suffixes: the platform prepends `batchName`, so `a` becomes `fold-screen-a`. Do not repeat the parent prefix inside each suffix or names become doubled.

## Cost review

Before submission, report input count multiplied by per-input samples/designs and any expensive optional stage. Validation does not authorize the aggregate spend.
