# From a tool's real output to the pool the scripts read

> Column names and output layouts change. This is a grounded snapshot, not an authority. Resolve every entry with `tamarind --json schema TOOL` before you build a pool, and prefer what the live schema says over what this table says.

`campaign_gates.py` and `select_panel.py` read **one row per design**, with fixed key names. No generation tool emits that shape. Building the bridge is a real step of this campaign, it is where designs are silently lost or mis-attributed, and it is yours to do.

## Read the output contract; do not guess it

`tamarind --json schema TOOL` carries an **`outputs`** block, and it answers the question that costs a method its floor:

- **`outputs.mainCSV`** — *which file is the actual result table.* Every other table the job wrote is an intermediate. It may be a glob (`designability/design*/mpnn_results.csv`) or a job-name template (`{JobName}.csv`), so resolve it against the job's **downloaded** bundle (`tamarind --json results JOB_NAME --download <dir>`) rather than expecting a literal name — `tamarind --json files` lists the inputs you uploaded, not a job's outputs.
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
| `rfdiffusion` | `seq` — slash-joined; **binder is the LAST field, not the first** (measured) | `design` **+** `n` (composite) |
| `rfdiffusion3` | `Sequence_A` | `design_id` |
| `freebindcraft` | `Sequence` (binder only) | `Design` |
| `boltzgen` | `designed_chain_sequence` | `id` |
| `genie3` | `binder_seq` | **`name`** — but see the row explosion below; `rank` is a MODEL rank, not an identifier |
| `mosaic-hallucinate` | `sequence` | `design_id` |
| `protein-hunter` | `best_seq` — **undetermined**, confirm on the canary | `run_id` |
| `proteina-complexa` | **none** — backbone-only | `Rank`, job-local |
| `boltzdesign` | **undetermined** — read its canary table before assuming either | `target` + `iteration` |
| `pxdesign` | **none** — backbone-only | — |
| *(`proteinmpnn`)* | `sequence` — **colon-joined, designed chain LAST** | `sequence_index` |

`sequence` is the live name on exactly one of these. Everything else needs renaming.

## Three ways this goes silently wrong

**1. Taking the wrong half of a joined sequence — and the schema text will not save you.**

**Do not trust a schema's stated chain order. Measure it.** RFdiffusion's own `seq` column description reads *"for binder design the format is binder/target"*. On a real PD-L1 binder-design run — four independent jobs, checked against the frozen construct byte for byte — **index 0 was the target and the binder was last**. The documented order is the reverse of the delivered order. This was found by running the campaign, not by reading the catalog, and it is the reason this section exists.

So the two tools you are most likely to pair actually **agree** — both put the binder last. What is inverted is RFdiffusion against its own documentation, and that is the trap: the agreement holds only if you take it from the measurement rather than from the schema text:

- **RFdiffusion** `seq`, slash-joined — binder measured **last**.
- **ProteinMPNN** `sequence`, colon-joined — "the designed chain is appended last", so binder **last**.

A target chain of ordinary composition and legal length gates cleanly as if it were a design. Every row then carries the same target sequence, and the numbers that come back are a scoring method's opinion of the target against itself.

**Identify the binder by what it is, not by its position.** You know the target chains — they are in your frozen plan — and you know the length you asked for. Assert both:

```python
chains = row["seq"].split("/")
# TARGET_CHAINS is a SET, one entry per chain of the frozen construct. A
# heteromeric target has more than one, and excluding only the first leaves
# the second looking like a design.
binder = [c for c in chains if c not in TARGET_CHAINS]
assert len(binder) == 1 and LEN_MIN <= len(binder[0]) <= LEN_MAX
```

The gates catch two weaker versions of this — the un-split string (`has non-residue characters '/'`) and a pool that collapses to one distinct sequence (`every design carries an identical sequence`) — but neither fires if you split, took the wrong half, and the pool still varies. Nor does `select_panel.py`'s `scored_sequence` check: it asks whether the row's sequence is **one of the chains** the scoring job folded, and the target is a chain of every scoring construct, so a row carrying the target passes it. That is deliberate — the script is never given the frozen target, and a script that guessed which chain was the design would be asserting something only the campaign knows. **The assertion above is what actually closes it, and it is yours to write.**

**2. A composite identifier collapses.** RFdiffusion's `design` repeats across the several MPNN sequences sampled for one backbone; using it alone trips the duplicate-id refusal. Join `design` and `n`. Getting this wrong in the other direction — minting a fresh id per row — breaks `root_backbone_id` and lets one backbone's family escape the per-root cap.

**3. One design can occupy several rows.** Measured: a `genie3` run for 2 designs returned **10 rows** — five AlphaFold models per design, differing only in `model_id` and `rank`. Taken at face value that is a fivefold phantom pool, and the duplicates carry the same sequence, so the identical-sequence guard will not catch it either (they are not *all* identical). Collapse to one row per design first: group by `name`, keep the best-ranked row, and check that the number of distinct sequences equals the number of designs you asked for. The same shape appears wherever a generator refolds each design with several models.

**4. A job-local identifier repeats across a batch.** `Rank` is unique within one job, and a fan-out launches many. Namespace every id with its job name before pooling.

## Backbone-only methods carry lineage across the hop

`proteina-complexa` and `pxdesign` emit no sequence, so they route through sequence design (`boltzdesign` and `protein-hunter` are **undetermined** in [roster.md](roster.md) — read the method's own per-design table on its canary and treat it as backbone-only only when that table genuinely has no sequence column, because the extra hop mints a second id space for nothing) — and that job indexes its own rows in a new id space. Carry the origin across explicitly: `root_backbone_id` and `structure_method` keep naming the **generator**; `seq_method` names the sequence designer. Losing this is how a method contributes zero ranked backbones while appearing to have run.

## `binder_chain` is not the same letter on every method

Measured on one campaign, same target, three generators:

| method | binder chain | target chain |
|---|---|---|
| `rfdiffusion` | **B** | A |
| `boltzgen` | **B** | A |
| `genie3` | **A** | B |

So the natural assumption — "the binder is chain B", which is what FreeBindCraft's own output documentation states — **gates the target instead of the design** on genie3. The plausibility gate then measures the target's geometry and the fold-class column describes the target's fold. The mimic screen does catch this specific case (target against target scores TM ≈ 1.0 and REJECTs), but only because the mimic gate happened to run; with no reference chains supplied it is NOT_RUN and nothing notices.

Read the chain off each structure rather than assuming: the binder is the chain whose length matches the design you asked for, and the target is the one that matches your frozen construct. Set `binder_chain` per row, per method.

## A generator can hand you a natural protein

`boltzgen` returned a 75-residue "de novo design" that is **93.3% identical to human ubiquitin** and matches its first 40 residues exactly. It passed the liability gate cleanly — composition, entropy, patches and cysteine parity are all unremarkable, because ubiquitin is a perfectly well-behaved protein.

Nothing in `campaign_gates.py` catches this. The self-similarity and known-binder limbs of novelty compare against the target and the control chains, and ubiquitin is neither. **Only the database limb — a sequence-identity search against the wider protein universe — sees it**, and that limb is a Tamarind job, which is exactly why this script emits `novelty_verdict = NOT_RUN` with a reason instead of a pass.

So treat that NOT_RUN as a live liability, not a formality: run the database novelty search on the survivors before the panel, and if you genuinely cannot, say in the report that the shipped designs were **not** checked against known proteins — because a campaign can otherwise ship ubiquitin as a de novo binder and every other gate will agree it looks fine.

## Which structure you hand the structural gates changes their verdict

`designed_structure_path` decides what the plausibility and mimic gates measure, and a generator usually writes several structures per design. Point it at the design's **final, relaxed** complex, name the binder chain explicitly in `binder_chain`, and record which file you used.

Measured across three methods, one design each, every structure taken straight from its generator's own output:

| method | structure used | plausibility | mimic |
|---|---|---|---|
| `rfdiffusion` | `designability/` output | **REJECT** — 5 of 69 peptide C–N bonds out of band (worst 1.2033 Å vs a 1.229 Å floor), 1 severe clash | PASS, TM 0.31 |
| `boltzgen` | refolded final design | **REJECT** | PASS, TM 0.34 |
| `genie3` | `unrelaxed_` AF2-multimer model | **PASS** | PASS, TM 0.34 |

So this is not simply "unrelaxed rejects" — an explicitly unrelaxed AF2-multimer structure passed while a refolded one did not. The gate discriminates on the actual geometry, and which file a generator hands you varies more than its label suggests.

So when plausibility rejects everything, **investigate the input before the threshold.** The thresholds are vendored frozen values and retuning them to admit your pool is the defect this campaign exists to prevent; the honest fixes are to relax the structures first, or to feed the gate the co-folded complex rather than the raw generator output, or to disclose the gate as NOT_RUN. The skill's "a gate that passes everything, fails everything, or returns a constant is broken until investigated" rule fires here exactly as intended — and on a two-design pool it fires on sample size alone, so read it as a prompt, not a verdict.

## Clustering is a stage you run

`select_panel.py` refuses a row with no `tm_cluster`, and no bundled script writes one. Cluster the surviving pool at ~90% identity and join the cluster id on before selection. The vendored kernel has the single-linkage TM clusterer; nothing calls it for you.
