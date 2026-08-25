# The four pre-scoring gates

> Every threshold here is the protocol's, implemented in `_kernel/`. This page tells you what each gate is, which limbs need a Tamarind job, and how each one fails silently. It does not restate the formulas — `campaign_gates.py` computes them.

All four run **before any co-folding spend**. Cluster de novo pools at ~90% identity
first; for mutagenesis and other close-variant pools drop only exact-sequence
duplicates and let the selection caps handle diversity.

```bash
python3 "$SKILL_DIR/scripts/campaign_gates.py" pool.json \
    --reference-chains refs.json \
    --known-binders corpus/ \
    --uniref90-hits hits.json --novelty-tier final \
    --out gates.csv --rejects rejects.json
```

## 1. Novelty — four REJECT arms over five subject sets

The one gate with no second falsifier downstream, and the only one that catches a
design which is a copy of something real. Every other gate would pass ubiquitin.

**The subject sets.** UniRef90; the known-binder corpus; ubiquitin; every chain of
the campaign's own target; every chain of the controls.

**The REJECT arms.** Above 60% identity over more than 50% coverage; at or above
30% gapped local identity over at least 40 aligned columns; TM-score at or above
0.5 to any target or control chain. Ubiquitin is detected by **local alignment,
not exact match**, because the protocol observes it "often emerges with short
terminal extensions".

**The combination rule is not "all arms must run".**

| outcome | meaning |
|---|---|
| **REJECT** | any arm tripped on any subject — reported even when another subject set could not be screened. A proven copy is a copy whether or not UniRef90 was staged. |
| **NOT_RUN** | no arm tripped, but a *required* subject set was unavailable. The design is **not cleared**; the reason names the missing set. |
| **PASS** | no arm tripped and every required set was screened. |

**Two tiers, and the difference is load-bearing.** `--novelty-tier dispatch` (the
default) requires ubiquitin and the corpus — production scoring is explicitly *not*
gated on UniRef90 staging. `--novelty-tier final` adds UniRef90, which the protocol
requires **before any row reaches the ranked sheet**. Run the dispatch tier before
scoring and the final tier before the panel.

Each evidence row is stamped with the tier that produced it, and **`select_panel.py`
enforces it**: a `NOT_RUN` novelty verdict, or a `PASS` earned only at the dispatch
tier, does not rank. Without the stamp the two clearances are indistinguishable to
the sheet writer and dispatch evidence ships as final evidence. A campaign that
genuinely cannot run the search passes `--allow-novelty-not-final`, which ranks the
rows and obliges the report to say the shipped designs were never checked against
known proteins.

**What runs locally, with no job at all:** ubiquitin, the target chains, the control
chains, and the TM screen. This is most of the gate. **What needs a job:** the
UniRef90 arm only.

### Staging the subjects

- **`--reference-chains`** takes the target and control chains. The `[pdb, chain]`
  pair form feeds the structural TM screen only; the object form
  `{"pdb":…, "chain":…, "sequence":…, "role":"target"|"control"}` also feeds the
  sequence arm. **A reference with no sequence leaves that arm NOT_RUN** — the
  sequence is deliberately not inferred from the PDB, because a mis-parsed
  reference is a gate pointed at the wrong molecule.
- **`--known-binders`** takes a FASTA/CSV/TSV or a directory of them (or
  `$CAMPAIGN_KNOWN_BINDER_CORPUS`). **Until it is staged, a clean design is NOT_RUN
  rather than PASS**, because a corpus of zero subjects would clear every design
  against nothing. The protocol stages this in the first hour; do the same.

  **It does not scale to a campaign-size pool, and the run refuses rather than
  crawling.** The in-process aligner is O(pool x corpus) — measured at ~0.5 ms per
  local alignment, the protocol's own ~16,500-entry corpus against a 20,000-design
  pool is ~330M alignments, roughly **46 hours single-core** on a campaign with a
  24-hour clock. The kernel's cap compares only the corpus size, so it never fires
  on that shape; the wrapper checks `pool x corpus` up front and refuses with the
  arithmetic. Above the cap, search the pool against the corpus **once** with
  MMseqs2 and pass the rows to **`--known-binder-hits`** instead — same shape as
  `--uniref90-hits`. Supply one or the other, never both: the arm would run twice
  against different subject sets and the row could not say which produced its
  verdict.
- **`--uniref90-hits`** takes `{design_id: [hit, …]}` from a sequence-identity
  search job, with the search's own columns — `identity`/`fident`/`pident` and
  `coverage`/`qcov`/`cov`. Percentages and fractions are disambiguated by value;
  exactly `1` is read as a **fraction**, the reading that rejects, because a novelty
  ban's failure direction is to let a copy through.

**A malformed hits file refuses the run rather than degrading a row.** Measured
while wiring this up: hits named `gapped_identity`/`query_coverage` raised *inside*
the verdict, after the corpus arm had already rejected the design — and the per-row
catch turned that raise into NOT_RUN, taking the standing REJECT with it. A bad
input file must never be able to loosen a gate, so the file is judged once at
startup.

**The escape this closes, measured.** A generator returned a 75-residue "de novo
design" whose first 40 residues were human ubiquitin's exactly. It passed liability
cleanly — ubiquitin is a perfectly well-behaved protein — and only a novelty search
sees it. It is now REJECT locally, at 1.0 gapped identity over 40 columns.

## 2. Liability — composition

Cysteine parity, homopolymer runs, surface hydrophobic patches, windowed
composition entropy. Runs locally on the sequence alone.

**`lcp_score` rides alongside it.** Local Composition Perplexity is the protocol's
*mandatory* sequence-design restraint against homopolymer stretches, ported from
Chroma's implementation. It is **recorded, never a gate** — the protocol makes it a
restraint on sequence *design* and a reported metric, not a rejection threshold.
Higher is worse. Use it to steer sequence design and to break ties, and report it
on every ranked row.

## 3. Monomer foldability — needs a job

The binder alone, mean pLDDT at or above the frozen floor (default **0.70** on the
0–1 scale, 70 on 0–100). `campaign_gates.py` writes NOT_RUN with a reason; run a
binder-alone fold and join the result onto the row.

**Join BOTH fields, or the sheet halts.** Adding `monomer_plddt` alone leaves
`monomer_foldability_verdict` at the `NOT_RUN` that `campaign_gates.py` wrote, and
`select_panel.py` then recomputes the verdict from that pLDDT and halts on the
disagreement — after a below-floor design has already travelled through the score
algebra instead of being filtered before it. Write the measurement **and** the
thresholded verdict together, against the same frozen floor:

```python
row["monomer_plddt"] = plddt                       # on the floor's own scale
row["monomer_foldability_verdict"] = "PASS" if plddt >= floor else "REJECT"
```

**The arms disagree on the scale and that is where this bites.** Measured on real
rows for the same construct, ESMFold2 reports mean pLDDT on **0–1** (0.7884) and
Protenix on **0–100** (86.75). A Protenix-derived pLDDT compared against a 0–1 floor
clears for **every design** — the gate keeps reporting PASS while rejecting nothing,
which is worse than not running it. Fix the column, not the floor, and record which
convention the frozen floor is written in.

## 4. Structural plausibility

Backbone geometry, steric clashes, core packing, at thresholds you choose at kickoff
and freeze. Runs locally from the designed structure; needs `numpy`.

## The discipline that makes any of it count

**Record every rejected design_id and verify its absence from every downstream
pool.** A gate counts as run only when its rejects are traceably absent downstream —
that is what `--rejects` is for. Re-run the liability, monomer-foldability and
novelty checks once more before finalizing the sheet.

**A gate that passes everything, fails everything, or returns a constant is broken
until investigated.** `campaign_gates.py` warns on all three. The one legitimate
all-NOT_RUN column is monomer foldability, which cannot run here; novelty lost that
exemption when it started running.

**Provenance keys are assigned at backbone-generation time and propagate unchanged.**
`root_backbone_id` — one id per de novo backbone, shared by every derived sequence
and every partial-diffusion variant — and `structure_method` and `seq_method`, which
are **tokens from the campaign's frozen method vocabulary, not free text**. A row
whose token is absent from the enum is rejected rather than admitted under a new
name.
