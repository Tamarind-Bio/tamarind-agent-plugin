---
name: tamarind-pipeline
description: "Use to chain MULTIPLE Tamarind Bio tools into one workflow where each step's output feeds the next (e.g. design -> fold -> score). Two composition modes: a DECLARATIVE server-side pipeline (submit-pipeline stages[] / run-pipeline) that the platform wires and runs as one object, and an IMPERATIVE campaign loop (submit -> poll -> read score -> branch, retry failures, pick a winner) you drive yourself when later steps depend on inspecting earlier results. Not for running ONE tool across MANY inputs (use tamarind-batch), not for a single job (use tamarind-submit-and-poll), not for first-time key setup (use tamarind-api-setup)."
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: chain multiple tools

Compose several tools into one workflow where one step's output is the next step's input: design a backbone, fold the designed sequences, score the interface, filter the survivors. This skill covers **two ways to express that chain**, and the load-bearing job is picking the right one and getting the data-flow wiring correct.

This skill builds on `tamarind-submit-and-poll` for all execution mechanics (validate, submit, poll to terminal, download, the by-name bare row, the two-step `/result`, the bare-filename file-param rule). It does not re-teach those; it adds the composition layer on top. For many inputs of ONE tool use `tamarind-batch`; for first-time key setup use `tamarind-api-setup`.

## Two composition modes

| | **Declarative pipeline** | **Imperative campaign loop** |
|---|---|---|
| What | A pre-wired DAG submitted as ONE object; the platform runs every stage and threads cross-stage data | You submit one job, poll it to terminal, READ the result, then decide the next job |
| When | The steps and tools are known up front and outputs chain cleanly **by type** | Later steps depend on inspecting an earlier RESULT: branch on a score, retry only the failures, pick a winner, stop early |
| API | `POST /submit-pipeline` (`stages[]` inline) or `POST /run-pipeline` (a pipeline saved in the UI) | repeated `tamarind-submit-and-poll` calls plus your own control flow |
| Control | The platform owns sequencing; you submit and wait | You own sequencing; you can read scores and change course mid-flight |

Default to the **declarative pipeline** when the plan is a fixed forward chain (design then fold then score with no decisions in between). Reach for the **campaign loop** the moment a step's behavior depends on reading a previous step's output, because a declarative pipeline can't branch on a score it hasn't computed yet.

The two are composable: a campaign loop can submit a declarative pipeline as one of its steps and branch on its aggregated result.

## Mode A: the declarative server-side pipeline

### Stage types must chain by input/output type

A pipeline is a list of stages, each a tool with an input type and an output type. Stage N's **output type must equal stage N+1's input type**, and stage 1's input type must equal the pipeline's declared initial input type. The platform's four canonical transforms:

| Transform | input -> output |
|---|---|
| Structure design (e.g. RFdiffusion) | pdb -> pdb |
| Inverse folding (e.g. ProteinMPNN) | pdb -> sequence |
| Mutate sequences | sequence -> sequence |
| Structure prediction (e.g. AlphaFold, Boltz) | sequence -> pdb |

So `rfdiffusion (pdb->pdb) -> proteinmpnn (pdb->sequence) -> alphafold (sequence->pdb)` is a valid chain (design a backbone, design sequences for it, fold each); a chain that puts a structure-prediction stage's `pdb` output into a stage that wants a `sequence` is invalid and will not wire. Scoring/filtering stages can slot at any position (they read, they don't transform the type).

### A stage can run MULTIPLE tools in parallel (fan-out)

A stage's `toolSettings` is keyed by tool name and can hold **more than one tool**. Every tool listed in a stage runs on that stage's input in parallel, and all their outputs flow to the next stage. This is how you express "try N tools at this step": put all N in one stage's `toolSettings`. So "fold this sequence with boltz AND chai AND protenix, then score every prediction with us-align AND dockq AND molprobity" is a valid TWO-stage declarative pipeline, not something you have to drive by hand:

```jsonc
{
  "jobName": "fold-compare-1",
  "initialInputs": ["MKT...EVQ"],
  "stages": [
    { "task": "Structure Prediction", "toolSettings": { "boltz": { "sequence": "pipe" }, "chai": { "sequence": "pipe" }, "protenix": { "sequence": "pipe" } } },
    { "task": "Scoring PDB",           "toolSettings": { "molprobity": { "pdbFile": "pipe" }, "pdockq": { "pdbFile": "pipe" } } }
  ]
}
```

Multi-tool fan-out is a first-class declarative-pipeline shape, NOT the imperative loop's job. When the user says "run all of these in parallel as a pipeline," reach for one stage with several `toolSettings` keys; do not tell them parallel tools aren't a pipeline shape, and do not split them into N separate runs.

A fan-out scoring stage pipes ONE structure (each upstream output) into each scorer, so SINGLE-input scorers (`molprobity`, `pdockq`, `protein-metrics`) drop in directly with one `pipe` field. PAIRWISE scorers compare TWO structures (`us-align` needs `pdbFile1`+`pdbFile2`, `dockq` needs `modelFile`+`nativeFile`, `rmsd-calculator` needs `pdbFile1`+`pdbFile2`), so they do NOT take a single bare `pipe`: read each scorer's `getJobSchema` for how its second input is supplied, and for an explicit all-vs-all comparison across the parallel folds reach for the imperative campaign loop instead (read each fold's output, then submit the pairwise comparisons).

### The body shape: jobName + initialInputs + stages

`/submit-pipeline` (inline stages) needs three things at the top level:

- **`jobName`** (NOT `pipelineName`): the run name for this pipeline invocation.
- **`stages`**: the list of stages. Each stage is `{task, toolSettings}` where `task` is the stage's CATEGORY label and `toolSettings` is **keyed by tool name**, with that tool's settings dict nested under the key (one or more tool keys, see the fan-out note above). The server reads each stage's tool list as `Object.keys(toolSettings)`, so the tool-name key is load-bearing and the stage `task` is the category, not the tool id. The exact `task` values: `Structure Design`, `Structure Prediction`, `Inverse Folding`, `Mutate Sequences`, and for a scoring stage the INPUT-TYPED form `Scoring PDB` / `Scoring Sequence` / `Scoring SMILES` / `Scoring SDF` (a bare `Scoring` is REJECTED by the engine, pick the one matching the stage input type).
- **`initialInputs`** (a LIST): the real head value(s) fed into stage 1. Required whenever stage 1 has a `"pipe"` field (it usually does). Items are uploaded bare filenames (do NOT email-prefix) or protein sequences.

The chained input field uses the `"pipe"` sentinel on EVERY stage, including stage 1:

- **Stage 1's** input field takes `"pipe"`, fed from the top-level `initialInputs` list at run time.
- **Stages 2 and later** take `"pipe"` in the field that consumes the prior stage's output; the platform substitutes the upstream output at run time.

Only the ONE field that receives upstream data gets `"pipe"`; every other setting on a stage's tool is a normal literal you fill in (number of designs, model variant, MSA on/off). Get the wrong field (or every field) set to `"pipe"` and the pipeline mis-wires.

```jsonc
// /submit-pipeline, stages[] inline (design -> fold)
{
  "jobName": "design-then-fold-run-1",
  "initialInputs": ["target.pdb"],   // head value LIST, fed into stage 1's "pipe"
  "stages": [
    { "task": "Structure Design",     "toolSettings": { "rfdiffusion": { "pdbFile": "pipe", "targetChains": ["A"], "binderLength": "60-100", "numDesigns": 8 } } },
    { "task": "Inverse Folding",       "toolSettings": { "proteinmpnn": { "pdbFile": "pipe", "designedResidues": { "A": "1 2 3 4 5" }, "numSequences": 4, "modelType": "proteinmpnn" } } },
    { "task": "Structure Prediction",  "toolSettings": { "alphafold":   { "sequence": "pipe", "numRecycles": 3 } } }
  ]
}
```

```jsonc
// /run-pipeline, run a pipeline saved in the UI; needs jobName + pipelineName + initialInputs
{ "jobName": "design-then-fold-run-1", "pipelineName": "design-then-fold", "initialInputs": ["target.pdb"] }
```

The exact field name that carries the chained value is per-tool (`pdbFile`, `sequence`, `proteinFile`, ...), so read each stage tool's `getJobSchema` to learn which field is its input. The field name that gets `"pipe"` on a stage is the one whose TYPE matches the prior stage's output type.

### Mirror the request; scoring and filtering stages are OPT-IN

The number-one failure mode is **adding stages the user did not ask for**, usually a scoring/filtering/validation step bolted on "because it's good practice." Build only the stages the request named:

- Scoring, filtering, validation, and analysis stages are **opt-in**. Include one only when the user used a word like score / rank / evaluate / filter / validate, or named a specific scoring tool.
- **Sanity-check the stage count**: count the distinct actions/tools the user named versus the stages in your plan. More stages than named tools means you are overreaching, re-read the request.
- If you think an extra stage would help, build what they asked and **suggest** the extra in chat text, let them decide. Do not silently expand the chain.
- When the user named a specific tool for a stage, that is a constraint: use exactly it. Do not fan out to alternatives they did not ask for (each alternative is another parallel branch and another cost multiplier).
- Don't ask for an input you already chose. If your own reasoning picked a synthetic/test input, put it in the spec and proceed; asking "which input?" after deciding is a round-trip the user opted out of. (User-owned workspace files still require asking before use, only fabricated test inputs are self-serve.)

Some tools carry a **pipeline-only** toggle that controls what gets piped downstream, e.g. `boltz` has `chooseBest` (pipe only the top-confidence model to the next stage). These are tagged `exclude: ["api", "batch"]` in the schema (pipeline context only), so they appear in a pipeline stage but not in a plain `submit-job`. Read `getJobSchema` to see which knobs are pipeline-scoped.

### Pause for manual filtering while testing

When you do add a score-filter stage, pause for manual inspection after it during testing (the UI's "Pause for manual filtering after this stage") and start with a small number of designs, so you confirm each stage's output is what you expect before committing a full run. Surface this to the user when the pipeline includes a filter.

### A pipeline parent can hang `Running` after its stages finish

A declarative pipeline parent occasionally stays `Running` even after every stage has reached `Complete` (the aggregation step doesn't always flip it). If the parent is stuck but the stage jobs are done: `cancelJob(<pipeline jobName>)` to clear the parent, then pull outputs **per file** via MCP `getJobFile` / `listJobFiles` (or read the stage jobs' own results directly). The whole-pipeline `/result` zip 400s once the parent is cancelled, so retrieve per-file, not the aggregated zip.

## Mode B: the imperative campaign loop

When later steps depend on reading earlier RESULTS, drive the chain yourself with the base lifecycle. The loop is **submit -> poll to terminal -> read the score -> decide**, and the decision is what a declarative pipeline can't express:

- **Branch on a score**: read the completed job's `Score` (pLDDT/ipTM/ipSAE/affinity, tool-dependent), then pick the next tool or settings based on the value.
- **Retry only the failures**: when a step submits many jobs, re-run just the `Stopped` ones (optionally with adjusted settings), not the whole set. Test ONE retry to terminal before re-running the rest.
- **Pick a winner**: rank the candidates from one step and carry only the top-K into the next.
- **Stop early**: end the campaign when a hit clears a threshold, instead of running every planned stage.

Execution mechanics (submit, the non-blocking poll, the by-name row, download) all come from `tamarind-submit-and-poll` (and `tamarind-batch` when a step is a screen). This skill adds the control flow around them. Persist job names to disk so a long campaign can re-attach from a fresh session rather than holding one process open. Worked recipe in [references/workflows.md](references/workflows.md).

The campaign-loop discipline mirrors the pipeline discipline: only run the steps the request named, surface a branch/threshold choice to the user before you commit weighted-hours to it, and treat scoring/filtering as opt-in.

## Surface consequential choices before submitting

A chain multiplies cost and runtime across every stage, so one default (number of designs per stage, model variant, MSA on/off, whether to add a scoring stage, the branch threshold in a campaign loop) compounds down the chain. When the request is open-ended, present the meaningful options plus the default you would otherwise apply and let the user pick **before** you submit the pipeline or start the loop, rather than choosing silently and reporting it after jobs are queued. This matters most at the FIRST stage, whose output count sets the width of everything downstream.

## How the two modes call the platform

- **Declarative**: `POST /submit-pipeline` with `{jobName, initialInputs, stages}` (each stage `{task: <category>, toolSettings: {<tool>: {...}}}`), or `POST /run-pipeline` with `{jobName, pipelineName, initialInputs}` for a UI-saved pipeline. Neither is in `openapi.yaml` (it covers the 8 core job endpoints only), so build the body from this skill plus each stage tool's live `getJobSchema`. Validate each stage tool's settings with MCP `validateJob` against that tool (the flat per-tool form, with a concrete value not `"pipe"`) before assembling the pipeline.
- **Imperative**: the `tamarind-submit-and-poll` recipe per step, with your own loop deciding the next step from the prior `Score`. Where the MCP is present, `submitBatch(fromJob=...)` is the cleanest single-call design->fold link (it reads a completed design job's generated sequences and folds each), and `listJobFiles(jobName)` gives a prior job's exact output `s3Path` for a file-typed next step.

## Validate every generative step

A pipeline can silently propagate a bad early design into expensive downstream folds. Before assembling stages (declarative) or before each loop step (imperative), `validateJob` each tool's settings with the MCP when present, and after a generative step completes, read at least one actual output artifact (a real PDB/CIF: coords, sequence, atom count), not just the metrics CSV, before feeding it forward. A passing CSV is necessary, not sufficient.

## Reference files

- [references/workflows.md](references/workflows.md): the declarative `submit-pipeline`/`run-pipeline` recipes (stage type-matching, head-value-in-`initialInputs` with every piped stage using the `pipe` sentinel), the imperative campaign-loop recipe (submit -> poll -> branch-on-score, retry-failures, pick-winner), and the MCP `submitBatch(fromJob=...)` design->fold shortcut.
- [references/examples.md](references/examples.md): validated stage payloads (the design->fold->score chain), the `pipe`-sentinel placement table, what fails and the exact error, and pipeline output shapes.
