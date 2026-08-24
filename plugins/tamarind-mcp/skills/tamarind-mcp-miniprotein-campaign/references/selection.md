# Provenance, selection caps, ranking, and deliverables

## Provenance keys

Every generation arm assigns `root_backbone_id` (one id per de novo backbone, shared by every derived sequence) and `structure_method` at backbone-generation time, and propagates both **unchanged** through every downstream stage. `structure_method` and `seq_method` are tokens from the plan's frozen method vocabulary, never free text.

Optimization lineage rides on three columns and is not bookkeeping:

- every child keeps its parent's `root_backbone_id`;
- `parent_design_id` names the design it came from;
- `opt_round` numbers the round, 0 for de novo.

**Minting a fresh root for a child escapes the per-root cap while looking like ordinary provenance**, and ships a panel that is five rounds of one backbone wearing five names. Nothing downstream can reconstruct a root you did not keep, and the cap it protects is counted before anything looks. A round-0 design must not claim a parent; a design must not be its own parent; a round must be above its parent's. A parent that is simply absent from the shipped panel is not an offence — the panel is small, the round is large, and the caps allow only a couple of rows per root.

## Selection caps, applied in selection order

These are ceilings, not quotas:

1. reject exact-sequence duplicates;
2. reject pairs within **edit distance 5**;
3. cap any single `root_backbone_id` at **5%** of rows, rounded up;
4. cap any single **structural-similarity 0.90 single-linkage cluster** at **10%**, rounded up;
5. cap any single `structure_method` at **50%** and require **at least 3 distinct structure methods**;
6. cap any single `seq_method` at **two-thirds**, backfilling from the next-best alternate.

If the ranked pool cannot fill the panel under these caps, **fix it upstream first** — more designs, more methods.

## Relaxation ladder

One step at a time, recording on every affected row which step admitted it:

1. **diversity caps** — never past per-root 25%, per-method 50%, or fewer than 3 distinct structure methods;
2. **liability flags.**

Relaxation is applied by changing a threshold, **never** by deleting, no-oping or bypassing a gate, and never as the first response to an under-diverse pool or to low scores.

The pose term is never relaxed per row. If the limb genuinely could not run, it carries NOT_RUN with its reason on **every** row — a disclosed instrument reduction declared up front. What is never allowed is the mixture: NOT_RUN written on some rows to get past the threshold on others. The final score being non-null is never relaxed. Novelty is relaxed only after regeneration **and** the full ladder have failed, and even then the absolute floors hold: no two shipped rows identical, and the target-mimic and natural-sequence-copy bans are never relaxed. **A row carrying no mimic verdict at all is refused the same way — absence is not a pass.**

If even the last resort cannot reach the panel size, **ship the actual N. Padding with duplicates is forbidden.**

## What the panel selector refuses

`select_panel.py` will not rank a row it cannot audit, so a candidate file has
to carry these or the row goes to the unranked section with its reason:

| Field | Rule |
|---|---|
| `sequence` | drawn entirely from the residue alphabet — a path or status word is refused, never salvaged |
| `liability_verdict`, `novelty_verdict`, `structural_plausibility_verdict`, `monomer_foldability_verdict`, `target_mimic_verdict` | present and one of PASS / REJECT / NOT_RUN. **Absent is not a pass**, and REJECT is refused |
| `n_seeds` | a non-negative whole number. Absent reads as a deliberately shallow tier rather than a lost join |
| `opt_round`, `parent_design_id`, `root_backbone_id` | lineage that closes — round 0 claims no parent, a later round names one, nothing is its own parent |
| per-arm `ipsae_*` / `sc_DockQ_*` | numeric. A boolean is refused: `float(True)` is a fabricated perfect score |
| `target` | one target across the whole file, or none at all. The rank score is per-target and transductive, so two targets pooled changes every z-score |

Two whole-run refusals, distinct from per-row ones: it will not emit a panel
whose distinct `structure_method` count is below the floor — that floor is
absolute and no rung of the ladder goes under it — and it will not report
success on an empty panel, because exiting cleanly without writing the sheet
leaves whatever runs next to fail on a missing file.

A short panel that clears the floor **does** ship. "Ship the actual N" is the
instruction; padding with duplicates is what is forbidden.

## Rank key

Order by: **full seed tier on all arms** descending, then **pose pass** descending, then **rank score** descending.

If the pose limb did not run, that term is constant and the key degenerates to seed tier then rank score. Sort it as a constant — never coerce NOT_RUN to true or false — and say in the report that the ordering carries no pose evidence.

Rows below the full seed count after a failed top-up are still **ranked**, with their true seed count disclosed per arm; they are not dropped for seed count alone. Dispatch one targeted seed top-up wave before freezing the sheet. The unranked section is reserved for rows with missing or zero scores only.

**A value that was not run is a labeled value in its own column** — never 0.0, never -1, never -999, never an empty string, and never mixed into the final score.

## Sheet columns, at minimum

`design_id`, `target`, `sequence`, `binder_len`, `rank`, `rank_zscore`, `final_score`, `score_instrument`, pose pass and pose value, `structure_method`, `seq_method`, `epitope_directed`, `opt_round`, `root_backbone_id`, `parent_design_id`, `n_seeds`, `novelty_verdict`, `novelty_verdict_path`, cluster id, `fold_class`, `designed_structure_path`, `binder_chain`, `structural_plausibility_verdict`, one predicted-structure path per arm, and one column per scoring and shadow metric actually computed.

**A gate column carries the gate's own number, not a restatement of it.** A verdict with no numbers beside it is unfalsifiable, and a path is not a verdict. Each verdict holds one of PASS / REJECT / NOT_RUN — a word, never a bare true/false and never blank for "passed" — and the scalar terms that decided it sit beside it at full precision. A gate that did not run for a row leaves its evidence cells **empty** and its verdict NOT_RUN: an absent input makes the row not-recomputable, which is disclosed, while an invented one makes it a silent pass.

`binder_chain` is the chain id **within** the designed structure that is the design. A plausibility check given no chain cannot be re-run at all, so an unnamed chain is a check nobody can reproduce.

**The monomer foldability trap.** Read the confidence off a **binder-alone** fold, taken as the max over that job's seed and sample rows on the scale that model emits, and carry the producing job name. Reading it off a **complex** fold is the trap: there it is the confidence of binder and target together, dominated by a target that folds perfectly alone — so it does not fail the floor, it clears it on every row and passes the whole pool on exactly the artifact the gate exists to detect.

## Recompute before shipping

- **Recompute every gate that ran** — novelty, liability, monomer foldability, plausibility, and the final score under the realized mask — from the row's own sequence and predicted structure, and admit the row only when the recomputed value matches the carried value to within 1e-4. A mismatch halts the sheet, naming the row. Do not ship a row whose gates you could not reproduce. A NOT_RUN term is checked for its label and reason, never recomputed into a number.
- **Companion coverage is 100%** of ranked design ids by exact match. No design-and-arm group is uniformly null on the ranking metric. Recompute the final score for a random sample of rows **from the per-seed companion alone** and confirm agreement to 1e-4, or regenerate the companion.
- **Re-check diversity on the final selected set**: no exact duplicates, no pair within edit distance 5, no root above its cap, no cluster above its cap, at least 3 structure methods represented, and no ranked row with an empty or zero score.

## Deliverables

Files the user can open, not a tarball — structures render in a viewer, an archive previews as nothing.

- `design_sheet.csv` — exactly the ranked rows, with explicit rank and full metadata;
- `per_seed_metrics.csv` — one row per design, arm and seed, with raw values and the per-seed structure path;
- `instrument_realization.csv` — one row per arm: status, seeds run, rows scored, whether it fed the final score, control separation, and a reason on any arm that did not run. Every number **derived** from the companion and the validation verdict, never hand-authored;
- `scoreboard.csv`;
- `deviations.jsonl` — one JSON object per line, deduplicated;
- `report.md` plus figures and a flat manifest of per-file links.

**Store everything.** The exact configuration that produced each job, every structure emitted, every metric at the level it was computed, and the manifest mapping every design id to its parent backbone, its sequence-design model and its producing job.

## Multimeric targets

The default complex construct scores one binder against the whole target, so **a number reported without naming its stoichiometry is that one.** It says nothing about whether N binders can occupy N sites at once. On a homo-oligomeric target, run the full-occupancy construct for the shortlist as well, name the stoichiometry beside every number, and never present a single-binder panel as a complete characterization. A zero clash count is a real result and a blank one is not — a design whose copies were never built has no clashes either, and the two must never be reported the same way.

## Counter-screening

Not mandated and not forbidden. Counter-screen when the biology calls for it — a close paralog the binder must not engage — and say which off-target you chose and why. Do not counter-screen by default: it doubles the scoring spend on every design it covers, and against a target with no meaningful paralog it buys nothing. Choosing not to run one is a legitimate scientific call, so say so plainly rather than disclosing it as a missing capability.
