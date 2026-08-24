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

**State this once, at the start, and then honor it.** The MCP server stores no campaign plan, builds no scoring batch, runs no analysis sandbox, and has no gate that can refuse a submission. Every guarantee below is therefore a procedure you run and show, not a mechanism that stops you. A campaign that reports a check it did not run is worse than one that reports the gap.

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

**Read the files, not the file listing.** Call `listJobFiles`, then `getJobFile` on the actual result table — it is often neither the first nor the largest file — and `getJobLogs` with a bounded `maxLines` for a stage that died silently. Then name **which stage** lost the designs. "This method produced nothing" is a restatement, not a diagnosis, and it is the sentence that drops a working method.

When the diagnosis points at a setting, change that setting and re-run the canary. **At most two diagnosis-driven retries**, each changing something a diagnosis pointed at; then record the drop with its consequence and move that compute to methods that are producing. The common repairable shape is a generator whose own in-job sequence step rejects everything: turn that step off and route its backbones through this campaign's own sequence-design pass instead.

Probe the **chain**, not the first link. A canary is unfinished until one backbone has become a sequence you can score, and the record names the residues, the job you read them from, and the tool that produced them. A sequence field holding a filename, a path or a status word is no sequence at all.

## 3. Generate — one construct, one epitope, a floor per method

See `references/roster.md` for the roster, the sequence-carrying split, the epitope setting keys and the length policy. In outline:

- single-chain miniproteins of **50–120 residues** (35–160 where epitope geometry motivates it, with the reason recorded), and **more than 25% away from every target chain's length** — set the length explicitly on every submit, because several tool defaults land inside the mimic band;
- **every method gets the same frozen construct and the same frozen epitope.** Filling unresolved residues from the reference sequence inside the construct's own range is mechanical and needs no approval. Widening the construct is a different molecule and is never a per-method fix;
- **at least 50 backbones from every starred method** not proved UNAVAILABLE. Track the per-method count as an open obligation;
- backbone-only methods must pass through sequence design before they can be scored; sequence-carrying methods must not, because the extra hop mints a second id space and is how a design ships another backbone's sequence;
- use the soluble sequence-design variant for anything destined to be ordered;
- ~20,000 designs before gating, fanned out with `tamarind-mcp-batch`, never a loop of `submitJob`.

Record per design whether its method was aimed at the frozen site. Methods that cannot be aimed are diversity arms, not failures — keep them, disclose that they were unaimed, and check their designs' contacts against the frozen site afterwards instead of assuming engagement.

## 4. Gate before any co-folding spend

Every candidate is assessed before it is scored: novelty (sequence identity, local alignment, and structural similarity to any target or control chain), liability (cysteine parity, homopolymer runs, hydrophobic patches), monomer foldability (binder alone, mean pLDDT at or above the frozen floor), and structural plausibility. Cluster the pool at ~90% identity.

Run the cheap sequence-level and geometric checks on the host, not through paid jobs. **Record every rejected design_id and verify its absence from every downstream pool** — a gate counts as run only when its rejects are traceably absent downstream. **A gate that passes everything, fails everything, or returns a constant is broken until investigated.**

The mimic screen is the one that has no second falsifier downstream: a structure generator conditioned on the target complex, asked for a binder near a target chain's length, will happily reproduce that chain's fold, and every confidence arm will like it.

## 5. Validate the scoring on known answers before production scoring

Score the control panel first — a genuine positive control, several negatives, and a target-self-pair control that exists specifically to falsify target-mimic inflation — confirm the scoring separates them, and **write the verdict down before submitting a single production scoring row.** Exclude published de novo miniprotein binders as controls: their separation is circular.

On the campaign harness this block is mechanical. Here it is not. Nothing will stop a production submission, so the check is only real if you refuse to proceed without it.

## 6. Score on all three arms, on frozen algebra

`references/instrument.md` holds the arms, the score algebra, the seed tiers and the funnel. Load-bearing invariants:

- **the arm axis is never tiered** — every co-folding stage runs all three arms. The arms disagree exactly where it matters, so a one-arm cut discards designs on evidence the frozen method never agreed with;
- reduce on the **pool** and the **seed count** only. No design carries a headline score without the full multi-seed score on all arms;
- shard every scoring batch at **500 members or fewer**;
- a term an arm did not produce is **NOT_RUN** — never 0, never blank, never a plausible-looking number, and never averaged in;
- when a limb did not run, report the **consequence**, not just the gap.

Building these rows is the campaign's most error-prone submission. A scoring row that pairs a target with a candidate needs the combined value the live schema defines, so build explicit `settings` plus matching `jobNames` — `fromJob` and `fromFile` fan-outs fold the candidate alone. `tamarind-mcp-batch` owns that contract; follow it.

## 7. Optimize, then select

At least five optimization rounds, continuing while the metrics improve. Feed the **predicted complex** back into sequence design, not the design's own structure — feeding the designed structure back is the previous round again. Every child keeps its parent's `root_backbone_id`; minting a fresh root escapes the per-root cap while looking like ordinary provenance. Promote to the full seed tier **before** selecting the next round's parents, so parents are chosen on settled numbers.

Selection caps, the relaxation ladder, the rank key, the sheet columns and the deliverables are in `references/selection.md`. If the pool cannot fill the panel under the caps, fix it upstream — more designs, more methods. Relaxation is a disclosed last resort applied to thresholds, never by skipping a gate. **If even that cannot reach the panel size, ship the real N; padding with duplicates is forbidden.**

## 8. Speak to the user in their language

Verdict tokens, column names, settings keys and file names are your reasoning material and never appear in user-visible text. Say "the scoring method", "fixed before we looked at any design, so the cutoffs cannot be tuned to flatter the results", "the check that the scoring works on this target", "did not run", "not tested yet — nothing is ruled out". Give the residues in the target's own numbering, never a settings key.

Every factual claim traces to a computation you ran or an artifact you can cite. "Verified" means you have the output. Never write an external identifier from memory.

## 9. Disclose what this campaign did not do

Name in the report, in the user's words: any method dropped and what it cost, any gate that did not run and what it no longer catches, any instrument term missing and why, the stoichiometry beside every number on a multimeric target, and any substitution made for a check specified in the protocol you are reproducing. A disclosed gap is a result. A silent one is a defect.
