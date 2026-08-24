#!/usr/bin/env python3
"""Run the pre-scoring gates over a design pool, before any co-folding spend.

The four gates the protocol makes mandatory before a design may be scored:
liability (composition entropy, hydrophobic patches, homopolymer runs, cysteine
parity), structural plausibility (backbone geometry, steric clashes, core
packing), the target-mimic screen (TM-score against every target and control
chain), and fold class for the diversity target. Novelty's database limb is a
Tamarind job and stays in the skill; its cheap sequence-level half runs here.

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
    for entry in _load_pool(args.pool):
        did = str(entry.get("design_id") or entry.get("id") or "").strip()
        if not did:
            continue
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
        if preason or mreason:
            row["gate_not_run_reason"] = "; ".join(r for r in (preason, mreason) if r)

        for gate, verdict in (
            ("liability", lv), ("structural_plausibility", pv), ("target_mimic", mv)
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
        "structural_gates_ran": structural,
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
    # A gate that passes everything or fails everything is broken until investigated.
    for gate, tally in counts.items():
        if rows and tally.get(VERDICT_NOT_RUN, 0) == len(rows):
            print(f"  WARNING: {gate} did not run on any design - it is NOT a passed gate", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
