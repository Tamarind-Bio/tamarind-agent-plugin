# What the campaign ships

> The protocol's deliverables, minus the ones that were Anthropic's harness rather than their science. Slack cadences, the Drive folder and the sub-agent swarm have no analogue here; the artifacts below do.

## 1. The design sheet

One CSV, **at most the panel size** (default 30) ranked rows, and only those, with
explicit rank and full metadata. `select_panel.py` writes it. The panel size is a
ceiling, not a quota — see **Row count** below, and never describe a sheet as holding
exactly N until you have counted its rows.

**Never null**, on every row: identity, provenance, rank, `rank_zscore`,
`final_score`, the instrument that produced them, `pose_PASS` and `pose_dockq`. A row
that cannot fill these is not a ranked row.

**What the writer actually reproduces, and what it only carries.** This distinction
is the sheet's whole evidentiary value, so state it precisely rather than describing
the sheet as verified.

| column | at write time |
|---|---|
| liability | **recomputed** from the row's own sequence |
| structural plausibility | **recomputed**, when the row names a structure and its binder chain |
| monomer foldability | **recomputed** from `monomer_plddt` against the frozen floor |
| `pose_dockq`, `sc_DockQ_*` | **carried** — the minimum over the cells the row already holds |
| `final_score`, `rank_zscore` | **carried** |
| novelty verdict and tier | **carried**; the tier is *enforced* instead |
| `designed_structure_path` | **not enforced** — used when present |

A recomputed column is matched against the carried value to within 1e-4 and a
mismatch halts the writer with the row id; that is what makes those three a claim
rather than a copy of one. The carried columns are not independently checked, so a
row holding a stale or misjoined `sc_DockQ_*` cell can rank on a pose measurement
belonging to another structure — reconcile scoring rows by sequence when you build
them, because the sheet writer will not catch it for you.

**Novelty is carried for a measured reason.** Reproducing it needs the staged corpus
and every reference chain inside the writer, and the in-process aligner is
O(pool x corpus) — ~0.5 ms per alignment, so the protocol's own corpus against a
protocol-scale pool is tens of hours. The writer lists novelty under its skipped
recomputes at run time and enforces the tier instead: a `NOT_RUN` verdict, or a `PASS`
earned only at the dispatch tier, does not rank.

**Row count.** If the gates leave fewer than the panel size rank-eligible after
upstream regeneration, ship the real N and say so. Padding with duplicates, or
relaxing a gate to reach the number, is sheet corruption.

## 2. Companions, written alongside it

- **per-seed metrics** — one row per design × scoring arm × seed with the raw
  values, so any sheet score can be reproduced without re-computing it. This is what
  makes the z-scores re-derivable: they are transductive, so a reader who wants to
  re-standardize needs the raw vector and the seed count.
- **instrument realization** — one row per (target, ranking arm) recording gate
  status, seeds run, how many ranked rows carry that arm's score, whether it was
  used in `final_score`, the control separation, **the cofactors present and the
  number of target chains folded**, beside the dossier's native oligomer count. An
  all-cofactor-blind or all-monomer ranking on a target whose dossier flags a
  cofactor is a **logged deviation**, recorded here.
- **the rejects ledger** — every rejected design_id with the gate and the numbers
  that rejected it.
- **the run manifest** — every design_id to its parent backbone, its sequence-design
  model, and the job that produced each artifact.

## 3. Scoreboard

One machine-readable row per target: designs generated, screened and ranked; best
and median `final_score`; and the counts behind every claim. Every number in it
comes from a fresh aggregate over the stored rows at write time, not from a running
tally kept in conversation.

## 4. Report

A publication-ready write-up in the style of a protein-design paper, with figures
and citations. Its headline states the **worst defensible reading** of the data.

It must name, in the user's own words:

- every method dropped and the diversity objective it cost, including any the
  live catalog turned out not to carry. Name the objective, not just the tool:
  FoldCraft, for instance, is the one the protocol names for beta-containing
  folds, so its absence is a fold-diversity gap specifically;
- every gate that did not run and what it no longer catches;
- every instrument term missing and why, and under a reduced mask, which terms the
  score actually ran over;
- the stoichiometry beside every number on a multimeric target, and any design whose
  N:N score collapsed relative to its 1:N;
- the fold-diversity count actually shipped against the 10% target, **and which
  secondary-structure method resolved it** — the target is defined under DSSP and
  the fallback is P-SEA;
- which optimization round you stopped at and what the last round bought. A round
  that improved nothing is a result, and reporting it is what makes the rounds that
  did improve credible;
- every substitution made for a check the protocol specifies.

## 5. Supplement

Everything not suited to the report: design configurations and contigs; for every
ranked design the designed complex **and** every predicted complex used for scoring
and pose verification; every intermediate from every optimization round; logs and
failure records.

**Nothing computed is discarded.** If it was computed, it is saved, with the exact
configuration that produced it — model and version, the settings submitted, the
seeds, and the job that produced each artifact.

**Retrievability is checked, not assumed.** Before completion, for every ranked row,
**open** every file its path columns reference — not merely resolve the path. A path
that resolves to a file nobody can open is a broken deliverable that looks complete.
