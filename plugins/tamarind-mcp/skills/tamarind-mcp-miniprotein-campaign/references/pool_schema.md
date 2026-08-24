# From a tool's real output to the pool the scripts read

> Column names and output layouts change. This is a grounded snapshot, not an authority. Resolve every entry with `getJobSchema` before you build a pool, and prefer what the live schema says over what this table says.

`campaign_gates.py` and `select_panel.py` read **one row per design**, with fixed key names. No generation tool emits that shape. Building the bridge is a real step of this campaign, it is where designs are silently lost or mis-attributed, and it is yours to do.

## Read the output contract; do not guess it

`getJobSchema(<type>)` carries an **`outputs`** block, and it answers the question that costs a method its floor:

- **`outputs.mainCSV`** — *which file is the actual result table.* Every other table the job wrote is an intermediate. It may be a glob (`designability/design*/mpnn_results.csv`) or a job-name template (`{JobName}.csv`), so resolve it against `listJobFiles` rather than expecting a literal name.
- **`outputs.columns`** — each column's name, type, description and units.
- **`outputs.taskType`** — `generate` vs `score`. A scoring tool's table can *echo* an input sequence, so a `produces: ["sequence"]` claim is not proof the tool created one.
- **`outputs.byTask`** — the per-task contract where a tool has one. **Authoritative for the task you set**, over the scalar fields. Most tools do not carry it; some express per-task variation as a `tasks` list on individual columns instead. Read the columns as well as the block.

Call this **before** you conclude a method produced nothing. "This method produced nothing" is a diagnosis only after you have opened the file `mainCSV` names.

## What the scripts require

`campaign_gates.py` — refuses the whole pool otherwise:

| key | notes |
|---|---|
| `design_id` (or `id`) | unique across the pool |
| `sequence` | binder only; residue letters only; 35–160 aa |
| `designed_structure_path`, `binder_chain` | optional; without them the structural gates report NOT_RUN |

`select_panel.py` additionally requires the lineage and gate columns in [selection.md](selection.md): `root_backbone_id`, `structure_method`, `seq_method`, `opt_round`, `tm_cluster`, `n_seeds`, the five `*_verdict` columns, and the `ipsae_<arm>` / `sc_DockQ_<arm>` score terms.

## The mapping, per generation method

| method | sequence column | design identifier |
|---|---|---|
| `rfdiffusion` | `seq` — **slash-joined `binder/target`** | `design` **+** `n` (composite) |
| `rfdiffusion3` | `Sequence_A` | `design_id` |
| `freebindcraft` | `Sequence` (binder only) | `Design` |
| `boltzgen` | `designed_chain_sequence` | `id` |
| `genie3` | `binder_seq` | **none** — `rank` is not an identifier |
| `mosaic-hallucinate` | `sequence` | `design_id` |
| `protein-hunter` | `best_seq` | `run_id` |
| `proteina-complexa` | **none** — backbone-only | `Rank`, job-local |
| `boltzdesign` | **none** — backbone-only | `target` + `iteration` |
| `pxdesign` | **none** — backbone-only | — |
| *(`proteinmpnn`)* | `sequence` — **colon-joined, designed chain LAST** | `sequence_index` |

`sequence` is the live name on exactly one of these. Everything else needs renaming.

## Three ways this goes silently wrong

**1. The chain-split convention is inverted between the two tools you are most likely to pair.** RFdiffusion writes `binder/target` — binder at index **0**. ProteinMPNN writes colon-joined with **the designed chain last** — binder at index **−1**. A split helper written for one hands you the *target* chain for the other, and a target chain of ordinary composition and legal length gates cleanly as if it were a binder. Nothing downstream can detect it. **Split by the separator the schema documents for that tool, and assert the length you get back is the length you designed.**

The gates do catch the un-split string — `refusing the pool: design 'design0' has non-residue characters '/' in its sequence` — but that only saves you if you forgot to split, not if you split and took the wrong half.

**2. A composite identifier collapses.** RFdiffusion's `design` repeats across the several MPNN sequences sampled for one backbone; using it alone trips the duplicate-id refusal. Join `design` and `n`. Getting this wrong in the other direction — minting a fresh id per row — breaks `root_backbone_id` and lets one backbone's family escape the per-root cap.

**3. A job-local identifier repeats across a batch.** `Rank` is unique within one job, and a fan-out launches many. Namespace every id with its job name before pooling.

## Backbone-only methods carry lineage across the hop

`proteina-complexa`, `pxdesign` and `boltzdesign` emit no sequence, so they route through sequence design — and that job indexes its own rows in a new id space. Carry the origin across explicitly: `root_backbone_id` and `structure_method` keep naming the **generator**; `seq_method` names the sequence designer. Losing this is how a method contributes zero ranked backbones while appearing to have run.

## Clustering is a stage you run

`select_panel.py` refuses a row with no `tm_cluster`, and no bundled script writes one. Cluster the surviving pool at ~90% identity and join the cluster id on before selection. The vendored kernel has the single-linkage TM clusterer; nothing calls it for you.
