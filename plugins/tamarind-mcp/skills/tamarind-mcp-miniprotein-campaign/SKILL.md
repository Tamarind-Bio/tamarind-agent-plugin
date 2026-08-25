---
name: tamarind-mcp-miniprotein-campaign
description: Run Anthropic's published de novo miniprotein binder campaign protocol through Tamarind MCP against one target and epitope — multi-method generation under a per-method floor, four pre-scoring gates, a three-arm co-folding instrument frozen and control-validated before any production scoring, five or more optimization rounds, and a ranked, diversity-capped 30-design panel with per-design provenance. Use for a reproducible panel or a like-for-like comparison across generation methods. Not for a single binder-design run, antibody or VHH engineering, docking, or one-off structure prediction.
---

# Run Anthropic's miniprotein binder campaign through MCP

This skill reproduces the campaign protocol Anthropic published with
[*Claude accelerates protein design*](https://www.anthropic.com/research/Claude-accelerates-protein-design)
— the `single_target` prompt in
[Anthropic/claude-protein-binder-design](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design/tree/main/prompts/prompts).
That document is one invariant protocol with the target swapped in; everything
below is it, with the compute substituted.

**The science is theirs and is frozen.** The roster and its per-method floor, the
four pre-scoring gates and their thresholds, the three-arm instrument, the score
algebra, the selection caps, the panel size — none of them are yours to retune.
They are implemented in the vendored kernel under `scripts/_kernel/`, which is a
function-by-function port carrying the protocol's own line references. Re-deriving
any of its formulas by hand is the defect this skill exists to prevent.

**What is substituted is the compute.** Their agents had a Modal account, a GPU
governor and a $10,000 budget, and stood every model up from source. You have a
catalogue of models already built and a job API, so each "install and validate X"
becomes a submission — and their spend governor, sandbox accounting and billing
calibration have no analogue here and are simply out of scope.

| Anthropic's campaign | Here |
|---|---|
| Modal sandboxes, concurrency governor, metered spend | Tamarind jobs; batch fan-out; no governor |
| build ESMFold2-Full / ESMFold2-Fast from source | `esmfold2`, selected by its `model` setting |
| build Protenix v2 (CUDA 12.4, checkpoint + CCD cache) | `protenix` |
| substitute arms: AF-Multimer-v3, AF3+OF3, Chai-1, Boltz | `alphafold`, `openfold`, `chai`, `boltz` |
| MMseqs2 against a staged UniRef90 | a sequence-identity search job, joined back in |
| Slack thread, Drive folder, sub-agent swarm | this conversation and the host workspace |
| 24-hour clock, 20k–200k designs | the user's actual budget — say what you scaled to |

Two protocol tools have **no Tamarind equivalent**: **FoldCraft** and
**HalluDesign**. FoldCraft is the one the protocol names for beta-containing and
mixed alpha-beta folds, so losing it costs the fold-diversity objective
specifically. Record both as dropped with that consequence stated — never as
though the roster were complete.

## 0. Own the science; delegate the mechanics

This skill owns the stage graph, the frozen values, the gates and the selection
rules. It owns no lifecycle:

- resolve every tool and setting live with `tamarind-mcp-tool-discovery`;
- run one job with `tamarind-mcp-submit-and-poll`, any fan-out with `tamarind-mcp-batch`;
- recover, inspect and cancel with `tamarind-mcp-results-analysis`.

Route away when the request is smaller or different: one generate-and-filter round
is `tamarind-mcp-binder-design`; antibody, nanobody or VHH engineering is
`tamarind-mcp-antibody` and is **out of scope here** — outputs stay single-chain
miniproteins, and known binders are not starting points or grafts.

## 0b. The gates are code — run them

Two bundled scripts carry every frozen number. **Do not re-derive their formulas.**
Each has a plausible wrong version that fails in the permissive direction and that
nothing downstream can detect: drop the `+1` in novelty coverage and every hit
under-reports; take `sc_DockQ` at the best-agreement seed instead of the
argmax-confidence seed and the number improves; make the pose term a mean instead
of a minimum and more designs pass.

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-mcp-miniprotein-campaign-skill"
python3 "$SKILL_DIR/scripts/campaign_gates.py" pool.json \
    --reference-chains refs.json --known-binders corpus/ \
    --out gates.csv --rejects rejects.json
python3 "$SKILL_DIR/scripts/select_panel.py" candidates.json \
    --gate gate.json --panel-size 30 --out design_sheet.csv --trace trace.json
```

Resolve `SKILL_DIR` to the directory holding this `SKILL.md`; do not assume the
shell starts there.

**`numpy` is not optional.** Without it the structural gates, the novelty gate and
`lcp_score` all report NOT_RUN — honest, but it means most of the protocol did not
run. It also switches off `select_panel.py`'s write-time recompute, which prints
`gate recompute: SKIPPED - disclose this` and ships the sheet anyway, so the halt
that catches a row whose gates do not reproduce is simply not running. Install it
before the campaign; if you genuinely cannot, say in the report that gate
reproduction was not verified.

**Where each piece runs.** Put the scripts on the workspace's own compute and keep
every artifact — the frozen plan, the gate verdict, the rejects ledger, each
stage's surviving pool, the sheet — in workspace storage under stable names,
because later stages read them back rather than re-deriving them.

**What is still on you.** `select_panel.py` refuses to emit a panel without a PASS
gate artifact and halts on a row whose gates do not reproduce. Nothing, however,
stops you submitting a scoring job that skips the validation gate entirely. On
Anthropic's harness that block was mechanical — a `submit_gate()` no job got past.
Here it is not. That boundary is yours.

## 1. The target dossier, before any design

Conduct a literature review of the target's biology first and record it. Before
generating or scoring anything, confirm and write down:

- **oligomeric state** at assay conditions;
- **constitutive cofactors and ligands** — structural metals, nucleic-acid
  partners, glycans;
- **the exact assay construct** — residue range, tags, fusion context;
- **which deposited structures** represent that state with the epitope ordered.

The scoring construct must match this assay-relevant system, **not a convenience
crop**. Where the dossier flags a cofactor as fold- or interface-required, at least
one ranking arm must represent it — and a scoring arm submitted as a bare sequence
string cannot, so that is a construct you must not score as if it were apo.

For the epitope: prefer biologically relevant interfaces already explored in the
design literature; novel epitopes need a differentiated hypothesis. Prefer
functional epitopes where a miniprotein can plausibly achieve a mechanism of
action.

## 2. Freeze the plan before any compute

Write the plan to a file in the host workspace and restate its frozen values in the
conversation:

- the **dossier** and the **scoring construct** — chains, crop, cofactors —
  identical at every seed tier;
- **the epitope** — residues, chain, and the evidence that chose them, in the
  target's own numbering;
- **controls** — which molecule fills each slot **and which chain of it**. Verify
  every control chain against the structure's entity records; never infer a chain
  from its position in the file. A control on the wrong face passes the validation
  gate cleanly and invalidates the campaign;
- **method vocabulary** — one token per tool, closed. `rfdiffusion` and
  `rfdiffusion3` are distinct tokens;
- **thresholds** — monomer mean-pLDDT floor (default **0.70** on the 0–1 scale / 70
  on 0–100), pose threshold (default **0.23**), novelty cutoffs, plausibility
  thresholds;
- **sheet schema** and the panel size (default **30**; a number the user asked for
  replaces 30 everywhere).

Freeze first, then compute. Changing a frozen value after production scoring has
begun is sheet corruption, not a refinement.

## 3. Probe the roster, then generate

See [references/roster.md](references/roster.md) for the roster, per-method
defaults that must be overridden, the epitope key per method, and the length
policy. In outline:

- single-chain miniproteins of **50–120 residues** (35–160 where epitope geometry
  motivates it, with the reason recorded), and **more than 25% away from every
  target chain's length** — several tool defaults land inside the mimic band;
- **at least 50 backbones from every starred method** not proved UNAVAILABLE.
  Throughput, cost and convenience are not grounds to skip one; a starred method
  that passed bring-up and contributed zero ranked backbones is a reportable
  defect;
- **every method gets the same frozen construct and the same frozen epitope** — and
  **almost nothing enforces this.** Seven of the eight aimable methods accept a
  submission with no epitope and run anyway; most drop the constraint, and
  FreeBindCraft picks its **own** site. Only Genie 3 refuses. Set the key on every
  submit, then **audit the site each method actually used from its own output**;
- backbone-only methods pass through sequence design before scoring; sequence-
  carrying methods must not, because the extra hop mints a second id space;
- use **SolubleMPNN / SolubleCaliby** for anything destined to be ordered; the base
  variants are fine for backbone search;
- scale generation to the user's budget and **state what you scaled to**. The
  protocol's own figure is 20,000–200,000 screened campaign-wide.

**Probe before production.** One small canary per method on the real target with
production settings, and exactly one verdict each: **PASS** (you opened its output
and one backbone reached a usable sequence), **UNAVAILABLE** (proved it cannot run
here, with the diversity objective the drop costs), **NOT_PROBED**, or
**RAN_NO_YIELD**. **Only UNAVAILABLE releases a method from its floor.**

**Read the files, not the file listing.** `getJobSchema(<type>).outputs.mainCSV`
names the actual result table; every other table is an intermediate. Then
`listJobFiles` to resolve that name, `getJobFile` to read it, and `getJobLogs` with
a bounded `maxLines` for a stage that died silently. Resolve status with `getJobs`
first — only a *terminal* job supports a verdict.

**A generator's own "success" table being empty is not the campaign's verdict.**
Measured: Genie 3 returned an **empty** `success_info.csv` while its actual result
table held two usable designs at interface confidence up to 0.83, each engaging
**all six** frozen epitope residues. A method's internal acceptance criteria are its
own; this campaign's gates are §4's.

At most two diagnosis-driven retries per method, then record the drop with its
consequence.

## 4. The four pre-scoring gates — before any co-folding spend

Every candidate is assessed before it is scored. Cluster de novo pools at ~90%
identity first; for close-variant pools drop only exact duplicates.

1. **novelty** — sequence identity and local alignment against UniRef90, the
   known-binder corpus, ubiquitin, and every chain of the target and controls, plus
   the structural TM screen;
2. **liability** — cysteine parity, homopolymer runs, surface hydrophobic patches;
3. **monomer foldability** — binder alone, mean pLDDT at or above the frozen floor;
4. **structural plausibility** — backbone geometry, steric clashes, core packing.

`campaign_gates.py` runs 1, 2 and 4 and records `lcp_score`, the protocol's
mandatory sequence restraint. Details, thresholds and the Tamarind job each
remaining limb needs are in [references/gates.md](references/gates.md).

**Record every rejected design_id and verify its absence from every downstream
pool** — a gate counts as run only when its rejects are traceably absent
downstream. **A gate that passes everything, fails everything, or returns a
constant is broken until investigated.**

Two limbs need a job and are NOT_RUN until you run one: **monomer foldability**
(a binder-alone fold) and **novelty's UniRef90 arm** (a sequence-identity search,
joined back with `--uniref90-hits`). The protocol requires the full-UniRef90 check
and the ubiquitin rejection **before any row reaches the final sheet** — that is
`--novelty-tier final`.

**Fold diversity** is a reported secondary objective, not a ranking gate: at least
**10% non-all-alpha** on the shipped sheet, where non-all-alpha means a beta strand
of ≥3 consecutive E/B residues **or** helical fraction below 70%. It is defined
**under DSSP**; the classifier's biotite fallback is **P-SEA**, a different
assignment that can disagree on exactly this criterion. Run DSSP yourself and pass
the codes per row as `ss_codes`; `campaign_gates.py` forwards them and stamps
`fold_ss_method`. Where you fall back, **name the method in the report**.

## 5. Validate the instrument on known answers

Production scoring is blocked until the validation gate passes, on two conditions:

- **(a) fold recapitulation** — the arm reproduces the target against a named
  CA-RMSD threshold;
- **(b) positive-control separation** — a known literature binder at full native
  stoichiometry scores clearly above negative controls.

Prefer a **non-antibody** positive control; co-folding models systematically
underperform on antibody–antigen interfaces, so an antibody is a secondary control
and one that fails (b) is weak evidence, not a failed gate. **Exclude published de
novo miniprotein binders** — they were themselves selected by co-folding metrics, so
their separation is circular. Add a **target self-pair control**, which exists
specifically to falsify target-mimic inflation. Calibrate the raw-score range
against a native complex ceiling band (e.g. Barnase/Barstar) and a constructed-
negative floor band; those are raw-score calibrations only, never z-scored.

Write the verdict to `gate.json` — `{"status": "PASS", "separation": <value>,
"controls": [...]}` — **before submitting a single production scoring row**.
`select_panel.py` reads this file and refuses to rank without it. Editing it to get
past the refusal falsifies the campaign's central claim.

## 6. Score on all three arms, on frozen algebra

[references/instrument.md](references/instrument.md) holds the arms, the algebra,
the seed tiers and the funnel. Load-bearing:

- **the arm axis is never tiered** — every co-folding stage runs all three arms.
  Measured, the same designed complex scored **0.025** on one arm and **0.586** on
  another: a 23-fold spread on the term the ranking is built from. A one-arm screen
  discards designs on evidence the frozen method never agreed with;
- reduce on the **pool** and the **seed count** only — SCREEN is 1 seed per arm,
  final is **5 distinct** seeds per arm;
- **interface confidence** is the minimum over both alignment directions, then max
  over seeds. **Build it from the two directional columns** — the `_max` column is
  this term's exact opposite and inflates it silently;
- **pose term** is the **minimum** over the arms that ran, at or above 0.23, and it
  is a *structural* DockQ you run yourself with the `dockq` tool. **Never substitute
  `pDockQ`** — that is a predicted DockQ from the same forward pass, so swapping it
  in replaces the campaign's only geometric check with a fourth correlated
  confidence estimate;
- **final_score** is the raw mean of the realized terms; **rank_zscore** is their
  per-target weighted z-score average, confidence weighted **4** and pose **1**.
  Rank on the z-score, report the raw numbers;
- a term an arm did not produce is **NOT_RUN** — never 0, never blank, never
  averaged in;
- shard every scoring batch at **500 members or fewer**.

**Thread every sequence programmatically from the generation table into the
submission. Never transcribe one.** A hand-built scoring submission is how a design
id ends up naming one molecule while the numbers beside it describe another, and
**no gate can catch it** — the gates recompute against the row's own sequence, so a
row scored on the wrong molecule reproduces perfectly. Verified on a real run this
produced two bad rows: one id named design `n1` while the job folded `n0`, and one
submitted sequence matched no design in any result table. Write the complex FASTA
programmatically, upload it, fan out with `fromFile` plus `sharedSettings`, then
read each job's stored input back (`getJobs(..., includeSequences=true)`) and carry
it onto the row as `scored_sequence` **verbatim, both chains**. Reconcile by
sequence, never by position or job name — and collapse identical binder sequences
*before* submitting, because reconciliation is only unique while they are.

On an oligomeric target, score every ranked design at **both** stoichiometries —
1:N (which feeds the ranking) and N:N — and disclose any design whose N:N score
collapses. Put the stoichiometry beside every number.

## 7. Optimize — five rounds minimum

At least five rounds, continuing while the metrics improve: partial diffusion with
sequence redesign; iterative predict-then-redesign; sequence redesign by sampling
or mutagenesis. Feed the **predicted complex** back into sequence design, **not**
the design's own structure — feeding the designed structure back is the previous
round again. Every child keeps its parent's `root_backbone_id`; minting a fresh
root escapes the per-root cap while looking like ordinary provenance. Promote to
the full seed tier **before** selecting the next round's parents. Select what you
ship across the original round and every optimization round.

## 8. Select the panel

`select_panel.py` computes the algebra, applies the caps and the ladder, and
recomputes every gate against the row's own sequence — halting on any row that does
not reproduce to 1e-4. The caps, in selection order: exact duplicates; Levenshtein
distance below five; `root_backbone_id` at 5%; TM-0.90 cluster at 10%;
`structure_method` at 50% and at least three distinct methods; `seq_method` at
two-thirds. Full tables in [references/selection.md](references/selection.md).

Read its `rejection_counts`: a panel emptied by `missing_provenance_field` is a
pipeline gap, one emptied by the caps is an under-diverse pool, and they have
opposite repairs. If the pool cannot fill the panel, fix it upstream — more
designs, more methods. Relaxation is a disclosed last resort applied to thresholds,
never by skipping a gate. **If even that cannot reach the panel size, ship the real
N; padding with duplicates is forbidden.**

The pool these scripts read is **not** the shape any tool emits. Building it is a
real step, and the two ways it goes wrong silently — an inverted chain split and a
collapsed identifier — are in [references/pool_schema.md](references/pool_schema.md).
Read it before the first gate run.

## 9. Ship the deliverables

The design sheet is the deliverable, and it travels with companions that let
someone else reproduce it. See
[references/deliverables.md](references/deliverables.md) for the full set and each
one's invariants.

Nothing computed is discarded: every configuration, every structure file from every
scoring seed and arm, every intermediate from every optimization round, the run
manifest, and the failure records.

## 10. Speak to the user in their language

Verdict tokens, column names, settings keys and file names are your reasoning
material and never appear in user-visible text. Say "the scoring method", "fixed
before we looked at any design, so the cutoffs cannot be tuned to flatter the
results", "the check that the scoring works on this target", "did not run", "not
tested yet — nothing is ruled out". Give residues in the target's own numbering.

**State only what you established.** Every factual claim traces to a computation you
ran or an artifact you can cite. "Verified" means you have the output. Never write
an external identifier from memory. Treat anomalies as bugs until investigated — a
score of exactly zero, a gate passing or failing everything, a perfect metric, an
impossible runtime. Before committing significant compute to a plan, run the
cheapest check that could falsify it.

**Lead with the unfavorable result.** Headlines state the worst defensible reading
of the data. Report messy or inconclusive results as such. These standards bind
*tighter* under autonomy, not looser: no human reviews this before the compute is
spent, so your own verification discipline is the only gate there is.

## 11. Disclose what this campaign did not do

Name in the report, in the user's words: every method dropped and what it cost —
including FoldCraft and HalluDesign, which this platform does not carry; any gate
that did not run and what it no longer catches; any instrument term missing and
why; the stoichiometry beside every number on a multimeric target; and any
substitution made for a check the protocol specifies. A disclosed gap is a result.
A silent one is a defect.
