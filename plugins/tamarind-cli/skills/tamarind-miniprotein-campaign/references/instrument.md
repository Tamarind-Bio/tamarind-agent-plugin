# The scoring method: arms, algebra, validation, and the funnel

> Model names and settings change. Resolve every arm with `tamarind --json tools` and `tamarind --json schema TOOL` before submitting, and treat a missing arm as a disclosed instrument reduction, never as a silent substitution.

## The three arms

All three are all-atom co-folders. The bold name is the only one you use with the user. **Never refer to an arm by position** — "the third arm" names nothing a protein designer can act on.

**Two of the three arms are the same tool.** They are separated by a `model` setting, not by a job type, and that is the single most important mechanical fact on this page. Resolve all of it with `tamarind --json schema TOOL` before submitting; this snapshot is grounded but it is not the authority.

| Arm (user-facing) | Job `type` | Settings that select it |
|---|---|---|
| **ESMFold2 with MSA** | `esmfold2` | `{"model": "esmfold2", "useMSA": true}` |
| **ESMFold2 (fast)** | `esmfold2` | `{"model": "esmfold2-fast"}` |
| **Protenix-v2** | `protenix` | — |

Three traps, each of which produces a campaign that looks complete and is not:

- **Omitting `model` runs the same arm twice.** `model` defaults to `esmfold2`, so two submissions that differ only in the label you gave them are one arm run twice. The rows come back with identical columns and nothing downstream can tell. That is the "never tier the arm axis" invariant failing silently, which is the failure this whole section exists to prevent. **Set `model` explicitly on every ESMFold2 submission, including the full one.**
- **`esmfold2-binder-design` is a different tool** — a binder *generator*, not a co-folder. A catalog search for "esmfold" returns it beside the two you want. Select on the exact token, never on name similarity.
- **The fast checkpoint has no MSA encoder.** `useMSA` is conditional on `model == "esmfold2"` and does not apply to the fast model, which always runs single-sequence. Never claim the fast arm used an MSA.

**The arms do not agree on the pLDDT scale, and the monomer gate is where that bites.** Measured on real rows for the same construct: ESMFold2 reports mean pLDDT on **0–1** (0.7884) and Protenix on **0–100** (86.75). The frozen monomer-foldability floor is a 0–1 number (default 0.70), so a Protenix-derived pLDDT compared against it clears for **every design** — the gate keeps reporting PASS while rejecting nothing, which is worse than not running it. Fix the column, not the floor: put whichever arm you read the monomer fold from onto the floor's scale in the pool, and record in the plan which convention the frozen floor is written in. `select_panel.py` halts on a `monomer_plddt` above 1.0 against a 0–1 floor rather than ranking through it.

**The per-chain MSA policy is not expressible on this platform, and that is a disclosed instrument reduction.** `useMSA` is a single global boolean over the whole prediction; Protenix exposes no MSA toggle at all. There is no way to give the target chain an MSA while holding the binder single-sequence. Record what you actually ran — MSA on or off for the entire complex — and never describe the run in per-chain terms the settings could not have produced.

All three compute the interface confidence term in-job (`ipSAE_*`, per ordered chain pair plus a `_max` aggregate), but it degrades to a soft warning rather than a job failure, and it is correctly skipped for a monomer construct. **Verify the column per arm on the rows in hand.** A missing column is silent and is caught by checking, not by trusting.

**How far the arms actually disagree, measured.** The same designed complex, scored on two arms in the same campaign:

| design | ESMFold2-Fast | Protenix-v2 |
|---|---|---|
| an RFdiffusion binder | ipSAE **0.025**, ipTM 0.42 | ipSAE **0.586**, ipTM 0.84 |
| a BoltzGen binder | ipSAE 0.014 | ipSAE 0.299 |

A **23-fold** spread on the term the ranking is built from, on the same molecule. Neither arm is wrong; they are different models with different failure modes, and that is the entire reason the arm axis is never tiered. A campaign that screened on ESMFold2 alone would have discarded the strongest design in this pool before Protenix ever saw it — on evidence the frozen method never agreed with.

Three constructs are needed and they are different submissions:

- **complex** — binder plus target. The ranking construct.
- **monomer binder** — the binder alone, for the foldability gate.
- **target only** — the target alone, for the fold-recapitulation check at validation.

## Score algebra — fix it, then never touch it

- **Interface confidence per arm** = minimum over both alignment directions, then **max over seeds**.

  **Build it from the two directional columns. The `_max` column is this term's exact opposite.** A real arm row carries `ipSAE_AB`, `ipSAE_BA` **and** `ipSAE_AB_max` — and measured across three real scoring rows, `ipSAE_AB_max` is the **maximum over the two alignment directions**, not an aggregate of the AB direction as its name suggests:

  | row | `ipSAE_AB` | `ipSAE_BA` | `ipSAE_AB_max` | this term (`min`) |
  |---|---|---|---|---|
  | ESMFold2-Fast | 0.015362 | 0.012940 | 0.015362 | 0.012940 |
  | ESMFold2 (full) | 0.012845 | 0.010349 | 0.012845 | 0.010349 |
  | ESMFold2 (full) | 0.094172 | 0.129578 | **0.129578** | **0.094172** |

  The last row is decisive: `_max` does not equal `AB`, it equals `BA`. So the column named `_max` gives you the **larger** direction exactly where this term is defined as the **smaller** one — on that row, 0.129578 against a true 0.094172, a 38% inflation, on every design, in the permissive direction, with a plausible number and no error. It is the single easiest way to silently loosen the instrument.

  Compute `min(ipSAE_AB, ipSAE_BA)` yourself and aggregate *that* across seeds. Never read an interface term out of a `_max` column.
- **Self-consistency per arm** = structural agreement between the designed complex and that arm's prediction **at the argmax-interface-confidence seed** — not the best-agreement seed. Record both argmax seeds per arm so seed concordance is auditable. Chain mapping is the best symmetric relabeling, which applies on monomeric targets too, since chain ids may differ between designed and predicted structures.
- **Pose term** = the **minimum** over the arms that ran, passing at or above the frozen threshold (default 0.23). Because it is a minimum, it is comparable across designs only when the same arms ran for each: two arms of three reads **systematically higher** than three, so a row missing an arm's term is written NOT_RUN rather than given a minimum over what is left. Never approximate this term from the legs that did run.

  **Where `sc_DockQ` comes from — read this before you build the column.** No co-folding arm emits it. It is a *structural comparison you run yourself*: the *self-consistency* DockQ between the design's own structure and that arm's predicted complex, at the argmax-interface-confidence seed. On this platform that is the **`dockq`** tool ("Evaluate your docking interface"), submitted per arm on the two structures. `dockq` takes `.pdb`; an arm that wrote `.cif` needs converting first, and the platform does no format sniffing.

  **Do not substitute `pDockQ_*` or `pDockQ2_*`.** They are already on the arms' own result rows, they are named almost identically, and their live descriptions carry the same "above ~0.23 indicates an acceptable interface" sentence as this term's frozen threshold — so the substitution is easy, tempting, and looks right. It is the single most damaging error available on this page. `pDockQ` is a *predicted* DockQ inferred from pLDDT and PAE **in the same forward pass that produced the confidence terms**. Swapping it in replaces the campaign's only geometric check with a fourth confidence estimate correlated with the three already in the score. A design whose arms confidently agree on a wrong pose then passes every limb — which is precisely and exactly the failure the pose term exists to catch. The platform ships `dockq` and `pdockq` as two separate tools; the distinction is real and the campaign depends on it.

  If you cannot run the structural comparison, the pose limb is **NOT_RUN** — with the consequence stated below — never `pDockQ` wearing this term's name.
- **final score** = the **raw mean of the terms actually realized**. Never z-scored, never averaging a NOT_RUN term as 0. Every row names which subset it realized.
- **rank score** = the per-target weighted z-score average of those same realized terms, each confidence z-term weighted **4** and each self-consistency z-term weighted **1**. A NOT_RUN term is absent from the average, never zero.
- **z-scores are transductive** — the mean and spread depend on the scored pool, so they are comparable only within the batch that produced them, never across waves or campaigns. Record raw values and seed count on every row so any batch can be re-standardized. **Rank and select on the z-score; report the raw numbers.**

**When the pose term does not run, say what was lost, not just what is missing.** It is the only geometric check. Every remaining term is a confidence estimate from the same co-folder family, so a design whose arms confidently agree on a wrong pose — wrong epitope, flipped bundle, wrong face — is no longer caught. That is precisely the failure the pose term exists to gate. Put that sentence in the report, in user-visible text.

**Shadow metrics.** Track whole-complex confidence and interface-scoring diagnostics from the same forward pass as free diagnostics; ranking uses the interface confidence term only. On multimeric targets whole-complex confidence is inflated by native protomer-protomer interfaces and compresses design-versus-control separation.

**Templates.** No template injection in production. A template-driven prediction is a validation diagnostic only, for when no co-folder recapitulates the apo target.

## Seed tiers

- **Screen** — 1 seed per arm.
- **Intermediate and final** — **5 distinct integer seeds** per arm. Assert the seeds are distinct: a per-design standard deviation of exactly 0 across more than one seed is a bug, not a result.

**Seeds and samples are two different axes, and the arms do not default alike.** Structures per submission is `numSeeds × numSamples`, and *seed* diversity is the axis this instrument tiers on — samples are diffusion draws within one seed. **Set both explicitly on every arm.** Leaving them to defaults is how one arm quietly runs a different instrument from another, which makes a cross-arm minimum incomparable while every column still looks populated. Read each arm's own defaults with `tamarind --json schema TOOL` rather than assuming they match.

**Check that the `seed` column is actually there before relying on it.** Its schema entry warns it is conditionally present and omitted on multi-chain complex runs — and the complex *is* the ranking construct. Measured on a real two-chain ESMFold2 run, it **was** present (first column of `metrics-processed.csv`), so the warning is not the whole story and the column is often usable. Treat it as: verify on the rows in hand, per arm. Where it is missing, carry the seed yourself — submit one job per seed with the seed in the job name and join it on — because "assert the seeds are distinct" and "record both argmax seeds per arm" both need it. A campaign that cannot say which seed produced a row must say so rather than implying an audit it did not do.

## The validation check, before production scoring

Score the control panel and confirm the method separates known answers **before** any production scoring row is submitted:

- a genuine positive control, with **its chain verified against the structure's entity records**;
- several negative controls;
- a **target self-pair control** — the target scored against itself — which exists specifically to falsify target-mimic inflation. Without it, a scoring method that rewards anything shaped like the target looks like a scoring method that works;
- **exclude published de novo miniprotein binders as controls.** Their separation is circular.

Also demonstrate that the multi-seed ensemble adds ranking information over a single-seed baseline, and report the measured seed variance. Run the reduced screening instrument on the same control panel and report its rank correlation against the full instrument — that number is what quantifies the cost of every reduced tier below.

Write the verdict — PASS, PASS with a named reduction, or FAIL — to a file before proceeding. Production scoring on an unvalidated method is the failure this whole section exists to prevent, and nothing in the CLI enforces it but you.

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
