---
name: tamarind-binder-design
description: Design new de novo protein, peptide, macrocycle, or small-molecule binders against a target with Tamarind Bio, then refold and rank candidates. Use for backbone/sequence or ligand generation from scratch. Not for antibody-specific CDR engineering, fixed-backbone inverse folding, docking an existing ligand, or predicting an existing structure.
---

# Design de novo binders

Binder design is a generate-and-filter campaign, not a single deterministic answer.

## Define the design problem

Clarify the target structure or sequence, target chains/site/hotspots, binder class, length or chemistry constraints, desired candidate count, and required downstream filters. Use `tamarind-antibody` for antibody or nanobody CDR workflows.

Query live:

```bash
tamarind --json tools --function binder-design
tamarind --json tools --function generate-small-mols
tamarind --json schema TOOL
```

Choose from account-visible tools based on the live description and schema. Do not assume that a remembered model name or setting is still available.

## Validate the generation stage

Upload target structures with `tamarind --json files upload PATH`, use the returned filename, and write `settings.yaml`.

```bash
tamarind --json validate TOOL --input settings.yaml --name DESIGN_NAME
```

Surface candidate count, sampling budget/steps, target site, scaffold/length range, refolding, and optional filters before submission. Candidate count can dominate weighted-hour spend; obtain explicit confirmation for material runs.

## Submit, recover, and analyze

Follow `tamarind-submit-and-poll` with a durable job name and bounded wait:

```bash
tamarind --json submit TOOL --input settings.yaml --name DESIGN_NAME
# Run tamarind-submit-and-poll's filtered status probe; use wait only for JobStatus.
tamarind --json wait DESIGN_NAME --timeout 14400 --poll-interval 20
tamarind --json results DESIGN_NAME --download /absolute/path/to/results
```

Rank extracted designs with:

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-binder-design-skill"
python3 "$SKILL_DIR/scripts/summarize_binder_metrics.py" /absolute/path/to/run --json
```

Resolve `SKILL_DIR` to the directory containing this `SKILL.md`; do not assume the shell is running from the skill directory.

Always propose a validation funnel: refold candidates independently, inspect interface confidence/geometry, remove liabilities and duplicates, then carry a diverse shortlist into wet-lab testing. Do not optimize on one metric alone.

Read [references/tools.md](references/tools.md), [references/peptide_macrocycle.md](references/peptide_macrocycle.md), and [references/examples.md](references/examples.md) for domain-specific choices.
