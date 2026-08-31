---
name: tamarind-mcp-pipeline
description: Author, validate, run, monitor, and read results from declarative multi-step Tamarind Bio pipelines through MCP with submitPipeline, validatePipeline, getPipelineSchema, getPipelineTemplate, listPipelineTemplates, getPipelineRun, getPipelineRunResults, listPipelineRuns, and stopPipelineRun. Use when stages depend on earlier stages (design to fold to score), or to run or re-run a saved pipeline template. Not for a single job, one independent batch, or CLI orchestration.
---

# Run Tamarind pipelines through MCP

A pipeline is a declarative graph the server runs for you: it dispatches each step's jobs, waits for
their molecules to land, and feeds them to the next step. Do not chain jobs by hand out of
`submitJob`/`submitBatch` polling.

| tool | use it for |
|---|---|
| `getPipelineSchema` | the IR schema + authoring guide — **read before writing a graph** |
| `listPipelineTemplates` | find a saved pipeline instead of authoring one |
| `getPipelineTemplate` | one template's graph + the manifest of inputs you must bind |
| `validatePipeline` | judge a run **before** it spends compute |
| `submitPipeline` | run it (spends compute) |
| `getPipelineRun` | poll status and per-step progress |
| `getPipelineRunResults` | read the molecules and scores each step produced |
| `listPipelineRuns` | find runs — they do **not** appear in `getJobs()` |
| `stopPipelineRun` | stop a run — **not** `cancelBatch` |

## Path A — run a saved template

Cheaper and safer than authoring. Always look before you author.

1. `listPipelineTemplates(search=...)` → pick an `id`. Rows are summaries and carry no graph.
   `owner` defaults to `"org"`, so you see templates you did not create; narrow with `owner="mine"`.
2. `getPipelineTemplate(templateId)` → read **`inputs`**: the manifest of what you must bind — the
   node id to key each binding by, molecule-vs-file, the molecule type, reference chain labels, and
   any `residueFields`.
3. `validatePipeline(...)` until `valid: true`.
4. `submitPipeline(...)`.

**Listed does not mean runnable.** Someone else's unpublished template lists fine, then fails
validation with `403 pipeline_permission_denied`. That is terminal — pick another or ask the owner to
publish. Prefer rows where `isPublished` is true or `createdBy` is you.

`settings` and `version` are **reference-mode only**. `settings` is `{nodeId: {settingKey: value}}`,
limited to the template's editable settings. Omit `version` for published-then-latest.

## Path B — author a graph inline

Only when nothing suitable exists. Passing `pipeline` to `submitPipeline` saves a new unpublished
template you own and runs it in one call.

Call `getPipelineSchema()` first, every time — it is fetched live, so it always matches the deployed
validator. Authoring blind reliably produces graphs the API rejects. Rules from it you cannot guess:

- **No edge list.** Topology lives inside each node's `inputs`, where a node names what it consumes.
- **Omit `metadata.defaultGroup` on an inline graph.** It is required only when SAVING a template;
  inline, the binding supplies the group. Do not hunt for a group id or borrow one — submit fills a
  *missing* `defaultGroup` from your binding but **never replaces one you left in**, and an
  unresolvable id is not rejected, so a placeholder becomes a permanent reference to molecules the
  run never used.
- **A `filter` must do something:** `intersect: true` (which needs ≥2 sources) or ≥1 rule. An empty
  filter is invalid, not a pass-through.
- **Residue selections go in the binding**, never in a node's `settings`.

## Bindings

One entry per input node, keyed by that node's id. Supply molecules **exactly one way**:

```jsonc
{"inputProtein": {"group": "<groupId>"}}      // an existing molecule group
{"inputProtein": {"sequences": ["MKT..."]}}   // or raw values — server mints the group,
{"inputLigand":  {"smiles": ["CCO"]}}         // and rolls it back if the submit fails
{"inputTarget":  {"pdbs": ["<uploadedPath>"]}}
{"inputLigand":  {"sdfs": ["<uploadedPath>"]}}
{"inputCsv":     {"file": "<path>"}}          // a file input
```

`pdbs`/`sdfs` take paths relative to your user folder for files you already uploaded — not contents.

Two optional keys inside a binding:

- **`residuesByChain`**, in one of **two shapes**. The wrong shape against an existing `templateId`
  is rejected `422`:

  ```jsonc
  // ADVANCED — the default for newly created templates. Per (tool node, field).
  {"residuesByChain": {"<toolNodeId>": {"designedResidues": {"A": "42-44,58-59"}}}}

  // SIMPLE — one selection for every residue field this input feeds.
  {"residuesByChain": {"A": "1-76"}}
  ```

  The shape is detected from the value: a chain → range **string** is simple, a node → **object** is
  advanced. `getPipelineTemplate` reports the mode in `simplifiedResidues`. Ranges are always
  strings, never lists: `"1-76"`, `"42 43 44"`, `"10-20,45,60-64"`.
- **`chainMapping`** — only when your chain IDs differ from the template's reference chains.

### The residue trap

A non-empty `residueFields` means the run **may** take a selection — **not** that it requires one.
Entries carry no per-field `required` flag, so the manifest cannot tell you which it is.

Inventing one is not a harmless default: it reaches the tool as designed residues, hotspots, or a
binding site, constraining the design to the wrong residues and spending GPU on scientifically wrong
output **that still looks successful**.

So do not guess — and do not refuse a runnable template either. Validate with the bindings you
actually have; a genuinely required selection comes back as `required-field-unset` naming the field.
Ask the user for the real one then.

`targetsChains` is not a reliable key for `residuesByChain`: it is empty on some entries, and on
others names a chain the input does not have (one the graph creates downstream).

## Validate before every submit

`submitPipeline` spends real compute. `validatePipeline` executes and saves nothing. Call it on the
same graph and bindings, and only submit on `valid: true`.

It reads what *describes* the run — `pipeline` or `templateId`+`version`, `bindings`, `settings`,
`name`. It ignores `runName`, `project` and `idempotencyKey`, which only name and tag the run.

Both outcomes return HTTP 200 — **read `valid`, do not branch on the status code.** Each error
carries a `code`, `severity`, the `node`, the `field` where there is one, and a fix-it `message`:

| code | usual cause |
|---|---|
| `required-field-unset` | often a residue selection — it belongs in the **binding**, not settings |
| `input-unbound` | an input node with no entry in `bindings` |
| `tool-unknown` | the node names a tool that does not exist |
| `setting-invalid` / `param-out-of-range` | a bad node setting |
| `chain-incompatible` | chain labels do not line up |
| `molecule-class-incompatible` | upstream does not produce what downstream consumes |

Two failure modes to handle deliberately:

- **`validationUnavailable` means NOT JUDGED** — there is no verdict, so do not start editing the
  graph in response to one. **Read `status`/`code` before retrying:** the flag is also set on a
  permanent `403 pipeline_permission_denied`, whose hint still says to retry. A 403 is terminal.
  Retry only a non-403, and if that fails identically every time, report it rather than looping.
- **`valid: true` is not a guarantee** that submit will accept the run. Validation does not confirm
  the tools exist, nor that a bound group exists or has anything in it. If submit rejects a graph
  validation approved, **believe submit** — re-validating will not reproduce it. Fix what submit
  names, usually a tool name or a group id, not the graph's shape.

## Submit, then poll

`submitPipeline` returns a run whose `id` is the `runId`. Pass `idempotencyKey` so a retried submit
is safe, `runName` to name this run explicitly, `project` to stamp an org project on its jobs.

Poll `getPipelineRun(runId)` on a **finite deadline** — never an unbounded loop. Steps are under
**`nodeRuns`**, each reporting `status`, `jobsTotal`/`jobsComplete`, `outputCount`, `outputGroup`.

- **A step carries two ids.** `id` is that step's own run id; `nodeId` is the stable pipeline node id,
  and `nodeId` is what `getPipelineRunResults(node=...)` wants.
- **The order is not stable and is not topological** — a dependent step can be listed ahead of the
  one it consumes, and the order can change between polls. Index by `nodeId`, never by position.

If a submit response is ambiguous, find the run with `listPipelineRuns` before retrying. Never submit
a second time to resolve uncertainty about the first.

## Read results

`getPipelineRunResults(runId)` returns each step's molecules **with their scores** — what you rank on.
Results appear per step as it finishes, so this is useful before the run completes; a step with
nothing yet reports an empty `molecules` list.

**The two tools name the same thing differently — do not carry keys across:**

| | array key | node id key |
|---|---|---|
| `getPipelineRun` | `nodeRuns` | `nodeId` |
| `getPipelineRunResults` | `steps` | `node` |

**Scores sit in different places depending on the shape you get. Read whichever you receive:**

- group molecules — id in `id`, scores under `metadata`
- step outputs — id in `complexId`, scores at top level in `scores`

Do not infer the shape from `outputGroup`: a step with one is normally read from the group but falls
back to its own outputs when the group returns nothing.

**`outputGroup: null` does not mean "nothing here."** It is the group a step *minted*. A step that
enriches its inputs in place — scoring, structure prediction — leaves molecules in the group they
arrived in, and a filter's survivors exist only as step outputs. Both report null and are read from
the step itself.

Paging: `limit` is 1-100 (default 25). Keep it small — molecules carry sequences, files and full
score history. To page one step, pass `node` for that step and `cursor` from its `nextCursor`; a
cursor belongs to one step, so `cursor` requires `node`.

## Stopping, and finding runs later

- Stop with `stopPipelineRun(runId)`. Finished steps keep their outputs; work in flight is cancelled.
  **Do not use `cancelBatch`** — it understands only the older job layout and will not stop a run.
- Find runs with `listPipelineRuns` (filter by `status`, `templateId`, `owner`; here `owner` defaults
  to `"mine"`, unlike templates). **Pipeline runs do not appear in `getJobs()`.**

## Cost and authorization

A run fans out into many jobs and can cost far more than a single submit. Confirm material scope with
the user before the first `submitPipeline`, and again before re-running with a materially larger
binding. Authorization for one run is not authorization for the next.

## Reading a failure

A failed step reports its status in `getPipelineRun`. For why, read that step's jobs with the job
tools (`getJobs`, `getJobLogs` with a bounded line count) — the pipeline tools report run and step
state, not tool logs. Checkpoint the failure rather than resubmitting.

If a run sits at `running` with every job complete and no progress, that is a delivery-side stall,
not something a resubmit fixes. Report it with the `runId` and the step's `node`.
