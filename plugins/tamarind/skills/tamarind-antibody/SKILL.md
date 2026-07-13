---
name: tamarind-antibody
description: Design, redesign, model, number, humanize, or search antibodies, nanobodies/VHHs, and TCRs with Tamarind Bio. Use for CDR-aware or repertoire-specific workflows and antibody developability handoffs. Not for general non-antibody binder design, generic complex folding, or developability scoring alone.
---

# Engineer antibodies and nanobodies

Clarify the modality and goal: antibody versus nanobody/VHH/TCR; de novo CDR design versus redesign; structure prediction; numbering; humanization; or repertoire/paratope search.

## Select and inspect the tool

```bash
tamarind --json tools --modality antibody
tamarind --json tools --modality antibody --function antibody-design
tamarind --json tools --modality antibody --function structure-prediction
tamarind --json schema TOOL
```

Prefer antibody-specific tools when chain pairing, CDR regions, framework numbering, epitope/hotspot steering, or humanization matters. Route generic co-folding to `tamarind-structure-prediction` and non-antibody binders to `tamarind-binder-design`.

## Build and validate

Capture heavy/light or VHH sequence, framework, antigen structure and chain, epitope/hotspots, CDR regions/lengths, design count, and omitted residues as required by the live schema. Upload structures with `tamarind --json files upload PATH` and use the returned filename.

```bash
tamarind --json validate TOOL --input settings.yaml --name AB_NAME
```

Confirm chain identities, numbering scheme, CDR scope, candidate count, refolding, and optional filters before spending. Do not pass UI-only or excluded fields shown by the schema.

## Execute and filter

Follow `tamarind-submit-and-poll`:

```bash
tamarind --json submit TOOL --input settings.yaml --name AB_NAME
# Run tamarind-submit-and-poll's filtered status probe; use wait only for JobStatus.
tamarind --json wait AB_NAME --timeout 14400 --poll-interval 20
tamarind --json results AB_NAME --download /absolute/path/to/results
```

For design outputs:

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-antibody-skill"
python3 "$SKILL_DIR/scripts/summarize_binder_metrics.py" /absolute/path/to/run --json
```

Resolve `SKILL_DIR` to the directory containing this `SKILL.md`; do not assume the shell is running from the skill directory.

Rank on interface confidence and geometry, then apply antibody-specific developability filters through `tamarind-developability`. Preserve sequence diversity and flag liabilities rather than selecting only the top scalar score.

Read [references/tools.md](references/tools.md) and [references/examples.md](references/examples.md) for antibody-specific settings and caveats.
