---
name: tamarind-mcp-pipeline
description: Author, validate, run, monitor, and read results from declarative multi-step Tamarind Bio pipelines through MCP with submitPipeline, validatePipeline, getPipelineSchema, getPipelineTemplate, listPipelineTemplates, getPipelineRun, getPipelineRunResults, listPipelineRuns, and stopPipelineRun. Use when stages depend on earlier stages (design to fold to score), or to run or re-run a saved pipeline template. Not for a single job, one independent batch, or CLI orchestration.
---

# Run Tamarind pipelines through MCP

A pipeline is a declarative graph the server runs for you: it dispatches each step's jobs, waits
for their molecules to land, and feeds them to the next step. You do not chain jobs by hand.

**If you have previously been told the MCP surface has no pipeline submission tool, that is stale.**
There are nine pipeline tools. Do not rebuild orchestration out of `submitJob`/`submitBatch` polling.

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

## Choose a path first

**Path A — run an existing template.** Cheaper, safer, and usually what the user wants. Always look
before authoring: `listPipelineTemplates(search=...)`. Its `owner` defaults to `"org"`, so you see
your whole organization's templates, including ones you did not create. Narrow with `owner="mine"`.

**Listed does not mean runnable.** The org listing includes templates you cannot use: an unpublished
one belonging to someone else lists fine and then fails validation with `403
pipeline_permission_denied`. Treat that as terminal (see `validationUnavailable` below) — pick
another template or ask the owner to publish it. `isPublished` on the listing row is the signal to
read: prefer a published template, or one where `createdBy` is you.

**Path B — author a graph inline.** Only when nothing suitable exists. Passing `pipeline` to
`submitPipeline` saves a new template you own (unpublished) and runs it in one call.

## Path A — run a saved template

1. `listPipelineTemplates(search=...)` → pick an `id`. Rows are summaries; they carry no graph.
2. `getPipelineTemplate(templateId)` → read **`inputs`**. This is the manifest of what you must
   bind: the input node id to key each binding by, whether it takes molecules or a file, the
   molecule type expected, its reference chain labels, and any `residueFields`.
3. `validatePipeline(name, templateId, version, bindings, settings)` until `valid: true`.
4. `submitPipeline(name, templateId, ..., bindings)`.

`settings` and `version` are **reference-mode only**. `settings` is `{nodeId: {settingKey: value}}`
and is limited to the template's editable settings. Omit `version` to get the published version,
else the latest.

## Path B — author a graph inline

Call `getPipelineSchema()` first, every time. It returns the live JSON Schema plus a prose guide
fetched from the app host, so it always matches the deployed validator. Authoring blind reliably
produces graphs the API rejects.

Rules from that guide worth knowing before you read it, because they are not guessable:

- There is **no edge list**. Topology lives inside each node's `inputs` — a node names the nodes it
  consumes. Do not look for a `edges` array; you will not find one.
- Every molecule `user_input` node needs a reference group.
- A `filter` node must either set `intersect: true` or carry at least one rule. An empty filter is
  invalid, not a pass-through.
- Residue selections are supplied **per run, in the binding** (`residuesByChain`) — never as a node
  setting.

## Bindings — where most mistakes happen

One entry per input node, keyed by that input node's id.

Supply molecules **exactly one way**:

```jsonc
{"inputProtein": {"group": "<groupId>"}}          // an existing molecule group
{"inputProtein": {"sequences": ["MKT..."]}}       // or raw values — server creates the group
{"inputLigand":  {"smiles": ["CCO"]}}
{"inputTarget":  {"pdbs": ["..."]}}
{"inputLigand":  {"sdfs": ["..."]}}
{"inputCsv":     {"file": "<path>"}}              // a file input
```

When you pass raw values the server creates the group for you — and rolls it back if the submit
fails, so a failed submit does not leave an orphan group.

Two optional keys inside a binding:

- `residuesByChain`: `{"A": "1-76"}` — a residue selection, where the tool needs one.
- `chainMapping` — **only** when your chain IDs differ from the template's reference chains. Do not
  add it reflexively.

### The residue trap — read this before inventing a selection

A non-empty `residueFields` means the run **may** take a `residuesByChain` — **not** that one is
required. Measured: rfdiffusion, bindcraft and antibody-boltzgen templates whose manifests declare
`residueFields` have completed with no `residuesByChain` at all, and the entries carry no per-field
`required` flag to tell the two cases apart. A live entry is exactly this and nothing more:

```jsonc
{"node": "backbone", "field": "hotspots", "multichain": true, "targetsChains": []}
```

This matters because inventing a selection is **not** a harmless default. It reaches the tool as
designed residues, binder hotspots, or a binding site — constraining the design to the wrong
residues and spending GPU on scientifically wrong output **that still looks successful**.

So: do not guess, and do not refuse a runnable template either. Call `validatePipeline` with the
bindings you actually have. If a selection is genuinely required it comes back as
`required-field-unset` naming the field. Ask the user for the real selection then.

Related trap: `targetsChains` is empty on some entries, and on others names a chain **outside** the
input's own `chains` (a de-novo chain the graph creates). It is not reliably a key for
`residuesByChain`.

## Validate before every submit

`submitPipeline` spends real compute. `validatePipeline` executes and saves nothing, and catches
most authoring mistakes. Call it on the same graph and bindings, and only submit on `valid: true`.

It reads the arguments that *describe* the run — `pipeline` or `templateId`+`version`, `bindings`,
`settings`, `name`. It does not read `runName`, `project` or `idempotencyKey`, which only name and
tag the run, so passing them changes nothing.

Both outcomes return HTTP 200 — **read `valid`, do not branch on the status code.** Each error
carries a stable `code`, a `severity`, the `node` it belongs to, the `field` at fault where there is
one, and a `message` saying how to fix it:

| code | usual cause |
|---|---|
| `required-field-unset` | often a residue selection — it belongs in the **binding**, not in settings |
| `input-unbound` | an input node with no entry in `bindings` |
| `tool-unknown` | the node names a tool that does not exist |
| `setting-invalid` / `param-out-of-range` | a bad node setting |
| `chain-incompatible` | chain labels do not line up |
| `molecule-class-incompatible` | the upstream tool does not produce what the downstream tool consumes |

Two failure modes to handle deliberately:

- **`validationUnavailable`** means your pipeline was **not judged** — there is no verdict, so do
  **not** start editing the graph in response to one. **Read `status`/`code` before retrying:** the
  flag is set on a permanent `403 pipeline_permission_denied` ("this pipeline hasn't been shared with
  you") as well as on a genuinely unreachable validator, and the accompanying hint says to retry in
  both cases. A 403 is terminal — measured byte-identical on retry. Report it and ask the owner to
  publish or grant access. Retry only a non-403; if that fails identically every time, report it
  rather than looping.
- **`valid: true` is not a guarantee that `submitPipeline` will accept the run.** Measured gaps: it
  does not confirm the tools exist, and it does not check that a bound molecule group exists or has
  anything in it. So if `submitPipeline` rejects a graph validation approved, **believe
  `submitPipeline`** — re-validating will not reproduce the error. Fix what the submit names, which
  is usually a tool name or a group id, not the graph's shape.

## Submit, then poll

`submitPipeline` returns a `PublicRun`; its `id` is the `runId`. Pass `idempotencyKey` so a retried
submit is safe, and `runName` for an explicit name for this run (omit it to derive a unique one from
`name`). `project` stamps an organization project id on the jobs the run creates.

Poll `getPipelineRun(runId)` on a **finite deadline** — never an unbounded loop. Each step reports
its own `status`, `jobsTotal`/`jobsComplete`, `outputCount`, and `outputGroup`.

If a submit response is ambiguous, find the run with `listPipelineRuns` before retrying. Never call
`submitPipeline` a second time to resolve uncertainty about the first.

## Read results

`getPipelineRunResults(runId)` returns each step's molecules **with their scores** — which is what
you rank and compare on. Results appear per step as it finishes, so this is useful before the whole
run completes; a step that has produced nothing yet reports an empty `molecules` list.

**Scores live in different places depending on which shape you get. Read whichever you receive:**

- group molecules — id in `id`, scores under `metadata`
- the step's own outputs — id in `complexId`, scores at top level in `scores`

These are passed through as the API returns them rather than reshaped, so the fields match each
resource's own docs. A step with an `outputGroup` is normally read from the group but **falls back**
to its own outputs when the group returns nothing — so do not infer the shape from whether
`outputGroup` is set.

**`outputGroup: null` does not mean "nothing here."** It is the group a step *minted*. A step that
enriches its inputs in place — scoring, structure prediction — leaves its molecules in the group
they arrived in. A filter step's survivors exist only as step outputs. Both report a null group and
are read from the step itself.

Paging: `limit` is 1-100 (default 25). Keep it small — molecules carry their sequences, files and
full score history. To page one step, call again with `node` set to that step and `cursor` set to
its `nextCursor`; a cursor belongs to one step's group, so `cursor` requires `node`.

## Stopping, and finding runs later

- Stop with `stopPipelineRun(runId)`. Steps that already finished keep their outputs; work still in
  flight is cancelled. **Do not use `cancelBatch`** — it only understands the older pipeline job
  layout and will not stop one of these runs.
- Find runs with `listPipelineRuns` (filter by `status`, `templateId`, `owner`; `owner` defaults to
  `"mine"` here, unlike templates). **Pipeline runs do not appear in `getJobs()`**, which covers
  single jobs and batches only.

## Cost and authorization

A pipeline run fans out into many jobs and can be far more expensive than a single submit. Confirm
material scope with the user before the first `submitPipeline`, and again before re-running with a
materially larger binding. Authorization for one run is not authorization for the next.

## Reading a failure

A step that fails reports its status in `getPipelineRun`. To see why, look at the step's jobs with
the job tools (`getJobs`, `getJobLogs` with a bounded line count) — the pipeline tools report run
and step state, not tool logs. Checkpoint the failure and stop rather than resubmitting the run.

If a run sits at `running` with every job complete and no progress, that is a delivery-side stall,
not something a resubmit fixes. Report it with the `runId` and the step's `node`.
