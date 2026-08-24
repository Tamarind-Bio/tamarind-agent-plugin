# Result interpretation

## Status before artifacts

Read remote status first. Only a successful terminal state guarantees downloadable results. A local wait timeout means the remote job may still be active.

## Common confidence families

- `pLDDT`: local per-residue confidence; higher is better.
- `pTM`: global fold/topology confidence; higher is better.
- `ipTM`, `ipSAE`, `pDockQ`: interface-oriented confidence; higher is generally better, but tool-specific definitions differ.
- PAE: predicted alignment error; lower is better.
- Docking energy/affinity: often lower/more negative is better.
- Model confidence or pose confidence: usually higher is better and is not an energy.

Do not mix unlike metrics in one ranking. Report the exact field used and its direction.

## `Score` encoding

Job payloads may encode `Score` as a JSON string rather than an object. Parse it defensively, keep unknown fields, and do not assume every tool emits the same keys.

## Weighted hours

When present, `WeightedHours` reports platform usage. Include it in the result summary, especially for batches or repeated campaigns.

## Artifact handling

Download with:

```bash
tamarind --json results JOB_NAME --download /absolute/path/to/results
```

CLI 0.2 does not provide a general result-file listing command. Extract the bundle, inspect exact filenames, and upload a selected artifact for a downstream stage rather than guessing a remote path.

Computational confidence and scores prioritize candidates; they are not experimental validation.
