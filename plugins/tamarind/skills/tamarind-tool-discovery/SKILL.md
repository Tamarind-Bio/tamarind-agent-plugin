---
name: tamarind-tool-discovery
description: Use when you don't know WHICH Tamarind Bio tool fits a goal. Discover live with getAvailableTools / listModalities / listTags, then confirm params with getJobSchema. Match the user's INTENT not the tool name, identify upstream dependencies first, name a primary plus 1-2 conditional alternatives, prefer the recognized standard tool over a literal keyword match, and always validate generative output. Not for running a tool you already know (use its domain skill or tamarind-submit-and-poll), not for first-time key setup (use tamarind-api-setup).
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: pick the right tool

Tamarind runs hundreds of biology tools through one job API. This skill answers "which one fits this goal?" It is **discovery and selection only** (it does not submit). Once you've picked a tool and confirmed its schema, run it with `tamarind-submit-and-poll` (validate, submit, poll, download), screen many inputs with `tamarind-batch`, or chain tools with `tamarind-pipeline`. If `TAMARIND_API_KEY` is unset or a call returns 401, run `tamarind-api-setup` first.

The catalog drifts constantly (tools are added, renamed, versioned). **Never recommend a tool from memory.** Discover live, then confirm the exact params with `getJobSchema` before you tell the user what to run. A recommendation you didn't verify against the live catalog is a guess.

## The two filter axes (discover live, don't hardcode)

The catalog is filtered on two axes, and the live vocabulary for both is itself discoverable, so fetch it rather than hardcoding (it changes as tools are added):

- **Modality** = the molecule type (protein, antibody, small-molecule, enzyme, peptide, nucleic-acid, …). Get the live list with MCP `listModalities()`.
- **Function** = what the tool does (structure-prediction, binder-design, protein-ligand-docking, inverse-folding, developability, molecular-dynamics, …). Get the live list with MCP `listTags()`.

Each entry carries `value`, `label`, a `description`, and a live `toolCount`. Filter the catalog by either or both:

```
listModalities()                                          # the molecule-type axis, with counts
listTags()                                                # the function axis, with counts
getAvailableTools(function="binder-design")               # tools that do binder design
getAvailableTools(modality="antibody", function="structure-prediction")   # narrow on both
getAvailableTools(search="boltz")                         # free-text fallback
getJobSchema(jobType="boltz")                             # exact params + required fields + exampleJob
```

Over plain REST without the MCP, `GET /tools` returns the **full list** with each tool's inline `settings`; filter client-side on `name` / `displayName` / `description` (REST does not filter server-side and does not carry the `categories`/`tags` facets, an MCP-only convenience). See [references/tool_catalog.md](references/tool_catalog.md) for how to read what comes back, and `tamarind-api-setup` for the REST-vs-MCP surfaces.

## How to choose (the reasoning, not a lookup table)

A keyword search over tool names mis-ranks: the tool whose description most literally echoes the request is often **not** the right pick. Reason about FIT instead. The full principles, with worked examples, are in [references/selection_principles.md](references/selection_principles.md); the spine:

1. **Match the user's INTENT, not the tool name.** Anchor on the input they have, the output they need, and their constraints (speed, "no MSA", a known pocket vs a blind search), then filter by `function` and read each candidate's `description`. The tool that names their keyword in its title is frequently the wrong one.
2. **Identify upstream dependencies FIRST.** Before recommending a tool, check what must be true for it to run: does it need a structure, an MSA, a prepared ligand, an annotated complex, a fixed backbone? If a required input isn't in hand, recommend the upstream step that produces it as part of the answer (e.g. fold a structure before inverse-folding it; annotate antibody numbering before using CDR positions).
3. **Name a primary plus 1-2 conditional alternatives.** Commit to one primary tool, then describe FIT not RANK for the alternatives ("X is the default here; use Y if you don't have a target structure; Z if you need wet-lab-grade validation"). Avoid superlatives ("best", "SOTA"). Note what would make a different tool fit better: it invites the user to share the constraint that decides it.
4. **Prefer the recognized standard tool over a literal keyword match.** For de novo design especially (binders, antibodies/nanobodies, peptides, enzymes) when more than one tool could do it, pick the established field-standard choice, not the tool whose name keyword-matches hardest. A general-purpose design tool listed across several modalities is often the right answer on a narrow query, even though a niche tool's name matches the wording more exactly.
5. **Always validate generative output.** Any design or generative step (binder, sequence, structure, docked pose) needs a downstream validation tool: re-predict the structure, compute interface/confidence metrics, or run a developability filter. Don't end a recommendation at the generative step; name the validation step too.

When the user has already NAMED a tool, evaluate that one and confirm it fits, but still mention a better-fit alternative if one clearly exists. When the right pick genuinely depends on an unspecified sub-class (antibody vs nanobody, blind vs known-pocket docking), ask ONE focused question naming the branches rather than enumerating every sub-case.

## Confirm before recommending: getJobSchema is the authority

Existence and parameters both come from the live schema, never from memory:

- `getJobSchema(jobType)` returns the tool's exact `parameters` (with `required`, `type`, `default`, `options`, `conditionals`), its `categories`/`tags`, and an `exampleJob` starting payload. If it returns not-found, the tool isn't on the platform: say so and propose the closest hosted alternative (re-checked with another `getJobSchema`).
- Read the schema for **required** fields before claiming a tool takes a given input. Many tools need more than the obvious field: `boltz` requires `inputFormat` plus `sequence`; `proteinmpnn` requires a `pdbFile` plus the residues to design; `autodock-vina` requires a receptor file, a ligand, AND a bounding box. Don't assume a single sequence is enough.
- Keep the schema's defaults. They are tuned (generative tools default to large design counts on purpose); don't substitute conservative test values unless the user asked for a quick test.
- Where the MCP `validateJob` is present, it's the final authority on whether a settings blob will submit, but it's an improvement, not a gate (run it before submitting via `tamarind-submit-and-poll`; if it's absent, proceed and let submit validate). It is not needed just to PICK a tool; `getJobSchema` is enough for selection.

## Gated tools are invisible to external users: filter them

Some catalog tools are restricted (org-allowlisted, or behind a feature flag for a pre-release set). An external user **cannot run them**, so never recommend one. Two rules:

- `getAvailableTools` is scoped to the authenticated account, so for org-restricted tools it already reflects access (a tool the account can't use generally won't appear). Recommend from what discovery returns for THIS account, not from a remembered global list.
- **`getAvailableTools` does NOT honor the feature-flag gate.** A feature-flagged pre-release tool can appear in the MCP listing for an internal/privileged key yet be hidden from a normal external user on the website. So a tool surfacing in discovery is necessary but not sufficient: if a candidate looks like an unreleased or flagged variant of a shipped tool, prefer the shipped, ungated equivalent. When in doubt, recommend the stable public tool, and if the user names a tool they can't access, tell them it's gated and route them to their account admin rather than suggesting a workaround.

## Don't burn a job on a trivial property

Reserve weighted-hours jobs for work that needs the platform: GPU / ML inference, MSA generation, generative design, molecular dynamics, structure prediction, or anything whose output must persist as a citable artifact or feed a downstream pipeline. For a **trivial sequence/structure property you can compute locally in seconds** (hydrophobicity, GRAVY, net charge, sequence stats, SASA, a Cα distance map, basic small-molecule descriptors), compute it inline with a local library (BioPython, biotite, RDKit) instead of submitting a Tamarind job. Submitting a platform job for a one-line local calculation wastes the user's weighted-hours and adds queue latency for no benefit.

## Quick orientation by intent

A starting map from common goals to the discovery filter and a recognized anchor tool. **Verify live**: these names and the catalog drift, and `getJobSchema` is the authority. Full reasoning and the disambiguation cautions are in [references/selection_principles.md](references/selection_principles.md).

| The user wants to… | Discover with | Anchor tools (verify live) |
|---|---|---|
| Predict / co-fold a structure from sequence | `function="structure-prediction"` | `boltz`, `alphafold`, `chai`, `esmfold2` |
| Design a de novo binder | `function="binder-design"` | `bindcraft`, `rfdiffusion`, `boltzgen` |
| Engineer an antibody / nanobody | `modality="antibody"` | `rfantibody`, `immunebuilder`, `proteinmpnn` (abmpnn model) |
| Design sequence for a fixed backbone | `function="inverse-folding"` | `proteinmpnn`, `ligandmpnn`, `esm-if1` |
| Score developability (stability, aggregation, …) | `function="developability"` | `tap` (antibody), `thermompnn`, `netsolp` |
| Dock a ligand / predict binding affinity | `function="protein-ligand-docking"` / `"binding-affinity"` | `autodock-vina`, `diffdock`, `boltz` (co-fold) |
| Anything else (enzyme, small-mol, MD, RNA, cryo-EM) | `listTags()` then filter | see `tamarind-more-tools` |

Most domains have a dedicated skill (`tamarind-structure-prediction`, `tamarind-binder-design`, `tamarind-antibody`, `tamarind-inverse-folding`, `tamarind-developability`, `tamarind-docking`); the long tail lives in `tamarind-more-tools`. Once you've picked, hand off to the domain skill or `tamarind-submit-and-poll`.

## Reference files

- [references/selection_principles.md](references/selection_principles.md): the full reasoning principles with worked disambiguation examples (intent-over-keyword, upstream-dependency-first, primary-plus-alternatives, standard-over-literal-match, validate-every-generative-step) and the one-clarifying-question rule.
- [references/tool_catalog.md](references/tool_catalog.md): the modality / function map, how to read tool and parameter metadata from `getAvailableTools` / `getJobSchema`, and the gated-tool filtering rule.
