# Tamarind Bio tool catalog: how to read it

Tamarind exposes hundreds of tools through one job API. The catalog changes frequently, so **always enumerate at runtime**; this file is a map for interpreting what discovery returns, not a frozen list.

## How to discover

**MCP (preferred when present).** `getAvailableTools(modality=..., function=..., search=...)` filters server-side and returns entries with `categories` and `tags`, plus `availableCategories` / `availableTags` facet arrays computed from the live catalog. `category` / `tag` are deprecated aliases of `modality` / `function`, still honored.

```
getAvailableTools(function="structure-prediction")          # all folders
getAvailableTools(modality="antibody", function="developability")   # narrow on both
getAvailableTools(search="mpnn")                            # free-text
```

**REST (universal floor).** `GET /tools` returns the **full list** (no server-side filtering, so filter client-side). Each entry: `name` (the `type` you submit), `displayName`, `description`, `github`, `paper`, and `settings` (the inline parameter schema). REST entries do **not** carry `categories` / `tags`.

```python
tools = requests.get(f"{BASE}/tools", headers=HEADERS).json()   # a list
docking = [t for t in tools if "vina" in t["name"].lower()]
```

## The two filter axes

Don't hardcode the filter vocabulary; it drifts as tools are added. Fetch it live:

- `listModalities()`: molecule types. Each entry has `value`, `label`, `description`, `toolCount`. Live values include `protein`, `antibody`, `small-molecule`, `enzyme`, `peptide`, `small-molecule-binding-protein`, `nucleic-acid`, `cryoem`.
- `listTags()`: functions. Same shape. Live values include `structure-prediction`, `protein-design`, `binder-design`, `antibody-design`, `inverse-folding`, `protein-ligand-docking`, `protein-protein-docking`, `binding-affinity`, `affinity-optimization`, `developability`, `thermostability`, `solubility`, `molecular-dynamics`, `point-mutations`, `mutation-scoring`, `embeddings`, `finetuning`, `enzyme-design`, `generate-small-mols`, `small-molecule-property-prediction`, `motif-scaffolding`, `rna-design`, `codon-optimization`, `humanization`, `immunogenicity`, `structure-search`, `utilities`.

A tool can carry multiple modalities AND functions (e.g. `boltz` spans structure-prediction + docking + binding-affinity and several modalities), so it surfaces in more than one filter. Cross-listed generalists are a feature, not noise: see the standard-over-literal-match principle in [selection_principles.md](selection_principles.md).

## Reading a tool schema (getJobSchema)

`getJobSchema(jobType)` (MCP) returns the authoritative per-tool detail. Each entry in `parameters` may have:

- `name`, `type` (`sequence`, `number`, `boolean`, `dropdown`, `task`, file types like `pdb` / `cif` / `sdf` / `a3m`, …)
- `descr` / `displayName`
- `required`, `default`
- `options` / `optionsDescr` (for dropdowns), `lowerBound` / `upperBound` / `lengthLimit`
- `conditionals`: the field applies only when another field has a given value (e.g. a docking ligand file applies only when `ligandFormat="sdf"`)
- `exclude` (`["api"]` / `["batch"]` / `["pipelines"]`): the field is for a different surface; treat as advisory and let `validateJob` be the authority on what a submission accepts
- `list: true`: accepts multiple values / files
- `example`: a sample value

The top-level response also carries `categories`, `tags`, a `hint`, and an `exampleJob` built from each parameter's example/default. Start from `exampleJob`, then adapt and `validateJob` it rather than hand-building `settings` from scratch.

Over plain REST, the `/tools` entry's `settings` is a **trimmed** view: only `name` and `required` are guaranteed (`type` / `default` / `description` / `options` appear when relevant, ~60% carry `type`), and the gating keys `conditionals` / `exclude` are **not present**. Read REST params with `param.get("type")`, not `param["type"]`. For the full schema with gating keys, use MCP `getJobSchema`.

## Required-field reality (don't assume one input is enough)

Read the schema before claiming a tool takes a given input. Verified examples (re-check live, these drift):

- `boltz`: requires `inputFormat` (a task selector: `sequence` / `list` / `molecules` / `yaml`) AND the matching input (`sequence` for the `sequence` task; join multimer chains with `:`). Affinity, ligands, DNA/RNA, and templates are conditional extras.
- `alphafold`: requires `sequence` (join multimer chains with `:`). Single-sequence mode is `useMSA: false`; custom templates need `templateMode: "custom"`.
- `proteinmpnn`: requires a `pdbFile` (a structure) AND `designedResidues` (which positions to design). `modelType` selects the variant (`proteinmpnn` / `ligandmpnn` / `solublempnn` / `hypermpnn` / `abmpnn`), so one tool covers general, ligand-aware, soluble, thermostable, and antibody inverse folding.
- `autodock-vina`: requires a `receptorFile`, a ligand (`ligandFile` SDF or `ligandSmiles`, selected by `ligandFormat`), AND a bounding box (`boxX/Y/Z`, `width/height/depth`). It can't infer the pocket.

A tool with a `task` / selector parameter gates which sibling fields apply, so set the selector first; fields for the other modes are ignored.

## Gated tools: filter them from any recommendation

Some catalog tools are restricted and an external user **cannot run them**, so never recommend one:

- **Org-restricted tools** are allowlisted to specific organizations and are invisible to accounts outside the allowlist. `getAvailableTools` is account-scoped, so for these it already reflects access; recommend from what discovery returns for THIS account, not a remembered global list.
- **Feature-flagged (pre-release) tools** are hidden from normal external users by default but `getAvailableTools` does **NOT** honor that flag: such a tool can appear in the MCP listing for an internal or privileged key while being unavailable on the website to a normal external user. So a tool surfacing in discovery is necessary but not sufficient. If a candidate looks like an unreleased or flagged variant of a shipped tool (e.g. a pre-release twin of an already-live tool), prefer the stable, ungated public equivalent. When in doubt, recommend the shipped public tool; if the user names a gated one, tell them it's restricted and route them to their account admin rather than suggesting a workaround.

## Representative anchor families (verify with discovery)

Common starting handles, not an exhaustive or guaranteed list; confirm names and availability live.

- **Structure prediction / folding**: `boltz`, `alphafold`, `chai`, `esmfold` / `esmfold2`, `protenix`, `openfold`; antibody-specific folders (`immunebuilder`, `abodybuilder`), cyclic peptides (`highfold`).
- **Binder / protein design**: `bindcraft`, `rfdiffusion`, `boltzgen` (de novo binders, spans modalities); motif scaffolding via `rfdiffusion` variants.
- **Inverse folding / sequence design**: `proteinmpnn` (+ its `modelType` variants), `ligandmpnn`, `esm-if1`.
- **Antibody / nanobody**: `rfantibody`, `igdesign`, `proteinmpnn` (abmpnn model), plus numbering (`anarci`, `igblast`) and humanization tools.
- **Docking / affinity**: `autodock-vina` (known pocket, library screen), `diffdock` (blind), `boltz` / `chai` (co-fold the ligand into the complex), plus interface scorers.
- **Developability**: `tap` (antibody), `thermompnn` (stabilizing mutations), `netsolp` (solubility), `aggrescan3d` (aggregation).
- **Everything else** (enzyme, small-molecule / ADMET / QM, molecular dynamics, nucleic-acid, cryo-EM, search + utilities): discover via `listTags()` and see `tamarind-more-tools`.

Always read the schema before constructing `settings`, and run `validateJob` to confirm before submitting (via `tamarind-submit-and-poll`).
