---
name: tamarind-inverse-folding
description: Design sequences for a fixed protein backbone or run protein language models for embeddings, mutation scoring, and sequence generation with Tamarind Bio. Use for ProteinMPNN-, LigandMPNN-, ESM-IF-, or PLM-style tasks. Not for de novo backbone generation, antibody CDR design, or ordinary structure prediction.
---

# Run inverse folding and protein language models

Separate two task families:

- Inverse folding starts from a 3D backbone and produces sequences expected to fit it.
- Protein language models start from sequence and produce embeddings, mutation scores, likelihoods, or generated variants.

## Discover and confirm

```bash
tamarind --json tools --function inverse-folding
tamarind --json tools --function protein-language-models
tamarind --json tools --function embeddings
tamarind --json schema TOOL
```

For inverse folding, confirm designed chains/residues, fixed context, ligand context, sequence count, temperature/noise, omitted residues, and model variant. For PLMs, confirm task, model size, sequence limits, output format, and scan/generation parameters.

Upload a backbone with `tamarind --json files upload PATH` and use the returned bare filename. Validate before any run:

```bash
tamarind --json validate TOOL --input settings.yaml --name SEQ_NAME
```

Model size, sequence count, temperature, and batch size can change runtime, cost, and diversity. Surface them before submission.

## Execute and verify

Follow `tamarind-submit-and-poll`:

```bash
tamarind --json submit TOOL --input settings.yaml --name SEQ_NAME
# Run tamarind-submit-and-poll's filtered status probe; use wait only for JobStatus.
tamarind --json wait SEQ_NAME --timeout 7200 --poll-interval 15
tamarind --json results SEQ_NAME --download /absolute/path/to/results
```

Inverse-folded sequences require structural validation. Refold a diverse subset with `tamarind-structure-prediction`, then inspect backbone recovery and interface/confidence metrics. Do not route a designed sequence through a template/file field when the downstream schema expects `sequence`.

For many candidates, use `tamarind-batch` rather than repeated untracked submissions.

Read [references/tools.md](references/tools.md) and [references/examples.md](references/examples.md) for model-family details.
