# Tamarind Bio pipeline recipes

Chaining recipes in both modes. Execution mechanics (submit, poll, the by-name bare row, the two-step `/result`, the bare-filename file-param rule) come from `tamarind-submit-and-poll`; these recipes add the composition layer. All use `BASE = "https://app.tamarind.bio/api"` and `HEADERS = {"x-api-key": os.environ["TAMARIND_API_KEY"]}`. Neither pipeline endpoint is in `openapi.yaml`, so build the body from this file plus each stage tool's live `getJobSchema`.

The two composition modes:

- **Declarative** (recipes 1-3): a fixed forward chain submitted as one object. The platform runs every stage and threads cross-stage data.
- **Imperative** (recipes 4-5): you submit, poll, read the result, and decide the next step yourself, when a later step depends on inspecting an earlier one.

## 1. Declarative: design -> fold -> score, stages inline

`rfdiffusion (pdb->pdb)` then `proteinmpnn (pdb->sequence)` then `boltz (sequence->pdb)`. The top-level body needs `jobName` (the run name), `stages`, and `initialInputs` (a LIST: the head value, fed into stage 1's `"pipe"` field). Each stage's `task` is the CATEGORY label (Structure Design / Inverse Folding / Structure Prediction); its `toolSettings` is KEYED BY TOOL NAME, with that tool's settings nested under it. Stage 1's `"pipe"` field is fed from `initialInputs`; stages 2+ take the `"pipe"` sentinel in the ONE field that consumes the prior stage's output.

```python
import os, requests
BASE = "https://app.tamarind.bio/api"
HEADERS = {"x-api-key": os.environ["TAMARIND_API_KEY"]}

pipeline = {
    "jobName": "binder-design-run-1",
    "initialInputs": ["target.pdb"],   # head value (real uploaded bare filename, NOT email-prefixed); a LIST
    "stages": [
        # Stage 1: design backbones for the uploaded target; pdbFile = "pipe" (fed from initialInputs)
        {"task": "Structure Design", "toolSettings": {
            "rfdiffusion": {
                "task": "Binder Design", "pdbFile": "pipe", "targetChains": ["A"],
                "binderLength": "60-100", "numDesigns": 8}}},
        # Stage 2: design sequences for each backbone (pdb in -> sequence out); pdbFile = "pipe"
        {"task": "Inverse Folding", "toolSettings": {
            "proteinmpnn": {
                "pdbFile": "pipe", "designedResidues": {"A": "1 2 3 4 5"}, "numSequences": 4, "modelType": "proteinmpnn"}}},
        # Stage 3: fold each designed sequence and score the interface; sequence = "pipe"
        {"task": "Structure Prediction", "toolSettings": {
            "boltz": {
                "inputFormat": "sequence", "sequence": "pipe", "numRecycles": 3}}},
    ],
}
requests.post(f"{BASE}/submit-pipeline", headers=HEADERS, json=pipeline).raise_for_status()
```

Only the input field per stage is `"pipe"` (stage 1's `pdbFile` fed from `initialInputs`, stage 2's `pdbFile`, stage 3's `sequence`); every other setting is a normal literal. The field that gets `"pipe"` is the one whose TYPE matches the prior stage's output type (stage 1 outputs pdb -> stage 2's `pdbFile`; stage 2 outputs sequence -> stage 3's `sequence`). The server reads each stage's tool list from `Object.keys(toolSettings)`, so the tool-name key (`rfdiffusion`, `proteinmpnn`, `boltz`) is load-bearing; read each stage tool's `getJobSchema` to confirm its input field name.

## 2. Declarative: run a UI-saved pipeline with /run-pipeline

When the pipeline already exists (built in the UI at `app.tamarind.bio/pipelines`), drive it by name. `/run-pipeline` needs three required fields: `jobName` (a NEW run name for this invocation), `pipelineName` (the saved pipeline's name), and `initialInputs` (a LIST: the head value). The saved stages are already pre-wired with `"pipe"`, so you only pass the head value:

```python
requests.post(f"{BASE}/run-pipeline", headers=HEADERS, json={
    "jobName": "binder-design-run-1",            # NEW run name (required)
    "pipelineName": "binder-design-pipeline",    # the saved pipeline (required)
    "initialInputs": ["target.pdb"],             # head value LIST; stages are pre-wired with "pipe"
}).raise_for_status()
```

## 3. Validate every stage before assembling (MCP)

A pipeline propagates a bad early stage into expensive downstream folds. When the MCP is present, dry-run each stage's `toolSettings` against its tool BEFORE submitting the pipeline, with the stage-1 real value (not `"pipe"`) so you validate a concrete payload:

```
getJobSchema(jobType="rfdiffusion")          # learn stage-1 required fields + input field name
validateJob(jobName="stage1-check", type="rfdiffusion",
            settings={"task": "Binder Design", "pdbFile": "target.pdb",
                      "targetChains": ["A"], "binderLength": "60-100", "numDesigns": 8})
# act on verdict["valid"]; fix verdict["error"] before wiring this stage in.
```

`"pipe"` itself is a runtime sentinel, not a validatable value, so validate each stage with a representative concrete input for the field that will later be `"pipe"`. Then swap in `"pipe"` for the chained field on stages 2+ when you assemble the pipeline.

## 4. Imperative campaign loop: submit -> poll -> branch on score

When a later step depends on reading an earlier RESULT, drive the chain yourself. Here: fold candidates, read each `Score`, and only carry the high-confidence designs forward.

```python
import json
from tamarind_client import submit_job, wait_for, get_job, download   # see tamarind-submit-and-poll

candidates = {"cand-a": "MKT...", "cand-b": "AVF...", "cand-c": "GEV..."}

# Step 1: fold each candidate
for name, seq in candidates.items():
    submit_job(name, "boltz", {"inputFormat": "sequence", "sequence": seq})

# Step 2: poll to terminal, read the score, BRANCH
winners = []
for name in candidates:
    row = wait_for(name)                          # polls JobStatus to terminal, raises on Stopped
    score = json.loads(row.get("Score") or "{}")
    if score.get("plddt", 0) >= 80:               # threshold is a choice; surface it to the user first
        winners.append(name)

# Step 3: only the winners advance to the next tool (e.g. a developability filter)
for name in winners:
    download(name)                                # carry the structure forward
    # submit_job(f"{name}-tap", "tap", {...})     # next stage, gated on the branch above
```

`Score` is a JSON string on the completed row; the keys are tool-family dependent (folding: `plddt`/`ptm`/`iptm` plus interface metrics `ipSAE_*`/`pDockQ_*` for complexes). Read the keys, do not assume golden values. The threshold (`>= 80` here) is a consequential choice: surface it to the user before committing weighted-hours to the branch.

## 5. Imperative: retry only the failures, then pick a winner

`Stopped` jobs in a step are the ones to re-run, not the whole set. **Test ONE retry to terminal before re-running the rest** (the original failure may not be the only cause):

```python
from tamarind_client import get_job, submit_job, wait_for

names = json.load(open("pending_jobs.json"))
failed = [n for n in names if get_job(n)["JobStatus"] == "Stopped"]

if failed:
    # test ONE retry first (maybe with adjusted settings), confirm it reaches Complete...
    submit_job(f"{failed[0]}-retry", "boltz", {"inputFormat": "sequence", "sequence": "...", "numRecycles": 5})
    if wait_for(f"{failed[0]}-retry")["JobStatus"] == "Complete":
        for n in failed[1:]:                       # ...then re-run the rest
            submit_job(f"{n}-retry", "boltz", {"inputFormat": "sequence", "sequence": "..."})
```

For the win-picking step, rank the completed candidates by their interface metric and carry only the top-K forward (see `tamarind-results-analysis` for metric read-back, or `tamarind-batch` when the step is a many-input screen).

## 6. MCP shortcut: the design -> fold link in one call

When a step is "fold every sequence a design job produced," MCP `submitBatch(fromJob=...)` reads the completed design job's generated sequences and folds each as one batch, no download/re-upload:

```
# design job already Complete; fold all its sequences in one call:
submitBatch(batchName="verify-designs", type="alphafold", fromJob="my-proteinmpnn-job")
```

Then poll the batch parent's `batchStatus` (see `tamarind-batch`). This is the imperative-mode analog of a declarative `proteinmpnn -> alphafold` stage pair, useful inside a campaign loop where you want to inspect the design job before folding. For a file-typed next step, `listJobFiles(jobName)` returns each output's `s3Path` to reference directly.

## Notes

- **Stage type-matching:** structure design (pdb->pdb), inverse folding (pdb->sequence), mutate sequences (sequence->sequence), structure prediction (sequence->pdb). Stage N output type must equal stage N+1 input type; scoring stages slot anywhere.
- **The `pipe` sentinel** with `/submit-pipeline` appears on stage 1's input field too (fed from the `initialInputs` list); the real head value lives in top-level `initialInputs`, not inlined in stage 1. With `/run-pipeline` the saved stages are already pre-wired with `"pipe"` and you pass only `jobName` + `pipelineName` + `initialInputs`. Only the ONE field matching the upstream output type gets `"pipe"`.
- **Mirror the request:** build only the stages named; scoring/filtering/validation stages are opt-in (see SKILL.md).
- **Pause for manual filtering** while testing a scored pipeline, and start with a small design count.
