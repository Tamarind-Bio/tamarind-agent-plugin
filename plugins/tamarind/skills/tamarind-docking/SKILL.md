---
name: tamarind-docking
description: Dock or screen known ligands against a receptor, perform protein-protein docking, or score binding affinity/interface quality from existing structures with Tamarind Bio. Use for pocket-based or blind docking and pose ranking. Not for co-folding from sequence, generating a new ligand or binder, or general structure prediction.
---

# Dock and score binders

Start from the input the user actually has: receptor structure, ligand/SMILES/library, known pocket box, or an already formed complex.

## Discover the fitting tool

```bash
tamarind --json tools --function protein-ligand-docking
tamarind --json tools --function protein-protein-docking
tamarind --json tools --function binding-affinity
tamarind --json schema autodock-vina
```

- Use box-based physics dockers when the pocket coordinates are known.
- Use blind ML dockers when the site is unknown and the live schema supports the available inputs.
- Use score-only tools for a pose or complex that already exists.
- Do not send a sequence to a structure-only docking field; fold it first.

Closely related tools use different names for receptors, ligands, boxes, exhaustiveness, and scoring options. Confirm the exact schema before building settings.

## Prepare and validate

Upload structures or ligand files with `tamarind --json files upload PATH`. Use the returned bare filename. Keep receptor and ligand separate when the schema expects separate fields.

```bash
tamarind --json validate TOOL --input settings.yaml --name DOCK_NAME
```

Before submission, confirm pocket definition, blind versus box docking, ligand count, pose count, exhaustiveness/sampling, and any rescoring stage. Library size multiplies cost; route many ligands to `tamarind-batch`.

## Execute and analyze

Follow `tamarind-submit-and-poll`:

```bash
tamarind --json submit TOOL --input settings.yaml --name DOCK_NAME
# Run tamarind-submit-and-poll's filtered status probe; use wait only for JobStatus.
tamarind --json wait DOCK_NAME --timeout 7200 --poll-interval 15
tamarind --no-json results DOCK_NAME --download /absolute/path/to/results
```

For an extracted result directory:

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-docking-skill"
python3 "$SKILL_DIR/scripts/extract_docking_poses.py" /absolute/path/to/run --top 5 --json
```

Resolve `SKILL_DIR` to the directory containing this `SKILL.md`; do not assume the shell is running from the skill directory.

Report whether the ranking metric is lower-better energy/affinity or higher-better model confidence. Treat docking scores as prioritization evidence, not experimental binding proof.

Read [references/tools.md](references/tools.md) for method selection and [references/examples.md](references/examples.md) for input patterns.
