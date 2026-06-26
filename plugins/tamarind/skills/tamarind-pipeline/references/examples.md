# Tamarind Bio pipeline examples, sentinel placement, and output shapes

Validated stage payloads and the wiring rules. The freshest per-tool example is each stage tool's `getJobSchema(<tool>)` `exampleJob`; run `validateJob` on a stage's `toolSettings` (with a concrete value, not `"pipe"`) before assembling the pipeline. Tool schemas evolve, so re-fetch if one stops validating. Sequences and filenames here are illustrative, swap your own.

`BASE = "https://app.tamarind.bio/api"`, `HEADERS = {"x-api-key": <key>}`.

## The `pipe`-sentinel placement table

The single most-missed mechanic: the head value lives in the top-level `initialInputs` LIST, and EVERY stage (including stage 1) gets `"pipe"` in the ONE field whose TYPE matches the upstream output. Stage 1's `"pipe"` is fed from `initialInputs`; stages 2+ from the prior stage. Everything else is a normal literal.

| Stage | task (category) | tool key | output type | input field | value to put there |
|---|---|---|---|---|---|
| 1 | Structure Design | rfdiffusion | pdb | `pdbFile` | `"pipe"` (fed from `initialInputs`) |
| 2 | Inverse Folding | proteinmpnn | sequence | `pdbFile` | `"pipe"` (consumes stage 1's pdb) |
| 3 | Structure Prediction | alphafold / boltz | pdb | `sequence` | `"pipe"` (consumes stage 2's sequence) |

The real head value is the top-level `initialInputs` LIST (`["target.pdb"]`), used identically by both `/submit-pipeline` (inline stages) and `/run-pipeline` (UI-saved pipeline). Only ONE field per stage is `"pipe"`; setting more than one (or every field) mis-wires the stage. Note the two levels: a stage's `task` is the CATEGORY label (Structure Design, Inverse Folding, Structure Prediction), and its `toolSettings` is KEYED BY TOOL NAME with that tool's settings nested under the key.

## Stage type-matching reference

A stage's input type must equal the previous stage's output type:

| Transform | input -> output | example tools |
|---|---|---|
| Structure design | pdb -> pdb | `rfdiffusion`, `rfdiffusion3` |
| Inverse folding | pdb -> sequence | `proteinmpnn`, `ligandmpnn` |
| Mutate sequences | sequence -> sequence | sequence-editing tools |
| Structure prediction | sequence -> pdb | `alphafold`, `boltz`, `chai`, `esmfold2` |

Valid chains keep types matched end to end. `rfdiffusion (pdb->pdb) -> proteinmpnn (pdb->sequence) -> alphafold (sequence->pdb)` is valid. Putting a structure-prediction stage's `pdb` output into a stage that wants a `sequence` does not wire. Scoring/filtering stages read without transforming the type, so they slot at any position.

## Validated stage payloads (design -> fold -> score)

Each block below is the per-tool settings dict that nests under the tool-name key inside a stage's `toolSettings`. A full `/submit-pipeline` stage wraps it as `{"task": "<category>", "toolSettings": {"<tool>": { ...settings... }}}`. The input field is `"pipe"` on every stage (stage 1's `pdbFile` is fed from the top-level `initialInputs` list). The real uploaded bare filename goes in `initialInputs` (`["target.pdb"]`), not inside a stage.

Assembled, the first two stages look like:
```json
{ "task": "Structure Design",
  "toolSettings": { "rfdiffusion": { "task": "Binder Design", "pdbFile": "pipe",
      "targetChains": ["A"], "binderLength": "60-100", "numDesigns": 8 } } }
{ "task": "Inverse Folding",
  "toolSettings": { "proteinmpnn": { "pdbFile": "pipe", "designedResidues": {"A": "1 2 3 4 5"}, "numSequences": 4, "modelType": "proteinmpnn" } } }
```

### Stage 1: rfdiffusion (Binder Design, pdb -> pdb)
```json
{ "task": "Binder Design", "pdbFile": "pipe", "targetChains": ["A"],
  "binderLength": "60-100", "binderHotspots": {"A": "45 47 52"}, "numDesigns": 8 }
```
`pdbFile` is `"pipe"`, fed from the top-level `initialInputs` list (whose value is the real uploaded bare filename, NOT email-prefixed). The inner `task` here ("Binder Design") is rfdiffusion's own setting; the STAGE-level `task` is the category label "Structure Design". Hotspots are space-separated within a chain.

### Stage 2: proteinmpnn (Inverse folding, pdb -> sequence)
```json
{ "pdbFile": "pipe", "designedResidues": {"A": "1 2 3 4 5"}, "numSequences": 4, "modelType": "proteinmpnn" }
```
`pdbFile` consumes stage 1's pdb output, so it is `"pipe"`. `designedResidues` is REQUIRED for proteinmpnn (which residues to redesign, keyed by chain); `numSequences`/`modelType` are normal literals. `modelType` is in `proteinmpnn`/`ligandmpnn`/`solublempnn`/`hypermpnn`/`abmpnn`. Note `designedChains` and `verifySequences` are tagged `exclude` (UI/next-step only), do not put them in a pipeline stage's `toolSettings`.

### Stage 3: boltz (Structure prediction, sequence -> pdb)
```json
{ "inputFormat": "sequence", "sequence": "pipe", "numRecycles": 3 }
```
`sequence` consumes stage 2's sequence output, so it is `"pipe"`. `inputFormat` is **required** for boltz/chai even in a pipeline (a `"pipe"` sequence still needs `inputFormat: "sequence"`).

### Stage 3 alternative: alphafold (Structure prediction, sequence -> pdb)
```json
{ "sequence": "pipe", "numModels": "1", "numRecycles": 3 }
```
AlphaFold needs only `sequence` (`"pipe"` here). `numModels` is a string dropdown (`"1"`-`"5"`).

### Pipeline-only "pipe the best model" toggle
Some folding tools expose a pipeline-scoped knob that controls what flows downstream, e.g. `boltz` has `chooseBest` (pipe only the top-confidence model `model_0` to the next stage). It is tagged `exclude: ["api", "batch", "tools"]`, so it is meaningful only inside a pipeline stage, not a plain `submit-job`. Read `getJobSchema(<tool>)` for which knobs are pipeline-scoped before relying on one.

## Mirror-the-request examples

- User: "design binders for my target and fold them." -> TWO transforms (design, fold), so a design->inverse-folding->prediction chain. Do NOT add a scoring or developability stage; the user did not ask.
- User: "design binders, fold them, and **rank** by interface confidence." -> the word "rank" opts in a scoring read-back. Add it (or do the ranking in a campaign-loop step).
- User: "design binders with **RFdiffusion**." -> the named tool is a constraint. Use `rfdiffusion`; do not fan out to `bindcraft`/`boltzgen` branches they did not ask for.

## What fails (and why)

- **Missing `initialInputs`** -> stage 1's `"pipe"` input field has nothing to draw from; the top-level `initialInputs` LIST carries the real head value into stage 1. It is required whenever stage 1 has a `"pipe"` field (it usually does).
- **`pipelineName` on `/submit-pipeline`** -> the inline-stages endpoint wants `jobName` (the run name), not `pipelineName`. `pipelineName` is a `/run-pipeline` field only (the saved UI pipeline's name).
- **Flat `toolSettings`, or a tool id as the stage `task`** -> the server reads each stage's tools from `Object.keys(toolSettings)`, so `toolSettings` must be KEYED BY TOOL NAME with the settings nested under it, and the stage `task` must be the CATEGORY label (Structure Design / Inverse Folding / Structure Prediction), not the tool id.
- **More than one field set to `"pipe"` on a stage** -> only the field whose type matches the upstream output should be `"pipe"`; the rest are literals. Extra `"pipe"`s mis-wire the stage.
- **Type-mismatched chain** (a stage's input type != prior stage's output type) -> the pipeline does not wire. Check the type table above before assembling.
- **Adding an unrequested scoring/filter stage** -> overreaching. Count named tools vs planned stages; build only what was asked, suggest extras in chat.
- **boltz/chai stage without `inputFormat`** -> a `"pipe"` sequence still fails validation without `inputFormat: "sequence"`. Required fields are still required in a pipeline.
- **Validating `"pipe"` literally** -> `"pipe"` is a runtime sentinel, not a real input; validate each stage with a concrete representative value, then swap in `"pipe"` for the chained field when assembling.

## Output shapes (describe, don't expect exact values)

- **Declarative pipeline**: each stage runs as its own job(s); a fan-out stage (one design job -> N folds) produces a set of downstream jobs. Watch progress per stage (In Queue / Running / Complete counts). Each stage's outputs are that tool's normal outputs (structures + scores CSV + logs), chained automatically to the next stage's input.
- **Campaign loop**: each step is a normal single job or batch; you read its `Score` (JSON string on the completed row, keys tool-family dependent) and decide. Persist job names so a long campaign re-attaches from a fresh session.
- **Scores** carry the same per-family metrics as single jobs (folding: `plddt`/`ptm`/`iptm` plus interface `ipSAE_*`/`pDockQ_*` for complexes). Read the keys; outputs are non-deterministic, reason about the shape, not golden numbers.
- A **passing metrics CSV is necessary, not sufficient** at any stage. Pull at least one actual output structure (coords, sequence, atom count) before feeding it forward, especially after a generative step.
