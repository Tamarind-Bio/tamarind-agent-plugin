# Selecting the right Tamarind tool

The catalog has many tools per task. Picking well is a reasoning problem, not a string match. These are the principles, with worked examples. The live `tamarind --json schema TOOL` result is always the final authority on what a tool actually takes and produces.

## 1. Match INTENT, not the tool name

Anchor on the user's actual problem: the **input they have**, the **output they need**, and their **constraints** (speed, "no MSA", a known pocket vs a blind search, a target structure vs sequence-only). Filter the catalog by `function` (and `modality`), then read each candidate's `description` and match it to that problem. Let those fields plus `tamarind --json schema TOOL` drive the pick.

A keyword search over tool names systematically mis-ranks, because the tool whose title most literally echoes the request wording is frequently not the established choice. Lead with the goal, not the noun the user happened to use.

Example: "I want to design a nanobody binder against this antigen." The intent is de novo antibody-family binder design against an epitope. Filter `modality="antibody"`, `function="binder-design"` / `"antibody-design"` and read the descriptions, rather than grabbing the first tool with "nanobody" in its name.

## 2. Identify upstream dependencies FIRST

Before recommending a tool, check what must already be true for it to run. Common prerequisites:

- **A structure**: inverse folding, docking into a pocket, structure-based developability, and structure-conditioned design all need a 3D structure. If the user has only a sequence, the upstream step is a fold.
- **An MSA**: some folders condition on a multiple-sequence alignment. The platform usually generates it, but on paths that skip MSA generation (e.g. finetuning) a precomputed MSA is a hard prerequisite.
- **A prepared ligand / a defined pocket**: classical docking needs a receptor, a ligand, and a bounding box around the site; it can't invent the pocket.
- **Annotation**: using CDR positions or interface residues requires running the annotation/numbering step first; never guess numbering.

If a required input isn't in hand, the recommendation includes the upstream step that produces it. Example: "redesign the surface of this sequence with ProteinMPNN". ProteinMPNN takes a **structure** (`pdbFile`) plus the residues to design, not a bare sequence, so the answer is "fold it first (AlphaFold / Boltz), then ProteinMPNN on the predicted structure."

Where a tool can **auto-derive** an input from what you give it (chain IDs, interface residues, a ligand pose from a complex), let it, and don't pre-compute that input before submitting unless the user asked or the tool genuinely can't infer it.

## 3. Commit to a PRIMARY, describe FIT not RANK

Name one primary tool, then 1-2 conditional alternatives framed by FIT rather than ranking:

> "Boltz is the default for folding this protein+ligand complex (it predicts the bound structure and a confidence score). If you only need a fast monomer fold and have no MSA, ESMFold2 is quicker. If you need an explicit affinity number for a small-molecule binder, Boltz's affinity head covers that."

Avoid superlatives ("best", "SOTA pick"). Note what would make a different tool fit better: it invites the user to share the constraint that actually decides it (do they have a target structure? do they need wet-lab-grade validation? a quick test or a production run?). Surface anti-matches ("don't use X for Y, use Z") only when comparing tools or correcting a wrong pick, not as a default; stay forward-looking about what to do.

## 4. Prefer the recognized STANDARD tool over a literal keyword match

This is the most common selection footgun. For de novo design (binders, antibodies / nanobodies / VHH, peptides, enzymes), when more than one tool could do the job, pick the established field-standard choice from domain knowledge, NOT the tool whose description most literally matches the request wording.

A tool whose name or blurb spells out the exact phrase the user typed ("VHH nanobody generator") is often a niche tool, while the recognized generalist that spans several modalities is the stronger pick even though its name matches the query less exactly. A multi-modality design tool is easy to skip on a narrow query precisely because keyword density under-ranks it. Lead the catalog read with modality/intent and give cross-modality generalists prominent consideration.

When the user has explicitly **named** a tool, evaluate THAT tool and confirm it fits the input they have, but still mention a clearly-better-fit alternative if one exists (a faster or more appropriate sibling in the same `tag` group often does).

## 5. Validate every GENERATIVE output

Any design or generative step produces candidates that need checking. Never end a recommendation at the generative step; name the validation step too:

- **Designed binder / backbone** → re-predict the complex structure and read interface confidence (ipTM / ipSAE / pDockQ); optionally a developability filter.
- **Designed sequence (inverse folding)** → fold the sequences back and confirm they recover the intended structure (low RMSD, high pLDDT).
- **Docked pose** → check the pose's confidence / affinity score and that it sits in the intended pocket.
- **Antibody design** → developability (e.g. a TAP-style profiler), humanness, and a structure prediction of the designed Fv.

The chain "design → fold/score → filter" is the shape of almost every real workflow; recommend it as a unit. (`tamarind-pipeline` orchestrates these as explicit, resumable CLI stages; `tamarind-results-analysis` reads the metrics back.)

## One clarifying question when the pick depends on an unspecified sub-class

If the top 1-2 picks would CHANGE based on a sub-class the user didn't specify, ask ONE focused question naming the relevant branches. Don't enumerate every sub-case's best tool in one sprawling answer, and don't guess. Skip the question when the user already specified or the inputs make it obvious. Examples of real branch points that change the tool:

- **Antibody vs nanobody (VHH)**: different generators and different developability profilers.
- **Blind docking vs a known pocket**: a blind/unknown-pocket docker vs a classical box-defined docker are different tools.
- **Production scale vs a quick test**: decides whether to keep the large generative default or shrink the design count.

## Calibration and honesty

- If you don't know whether a tool or parameter exists, query `tamarind --json tools` and `tamarind --json schema TOOL`; do not guess or invent a restriction to rationalize a gap.
- Don't fabricate platform facts (pricing, quotas, limits, hidden parameters). If a candidate's attributes aren't in the schema or docs and the choice genuinely turns on them (a benchmark number, a compute cost, a license), say what you'd need to verify rather than bluffing.
- Describe capabilities in scientific terms (structure prediction, binder design, docking, scoring, annotation), not by reciting internal tool function names.
