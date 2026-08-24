---
name: tamarind-developability
description: Score protein or antibody candidates for manufacturability and clinic-readiness with Tamarind Bio, including stability, aggregation, solubility, viscosity, polyreactivity, glycosylation, and immunogenicity. Use as a post-design filter. Not for generating molecules, folding structures, or measuring binding alone.
---

# Filter candidates for developability

Treat developability as a panel of orthogonal risks, not one universal score.

## Choose the relevant axes

```bash
tamarind --json tools --function developability
tamarind --json tools --function thermostability
tamarind --json tools --function aggregation
tamarind --json tools --function solubility
tamarind --json tools --function immunogenicity
tamarind --json schema TOOL
```

Match the input type and candidate class. Sequence-only tools, structure-based tools, paired-antibody tools, and nanobody-specific tools are not interchangeable.

Build a settings file and upload structures when required:

```bash
tamarind --json files upload /absolute/path/candidate.pdb
tamarind --json validate TOOL --input settings.yaml --name DEV_NAME
```

For a hit list, identify which axes matter for the intended modality and formulation, then use `tamarind-batch` to apply one tool consistently across candidates. Validate representative and conditionally different payloads before multiplying the run.

## Execute and interpret

Follow `tamarind-submit-and-poll` for a single candidate:

```bash
tamarind --json submit TOOL --input settings.yaml --name DEV_NAME
# Probe status first; wait when an active JobStatus or batchStatus is present.
tamarind --json wait DEV_NAME --timeout 7200 --poll-interval 15
tamarind --json results DEV_NAME --download /absolute/path/to/results
```

Report each risk axis separately, including the tool and threshold rationale. Preserve a Pareto set when candidates trade affinity against solubility, stability, or immunogenicity. Computational developability predictions prioritize experiments; they do not replace them.

Read [references/tools.md](references/tools.md) and [references/examples.md](references/examples.md) for modality-specific panels and payload patterns.
