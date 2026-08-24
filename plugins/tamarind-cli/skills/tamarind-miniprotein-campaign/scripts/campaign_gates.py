#!/usr/bin/env python3
"""Run the pre-scoring gates over a design pool, before any co-folding spend.

What runs HERE, on the host, at zero co-folding cost: liability (composition
entropy, hydrophobic patches, homopolymer runs, cysteine parity), structural
plausibility (backbone geometry, steric clashes, core packing), the target-mimic
screen (TM-score against every target and control chain), and fold class for the
diversity target.

Two mandatory gates CANNOT run here, and this script says so on every row rather
than leaving them absent: monomer foldability needs a binder-alone fold, and the
database limb of novelty needs a sequence-identity search. Both are Tamarind
jobs. They are emitted as NOT_RUN with a reason, because an absent column reads
downstream exactly like a gate that ran and found nothing.

Every gate emits its own NUMBERS, not just a verdict, because the sheet writer
recomputes each one and matches to 1e-4 -- a verdict with no numbers beside it
is unfalsifiable. A gate that could not run emits NOT_RUN with empty evidence
cells, never a zero and never a plausible-looking number.

The formulas come from the vendored kernel (see _kernel/VENDORED.md), not from
this file. Re-deriving them by hand is the defect this script exists to prevent.

Usage:
  python3 campaign_gates.py pool.json --out gates.csv --rejects rejects.json
  python3 campaign_gates.py pool.json --reference-chains refs.json --out gates.csv
  python3 campaign_gates.py pool.json --json

Pool is a JSON list (or CSV) of objects carrying at least `design_id` and
`sequence`; `designed_structure_path` and `binder_chain` enable the structural
gates. `--reference-chains` is a JSON list of [pdb_path, chain] pairs: every
target chain and every control chain.
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERDICT_PASS = "PASS"
VERDICT_REJECT = "REJECT"
VERDICT_NOT_RUN = "NOT_RUN"

# Mirrors the panel selector's alphabet and length policy, applied one stage
# EARLIER and for a sharper reason: the ledger records only literal gate
# REJECTs, so a malformed design is reported as SCREENED with no entry keeping
# it out -- and it reaches paid folding before the selector ever sees it. The
# liability helper would meanwhile strip `results/design1.pdb` to
# RESULTSDESIGNPDB and hand it a PASS.
AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWYXBZJUO")
BINDER_LEN_MIN, BINDER_LEN_MAX = 35, 160


def _load_pool(path):
    with open(path) as fh:
        if path.lower().endswith((".csv", ".tsv")):
            delim = "\t" if path.lower().endswith(".tsv") else ","
            return list(csv.DictReader(fh, delimiter=delim))
        data = json.load(fh)
    for key in ("designs", "pool", "rows", "items"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    if isinstance(data, list):
        return data
    raise SystemExit(f"{path}: expected a list of designs or an object carrying one")


def _liability(helpers, seq):
    """Composition gate. Returns (verdict, evidence) with the numbers that decided it."""
    if not seq:
        return VERDICT_NOT_RUN, {}
    flags = helpers.composition_liability_flags(seq)
    ev = {
        "liability_min_window_entropy_bits": flags.get("min_window_entropy_bits"),
        "liability_max_hydrophobic_patch_fraction": flags.get("max_hydrophobic_patch_fraction"),
        "liability_max_homopolymer_run": (flags.get("homopolymer") or {}).get("longest_run"),
        "liability_cys_parity": (flags.get("cys_parity") or {}).get("parity"),
    }
    return (VERDICT_REJECT if flags.get("flagged") else VERDICT_PASS), ev


def _plausibility(sp, pdb, chain):
    if not pdb or not os.path.exists(pdb):
        return VERDICT_NOT_RUN, {}, "no designed structure on this row"
    try:
        result = sp.structural_plausibility_verdict(pdb, chain)
    except Exception as exc:  # the kernel raises rather than guessing a chain
        return VERDICT_NOT_RUN, {}, f"{type(exc).__name__}: {exc}"
    ev = {
        f"plausibility_{k.split('.', 1)[-1]}": v
        for k, v in (result.get("measurements") or {}).items()
    }
    return result.get("verdict", VERDICT_NOT_RUN), ev, result.get("reason") or ""


def _mimic(tm, pdb, refs, chain):
    if not refs:
        return VERDICT_NOT_RUN, {}, "no reference chains supplied"
    if not pdb or not os.path.exists(pdb):
        return VERDICT_NOT_RUN, {}, "no designed structure on this row"
    try:
        screen = tm.target_mimic_screen(pdb, refs, design_chain=chain)
    except Exception as exc:
        return VERDICT_NOT_RUN, {}, f"{type(exc).__name__}: {exc}"
    return screen.get("verdict", VERDICT_NOT_RUN), {"target_mimic_tm_max": screen.get("tm_max")}, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pool", help="JSON or CSV design pool")
    ap.add_argument("--reference-chains", help='JSON list of [pdb, chain] pairs (targets + controls)')
    ap.add_argument("--out", help="write the per-design evidence CSV here")
    ap.add_argument("--rejects", help="write the rejected-design ledger here")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = ap.parse_args()

    try:
        from _kernel import qa_analysis_helpers as helpers
    except ImportError as exc:
        raise SystemExit(f"vendored kernel unavailable: {exc}")
    try:
        from _kernel import qa_tm_helpers as tm, structure_plausibility as sp
        structural = True
    except ImportError:
        # numpy is the only reason these two fail. An honest NOT_RUN on every
        # structural gate beats a campaign that silently skips them.
        tm = sp = None
        structural = False

    refs = []
    if args.reference_chains:
        with open(args.reference_chains) as fh:
            refs = [tuple(pair) for pair in json.load(fh)]

    rows, rejects, counts = [], [], {}
    pool = _load_pool(args.pool)
    # A silently dropped row is an ungated design with no ledger entry proving
    # it stayed out -- indistinguishable downstream from one that passed. Name
    # the offender and refuse the pool.
    # An empty pool exits 0 and names a gates.csv nobody wrote, so the stage
    # reads as successful and whatever runs next fails on the missing file. It
    # also means no constant-gate warning can fire, because there is nothing to
    # be constant over.
    if not pool:
        raise SystemExit(
            "refusing an empty pool: nothing to screen.\n"
            "An empty gate stage cannot be distinguished from one that ran and rejected\n"
            "everything. Fix the generation or the join upstream."
        )
    nameless = [i for i, e in enumerate(pool)
                if not str(e.get("design_id") or e.get("id") or "").strip()]
    if nameless:
        shown = ", ".join(str(i) for i in nameless[:5])
        raise SystemExit(
            f"refusing the pool: {len(nameless)} row(s) carry no design_id or id "
            f"(first at index {shown}).\n"
            "A row with no durable identifier cannot be tracked into or out of a gate."
        )
    # A multi-row pool in which every design carries the SAME sequence is not a
    # design pool. The way this happens is measured, not hypothetical: a
    # generator writes the binder and the target joined in one field, and the
    # split takes the wrong half -- so every row becomes the target. RFdiffusion
    # ships exactly that shape, and its own schema documents the two chains in
    # the opposite order from the one it delivers, so following the
    # documentation produces this pool. The target is of legal length and
    # ordinary composition, so every other check here passes it.
    #
    # Fires ONLY on a pool that is otherwise perfectly well formed. A row with
    # no id, a duplicate id, a missing sequence or an illegal length has its own
    # refusal that says more, and those must win -- otherwise a two-row pool
    # where one row simply lacks a sequence gets reported as a chain-split bug.
    _seqs = [str(e.get("sequence") or "").strip().upper() for e in pool]
    _ids = [str(e.get("design_id") or e.get("id") or "").strip() for e in pool]
    well_formed = (
        all(_seqs) and all(_ids) and len(set(_ids)) == len(_ids)
        and all(BINDER_LEN_MIN <= len(s) <= BINDER_LEN_MAX for s in _seqs)
    )
    if len(pool) > 1 and well_formed and len(set(_seqs)) == 1:
        only = _seqs[0]
        raise SystemExit(
            f"refusing the pool: all {len(pool)} designs carry an identical "
            f"{len(only)}-residue sequence.\n"
            "  A pool of one repeated sequence is not a design pool. The usual cause "
            "is a joined\n"
            "  sequence field (binder and target in one string) split on the wrong "
            "side -- every row\n"
            "  is then the TARGET, which is of legal length and passes every other "
            "check here.\n"
            "  Identify the binder by excluding your frozen target sequence and "
            "asserting the\n"
            "  designed length, not by taking a fixed position in the split."
        )

    seen = set()
    for entry in pool:
        did = str(entry.get("design_id") or entry.get("id") or "").strip()
        if did in seen:
            raise SystemExit(f"refusing the pool: duplicate design_id {did!r}")
        seen.add(did)
        # No sequence means liability cannot run, and the ledger records only
        # REJECT -- so the row is reported as screened with no rejection entry,
        # and a downstream pool built by removing ledger ids carries it into
        # paid folding ungated. Fail closed, like a missing id.
        seq = str(entry.get("sequence") or "").strip().upper()
        if not seq:
            raise SystemExit(
                f"refusing the pool: design {did!r} carries no sequence.\n"
                "Liability cannot run on it, and a row that is neither gated nor "
                "rejected is one nothing downstream can keep out."
            )
        offenders = sorted({ch for ch in seq if ch not in AMINO_ACIDS})
        if offenders:
            raise SystemExit(
                f"refusing the pool: design {did!r} has non-residue characters "
                f"{''.join(offenders)!r} in its sequence.\n"
                "The liability helper would strip these and score whatever letters remain,\n"
                "so the row would be reported as screened and reach paid folding."
            )
        if not BINDER_LEN_MIN <= len(seq) <= BINDER_LEN_MAX:
            raise SystemExit(
                f"refusing the pool: design {did!r} is {len(seq)} residues, outside the "
                f"frozen {BINDER_LEN_MIN}-{BINDER_LEN_MAX} policy.\n"
                "Gating it would spend co-folding compute on a design the selector refuses."
            )
        pdb = entry.get("designed_structure_path") or entry.get("structure_path")
        chain = entry.get("binder_chain")
        row = {"design_id": did}

        lv, lev = _liability(helpers, entry.get("sequence"))
        row["liability_verdict"] = lv
        row.update(lev)

        if structural:
            pv, pev, preason = _plausibility(sp, pdb, chain)
            mv, mev, mreason = _mimic(tm, pdb, refs, chain)
        else:
            pv, pev, preason = VERDICT_NOT_RUN, {}, "numpy unavailable in this environment"
            mv, mev, mreason = VERDICT_NOT_RUN, {}, "numpy unavailable in this environment"
        row["structural_plausibility_verdict"] = pv
        row.update(pev)
        row["target_mimic_verdict"] = mv
        row.update(mev)

        # Fold class feeds the >=10% non-all-alpha diversity target. Reported,
        # never a ranking gate.
        if pdb and os.path.exists(pdb):
            try:
                fold = helpers.dssp_fold_class(pdb, chain=chain)
                label = getattr(fold, "fold_class", None) or getattr(fold, "label", None)
                helical = getattr(fold, "helical_fraction", None)
                # The kernel does NOT raise when it cannot classify -- it hands
                # back a FoldClass whose `.fold_class` is None and whose str()
                # is "unknown". Falling through to str(fold) minted a fourth
                # token beside PASS/REJECT/NOT_RUN, carrying no reason, which
                # `references/selection.md` forbids. An unclassifiable fold is
                # a gate that did not run, and it has to say why.
                if not label or str(label).strip().lower() == "unknown":
                    row["fold_class"] = VERDICT_NOT_RUN
                    row["fold_class_not_run_reason"] = (
                        "the fold classifier returned no class for this structure "
                        "(no secondary structure resolved on the designed chain)"
                    )
                else:
                    row["fold_class"] = label
                if helical is not None:
                    row["fold_helical_fraction"] = helical
            except Exception as exc:
                row["fold_class"] = VERDICT_NOT_RUN
                row["fold_class_not_run_reason"] = f"{type(exc).__name__}: {exc}"
        else:
            row["fold_class"] = VERDICT_NOT_RUN
            row["fold_class_not_run_reason"] = "no designed structure on this row"

        # The two gates this script cannot run. Written explicitly: an absent
        # column reads downstream exactly like a gate that ran and passed.
        row["monomer_foldability_verdict"] = VERDICT_NOT_RUN
        row["monomer_foldability_not_run_reason"] = (
            "needs a binder-alone fold job; run it and join monomer_plddt onto the row"
        )
        row["novelty_verdict"] = VERDICT_NOT_RUN
        row["novelty_not_run_reason"] = (
            "needs a sequence-identity search job; run it on the survivors and join the verdict"
        )

        # Route each reason by ITS OWN verdict. The kernel returns a `reason`
        # for any outcome, so folding them together wrote REJECT rationales
        # into a column named `_not_run_reason` -- and a consumer filtering on
        # "this column is non-empty" then counted refused designs as gates that
        # never ran, which is the exact confusion every NOT_RUN here exists to
        # prevent.
        not_run, rejected_because = [], []
        for verdict, reason in ((pv, preason), (mv, mreason)):
            if not reason:
                continue
            (not_run if verdict == VERDICT_NOT_RUN else rejected_because).append(reason)
        if not_run:
            row["gate_not_run_reason"] = "; ".join(not_run)
        if rejected_because:
            row["gate_reject_reason"] = "; ".join(rejected_because)

        for gate, verdict in (
            ("liability", lv), ("structural_plausibility", pv), ("target_mimic", mv),
            ("monomer_foldability", VERDICT_NOT_RUN), ("novelty", VERDICT_NOT_RUN),
        ):
            counts.setdefault(gate, {}).setdefault(verdict, 0)
            counts[gate][verdict] += 1
            if verdict == VERDICT_REJECT:
                rejects.append({"design_id": did, "gate": gate})
        rows.append(row)

    if args.out and rows:
        cols, seen = [], set()
        for r in rows:
            for k in r:
                if k not in seen:
                    seen.add(k)
                    cols.append(k)
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    if args.rejects:
        with open(args.rejects, "w") as fh:
            json.dump({"rejected": rejects}, fh, indent=2)

    rejected_ids = sorted({r["design_id"] for r in rejects})
    summary = {
        "screened": len(rows),
        "rejected": len(rejected_ids),
        "rejected_design_ids": rejected_ids,
        "verdict_counts": counts,
        # Availability and execution are different claims. numpy importing says
        # nothing about whether any row had a structure to screen, and a JSON
        # consumer that reads one as the other treats a zero-row structural
        # screen as a completed one.
        "structural_gates_available": structural,
        "structural_gates_evaluated": {
            gate: sum(n for verdict, n in (counts.get(gate) or {}).items()
                      if verdict != VERDICT_NOT_RUN)
            for gate in ("structural_plausibility", "target_mimic")
        },
        "evidence_csv": args.out,
        "rejects_ledger": args.rejects,
    }
    if args.json:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"screened {summary['screened']} designs, {summary['rejected']} rejected")
        for gate, tally in counts.items():
            print(f"  {gate}: " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
        if not structural:
            print("  NOTE: numpy unavailable - plausibility and mimic gates are NOT_RUN, not passed")
    # A gate that passes everything, fails everything, or returns a constant is
    # broken until investigated -- all three, not just the un-run case. The
    # job-borne gates are legitimately all-NOT_RUN here, so they are exempt from
    # that one arm and named as such in the row.
    always_not_run = {"monomer_foldability", "novelty"}
    for gate, tally in counts.items():
        if not rows:
            break
        if tally.get(VERDICT_NOT_RUN, 0) == len(rows) and gate not in always_not_run:
            print(f"  WARNING: {gate} did not run on any design - it is NOT a passed gate",
                  file=sys.stderr)
        elif tally.get(VERDICT_PASS, 0) == len(rows):
            print(f"  WARNING: {gate} passed every one of {len(rows)} designs - "
                  "a constant gate is broken until investigated", file=sys.stderr)
        elif tally.get(VERDICT_REJECT, 0) == len(rows):
            print(f"  WARNING: {gate} rejected every one of {len(rows)} designs - "
                  "a constant gate is broken until investigated", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
