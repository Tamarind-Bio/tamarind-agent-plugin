# The scoring method: arms, algebra, validation, and the funnel

> Model names and settings change. Resolve every arm with `getAvailableTools` and `getJobSchema` before submitting, and treat a missing arm as a disclosed instrument reduction, never as a silent substitution.

## The three arms

All three are all-atom co-folders, one sample per seed. The bold name is the only one you use with the user. **Never refer to an arm by position** — "the third arm" names nothing a protein designer can act on.

- **ESMFold2 with MSA** — target-chain MSAs, binder single-sequence.
- **ESMFold2 (fast)** — single-sequence only. Its released checkpoint has no MSA encoder, so passing an MSA is a silent no-op; never claim it used one.
- **Protenix-v2** — target-chain MSAs, binder single-sequence.

All three compute the interface confidence term in-job, but it degrades to a soft warning rather than a job failure, and it is correctly skipped for a monomer construct. **Verify the column per arm on the rows in hand.** A missing column is silent and is caught by checking, not by trusting.

Three constructs are needed and they are different submissions:

- **complex** — binder plus target. The ranking construct.
- **monomer binder** — the binder alone, for the foldability gate.
- **target only** — the target alone, for the fold-recapitulation check at validation.

## Score algebra — fix it, then never touch it

- **Interface confidence per arm** = minimum over both alignment directions, then **max over seeds**.
- **Self-consistency per arm** = structural agreement between the designed complex and that arm's prediction **at the argmax-interface-confidence seed** — not the best-agreement seed. Record both argmax seeds per arm so seed concordance is auditable. Chain mapping is the best symmetric relabeling, which applies on monomeric targets too, since chain ids may differ between designed and predicted structures.
- **Pose term** = the **minimum** over the arms that ran, passing at or above the frozen threshold (default 0.23). Because it is a minimum, it is comparable across designs only when the same arms ran for each: two arms of three reads **systematically higher** than three, so a row missing an arm's term is written NOT_RUN rather than given a minimum over what is left. Never approximate this term from the legs that did run.
- **final score** = the **raw mean of the terms actually realized**. Never z-scored, never averaging a NOT_RUN term as 0. Every row names which subset it realized.
- **rank score** = the per-target weighted z-score average of those same realized terms, each confidence z-term weighted **4** and each self-consistency z-term weighted **1**. A NOT_RUN term is absent from the average, never zero.
- **z-scores are transductive** — the mean and spread depend on the scored pool, so they are comparable only within the batch that produced them, never across waves or campaigns. Record raw values and seed count on every row so any batch can be re-standardized. **Rank and select on the z-score; report the raw numbers.**

**When the pose term does not run, say what was lost, not just what is missing.** It is the only geometric check. Every remaining term is a confidence estimate from the same co-folder family, so a design whose arms confidently agree on a wrong pose — wrong epitope, flipped bundle, wrong face — is no longer caught. That is precisely the failure the pose term exists to gate. Put that sentence in the report, in user-visible text.

**Shadow metrics.** Track whole-complex confidence and interface-scoring diagnostics from the same forward pass as free diagnostics; ranking uses the interface confidence term only. On multimeric targets whole-complex confidence is inflated by native protomer-protomer interfaces and compresses design-versus-control separation.

**Templates.** No template injection in production. A template-driven prediction is a validation diagnostic only, for when no co-folder recapitulates the apo target.

## Seed tiers

- **Screen** — 1 seed per arm.
- **Intermediate and final** — **5 distinct integer seeds** per arm. Assert the seeds are distinct: a per-design standard deviation of exactly 0 across more than one seed is a bug, not a result.

## The validation check, before production scoring

Score the control panel and confirm the method separates known answers **before** any production scoring row is submitted:

- a genuine positive control, with **its chain verified against the structure's entity records**;
- several negative controls;
- a **target self-pair control** — the target scored against itself — which exists specifically to falsify target-mimic inflation. Without it, a scoring method that rewards anything shaped like the target looks like a scoring method that works;
- **exclude published de novo miniprotein binders as controls.** Their separation is circular.

Also demonstrate that the multi-seed ensemble adds ranking information over a single-seed baseline, and report the measured seed variance. Run the reduced screening instrument on the same control panel and report its rank correlation against the full instrument — that number is what quantifies the cost of every reduced tier below.

Write the verdict — PASS, PASS with a named reduction, or FAIL — to a file before proceeding. Production scoring on an unvalidated method is the failure this whole section exists to prevent, and on the MCP surface nothing enforces it but you.

## The funnel

Stage the **pool** and the **seed count**. Never stage the arm axis.

| Stage | Pool | Filter |
|---|---|---|
| generate | → ~20,000 | roster batches, per-method floor |
| pre-scoring gates | → ~6,000 | liability and plausibility on the host; clustering; cheap sequence-level novelty only — self-similarity, known-binder corpus, composition. **Zero co-folding spend.** |
| monomer foldability | → ~4,000 | binder-alone mean pLDDT at or above the frozen floor |
| screen | → ~1,200 | rank score over interface confidence, **all three arms**, 1 seed |
| intermediate | → ~300 | same instrument, all three arms, cut deeper on the survivors; database novelty search starts here, one job per sequence |
| final | ranked | full realized score, 5 distinct seeds on all three arms, database novelty breadth, exact clustering cap check on the shipped panel |

Shard every scoring batch at **500 members or fewer**.

**Verify each stage actually ran before scaling it.** After the first shard of any scoring or filtering stage, confirm from its outputs that the stage ran as specified — item counts, pass and fail counts, one spot-checked example — before launching the rest.

**Carry the surviving pool forward as an artifact, not as a re-derived list.** A large design job's file listing can exceed the listing cap and come back partial, and a partial pool scores a subset while looking complete. Write each stage's survivors to a file and read the next stage's members from it.

## Optimization rounds

At least five rounds, continuing while the metrics improve.

- **partial diffusion with sequence redesign** — re-diffuse part of a promising backbone and redesign its sequence;
- **iterative predict-then-redesign** — feed the **predicted complex** back into sequence design, **not** the design's own structure. Feeding the designed structure back is not a weaker version of this round, it is the previous round: it re-samples sequence against a backbone nothing has folded;
- **sequence redesign** by sampling or mutagenesis.

Round 1 starts only after at least one full generation plus sequence-design wave is indexed and screened. Each round's outputs are scored on the **same instrument and seed count** as the pool that seeded it — a round scored at a different tier compares two measurements, not two designs. Promote to the full seed tier **before** selecting the next round's parents. Rank parents on the confidence and self-consistency terms together; if the pose limb did not run, say so before starting, because the loop is then hill-climbing on what makes a co-folder confident with no geometric check anywhere in the objective.

Select what you ship across the original round **and** every optimization round: a round-4 design competes with a round-0 design on the same instrument, never on its round number. Five rounds is the floor, not the target — stop at the plateau, and say which round you stopped at and what the last round bought. A round that improved nothing is a result, and reporting it is what makes the rounds that did improve credible.
