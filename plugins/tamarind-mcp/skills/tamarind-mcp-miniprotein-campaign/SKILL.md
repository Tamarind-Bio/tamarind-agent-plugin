---
name: tamarind-mcp-miniprotein-campaign
description: Run a multi-method de novo miniprotein binder campaign through MCP against one target and epitope, on a scoring method fixed before any design is seen, validated on known-answer controls before production spend, and shipped as a ranked, diversity-capped panel with per-design provenance. Use for a reproducible panel or a like-for-like comparison across generation methods. Not for a single binder-design run, antibody or VHH engineering, docking, or one-off structure prediction.
---

# Run a miniprotein binder campaign through MCP

The deliverable is not throughput. It is that **every number you ship traces to a computation you ran under a scoring method you fixed before you looked at any design.** Everything below serves that.

## 0. Own the science; delegate the mechanics

This skill owns the stage graph, the frozen values, the gates and the selection rules. It owns no lifecycle:

- resolve every tool and setting live with `tamarind-mcp-tool-discovery`;
- run one job with `tamarind-mcp-submit-and-poll`, any fan-out with `tamarind-mcp-batch`;
- recover, inspect and cancel with `tamarind-mcp-results-analysis`.

Route away when the request is smaller or different: one generate-and-filter round is `tamarind-mcp-binder-design`; antibody, nanobody or VHH engineering is `tamarind-mcp-antibody` and is **out of scope here** — outputs stay single-chain miniproteins, and known binders are not starting points or grafts.

## 0b. The gates are code, not prose — run them

Two bundled scripts carry every frozen number in this campaign. **Do not re-derive their formulas.** Each one has a plausible wrong version that fails in the permissive direction and that nothing downstream can detect: drop the `+1` in novelty coverage and every hit under-reports, which errs toward *admitting* a design at the reject threshold; take `sc_DockQ` at the best-agreement seed instead of the argmax-confidence seed and the number improves; make the pose term a mean instead of a minimum and more designs pass. Hand-deriving these is a defect, not diligence.

```bash
SKILL_DIR="/absolute/path/to/the/tamarind-mcp-miniprotein-campaign-skill"
python3 "$SKILL_DIR/scripts/campaign_gates.py" pool.json --reference-chains refs.json --out gates.csv --rejects rejects.json
python3 "$SKILL_DIR/scripts/select_panel.py" candidates.json --gate gate.json --panel-size 30 --out design_sheet.csv --trace trace.json
```

Resolve `SKILL_DIR` to the directory holding this `SKILL.md`; do not assume the shell starts there. The scripts need `numpy` for the structural gates — without it they report those gates **NOT_RUN**, which is honest, and they never report them passed.

**`numpy` also switches off the write-time recompute**, and that is the larger loss: without it `select_panel.py` prints `gate recompute: SKIPPED - disclose this` and ships the sheet anyway, so the halt in §7 that catches a row whose gates do not reproduce is simply not running. A stock machine often has no `numpy`. Install it before the campaign rather than discovering at the sheet that the campaign's last check never fired — and if you genuinely cannot, say in the report that gate reproduction was not verified.

The pool these scripts read is **not** the shape any tool emits. Building it is a real step, and the two ways it goes wrong silently — an inverted chain split and a collapsed identifier — are in [references/pool_schema.md](references/pool_schema.md). Read it before the first gate run.

**Where each piece runs.** Put the scripts on the workspace's own compute and keep every artifact — the frozen plan, the gate verdict, the rejects ledger, each stage's surviving pool, the sheet — in workspace storage under stable names, because later stages read them back rather than re-deriving them. Where the workspace can run review passes as separate agents, use one per review in §8 and keep them strictly serial. Where it cannot, run them yourself in the same order and say so.

**What is still on you.** `select_panel.py` refuses to emit a panel without a PASS gate artifact, and it halts on a row whose gates do not reproduce — those two are mechanical. Nothing, however, stops you from submitting a scoring job that skips the gate entirely. That boundary is yours to hold, and §5 is where it costs the most.

## 1. Freeze the plan before any compute

Research the target's biology first, then write the plan to a file in the host workspace and restate its frozen values in the conversation. It records:

- **target dossier** — oligomeric state at assay conditions, constitutive cofactors and ligands, the exact assay construct (residue range, tags, fusion context), and which deposited structures show that state with the epitope ordered;
- **scoring construct** — chains, crop, cofactors — identical at every seed tier;
- **the epitope** — residues, chain, and the evidence that chose them, in the target's own numbering;
- **controls** — which molecule fills each slot **and which chain of it**. Verify every control chain against the structure's entity records; never infer a chain from its position in the file. A control on the wrong face passes the validation check cleanly and invalidates the whole campaign;
- **method vocabulary** — one token per tool, closed. `rfdiffusion` and `rfdiffusion3` are distinct tokens;
- **thresholds** — monomer mean-pLDDT floor, pose threshold, novelty cutoffs, plausibility thresholds;
- **sheet schema** and the panel size (default 30; if the user asked for another number, that number replaces 30 everywhere).

Freeze first, then compute. Changing a frozen value after production scoring has begun is sheet corruption, not a refinement. Cofactors go in truthfully: a scoring arm submitted as a single sequence string cannot represent one, so a construct that needs a cofactor is a construct you must not score as if it were apo.

## 2. Probe every method before production compute

Run one small canary per generation method **on the real target with production settings**, and give each method exactly one verdict:

- **PASS** — the canary ran, you opened its output, and one backbone reached a usable amino-acid sequence;
- **UNAVAILABLE** — proved it cannot run here, with the diversity objective the drop costs;
- **NOT_PROBED** — no canary yet. Nothing is known and nothing is ruled out;
- **RAN_NO_YIELD** — it ran and produced nothing usable, cause not yet established.

**Only UNAVAILABLE releases a method from its floor.** Recording it for a method you merely have not tested quietly excuses that method from the campaign.

**Read the files, not the file listing.** Ask the schema which file is the result before you open anything: `getJobSchema(<type>).outputs.mainCSV` names the actual result table, and every other table the job wrote is an intermediate. It is often neither the first nor the largest file, and guessing from the listing is what once cost a working method its place in a campaign. Then `listJobFiles` to resolve that name (it may be a glob or a job-name template), `getJobFile` to read it, and `getJobLogs` with a bounded `maxLines` for a stage that died silently. Then name **which stage** lost the designs. "This method produced nothing" is a restatement, not a diagnosis, and it is the sentence that drops a working method.

**Check the job's status before you read absence as evidence.** An empty log and an empty file listing look identical whether the job has not started, is still running, or finished having produced nothing — the tools say so in their own hints. Resolve the status with `getJobs` first: only a *terminal* job supports a verdict. A queued job is NOT_PROBED, not RAN_NO_YIELD.

When the diagnosis points at a setting, change that setting and re-run the canary. **At most two diagnosis-driven retries**, each changing something a diagnosis pointed at; then record the drop with its consequence and move that compute to methods that are producing. The common repairable shape is a generator whose own in-job sequence step rejects everything: turn that step off and route its backbones through this campaign's own sequence-design pass instead.

Probe the **chain**, not the first link. A canary is unfinished until one backbone has become a sequence you can score, and the record names the residues, the job you read them from, and the tool that produced them. A sequence field holding a filename, a path or a status word is no sequence at all.

## 3. Generate — one construct, one epitope, a floor per method

See `references/roster.md` for the roster, the sequence-carrying split, the epitope setting keys and the length policy. In outline:

- single-chain miniproteins of **50–120 residues** (35–160 where epitope geometry motivates it, with the reason recorded), and **more than 25% away from every target chain's length** — set the length explicitly on every submit, because several tool defaults land inside the mimic band;
- **every method gets the same frozen construct and the same frozen epitope** — and **almost nothing enforces this**. Seven of the eight aimable methods accept a submission with no epitope at all and run anyway: most simply drop the constraint, and FreeBindCraft goes further and picks its **own** site. Only Genie 3 refuses. So a missing epitope key is a silent event on nearly every method, and the resulting designs look like ordinary members of the pool. Set the key on every submit from `references/roster.md`, then **audit the site each method actually used from its own output** — that is the only evidence that the comparison this campaign exists to make was even run. Filling unresolved residues from the reference sequence inside the construct's own range is mechanical and needs no approval. Widening the construct is a different molecule and is never a per-method fix;
- **at least 50 backbones from every starred method** not proved UNAVAILABLE. Track the per-method count as an open obligation;
- backbone-only methods must pass through sequence design before they can be scored; sequence-carrying methods must not, because the extra hop mints a second id space and is how a design ships another backbone's sequence;
- use the soluble sequence-design variant for anything destined to be ordered;
- ~20,000 designs before gating, fanned out with `tamarind-mcp-batch`, never a loop of `submitJob`.

Record per design whether its method was aimed at the frozen site. Methods that cannot be aimed are diversity arms, not failures — keep them, disclose that they were unaimed, and check their designs' contacts against the frozen site afterwards instead of assuming engagement.

## 4. Gate before any co-folding spend

Every candidate is assessed before it is scored: novelty (sequence identity, local alignment, and structural similarity to any target or control chain), liability (cysteine parity, homopolymer runs, hydrophobic patches), monomer foldability (binder alone, mean pLDDT at or above the frozen floor), and structural plausibility. Cluster the pool at ~90% identity.

Run these with `campaign_gates.py` (§0b), not by hand and not through paid jobs. It writes one evidence row per design carrying the numbers that decided each verdict, plus the rejects ledger. **Record every rejected design_id and verify its absence from every downstream pool** — a gate counts as run only when its rejects are traceably absent downstream. **A gate that passes everything, fails everything, or returns a constant is broken until investigated.**

The mimic screen is the one that has no second falsifier downstream: a structure generator conditioned on the target complex, asked for a binder near a target chain's length, will happily reproduce that chain's fold, and every confidence arm will like it.

## 5. Validate the scoring on known answers before production scoring

Score the control panel first — a genuine positive control, several negatives, and a target-self-pair control that exists specifically to falsify target-mimic inflation — confirm the scoring separates them, and **write the verdict to `gate.json` before submitting a single production scoring row** — `{"status": "PASS", "separation": <value>, "controls": [...]}`. `select_panel.py` reads this file and refuses to rank anything unless `status` is PASS or PASS_REDUCED, so the artifact is the gate, not a note about it. Editing it to get past the refusal is falsifying the campaign's central claim. Exclude published de novo miniprotein binders as controls: their separation is circular.

On the campaign harness this block is mechanical. Here it is not. Nothing will stop a production submission, so the check is only real if you refuse to proceed without it.

## 6. Score on all three arms, on frozen algebra

`references/instrument.md` holds the arms, the score algebra, the seed tiers and the funnel. Load-bearing invariants:

- **the arm axis is never tiered** — every co-folding stage runs all three arms. The arms disagree exactly where it matters, so a one-arm cut discards designs on evidence the frozen method never agreed with;
- reduce on the **pool** and the **seed count** only. No design carries a headline score without the full multi-seed score on all arms;
- shard every scoring batch at **500 members or fewer**;
- a term an arm did not produce is **NOT_RUN** — never 0, never blank, never a plausible-looking number, and never averaged in;
- when a limb did not run, report the **consequence**, not just the gap.

Building these rows is the campaign's most error-prone submission. A scoring row must pair the target with the candidate in the combined value the live schema defines. **`fromJob` folds the candidate alone** — it reads a design job's generated sequences, which are binders — so it cannot build a complex.

**Prefer a complex FASTA over hand-built settings.** `fromFile` folds *whatever each record contains*, and a record holding the joined `TARGET:BINDER` value is submitted as the complex — measured, the stored input comes back with both chains intact. So write the FASTA programmatically from the generation table, upload it, and fan out with `fromFile` plus `sharedSettings`. That is the only route on which **no sequence passes through your hands**, which is the whole point: see the transcription rule below. Building explicit `settings` + matching `jobNames` also works and is what `tamarind-mcp-batch` documents, but every sequence in it is one you typed.

Two things `fromFile` does not give you: the record id does **not** become the job name (jobs come back numbered in file order), and nothing ties a returned row to a design. Reconcile by reading each job's stored input sequence back and matching it to the design's binder — never by position, and never by job name.

**Thread every sequence programmatically from the generation table into the submission. Never transcribe one.** A hand-built scoring submission is how a design id ends up naming one molecule while the numbers beside it describe another, and **no gate can catch it** — the gates recompute against the row's own sequence, so a row scored on the wrong molecule reproduces perfectly and ranks on numbers that are not its own. Verifying this on a real run produced both failures in two rows: one id named design `n1` while the job folded `n0`, and one submitted sequence matched **no design in any result table** — it shared a prefix with a real design and then diverged. The platform accepted both, folded them, and returned entirely plausible confidence.

So close it mechanically. After scoring, read each job's stored input back from the platform (`getJobs(jobName=..., includeSequences=true)` returns the exact `sequence` submitted), and carry it onto the row as `scored_sequence`. `select_panel.py` halts when it disagrees with the row's own sequence, and warns when no row carries it at all. Reconcile by sequence, not by position or by job name — the sequence is the only thing that is the same object on both sides of the submission.

## 7. Optimize, then select

At least five optimization rounds, continuing while the metrics improve. Feed the **predicted complex** back into sequence design, not the design's own structure — feeding the designed structure back is the previous round again. Every child keeps its parent's `root_backbone_id`; minting a fresh root escapes the per-root cap while looking like ordinary provenance. Promote to the full seed tier **before** selecting the next round's parents, so parents are chosen on settled numbers.

`select_panel.py` (§0b) computes the score algebra, applies the caps and the ladder, sorts on the rank key and recomputes every gate against the row's own sequence — halting on any row that does not reproduce to 1e-4. Read its `rejection_counts`: a panel emptied by `missing_provenance_field` is a pipeline gap, one emptied by the caps is an under-diverse pool, and they have opposite repairs. The full tables are in `references/selection.md`. If the pool cannot fill the panel under the caps, fix it upstream — more designs, more methods. Relaxation is a disclosed last resort applied to thresholds, never by skipping a gate. **If even that cannot reach the panel size, ship the real N; padding with duplicates is forbidden.**

## 8. Speak to the user in their language

Verdict tokens, column names, settings keys and file names are your reasoning material and never appear in user-visible text. Say "the scoring method", "fixed before we looked at any design, so the cutoffs cannot be tuned to flatter the results", "the check that the scoring works on this target", "did not run", "not tested yet — nothing is ruled out". Give the residues in the target's own numbering, never a settings key.

Every factual claim traces to a computation you ran or an artifact you can cite. "Verified" means you have the output. Never write an external identifier from memory.

## 9. Disclose what this campaign did not do

Name in the report, in the user's words: any method dropped and what it cost, any gate that did not run and what it no longer catches, any instrument term missing and why, the stoichiometry beside every number on a multimeric target, and any substitution made for a check specified in the protocol you are reproducing. A disclosed gap is a result. A silent one is a defect.
