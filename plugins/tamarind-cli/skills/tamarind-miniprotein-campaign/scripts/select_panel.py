#!/usr/bin/env python3
"""Score, cap, rank and recompute the final design panel -- the deliverable.

Three things happen here, in this order, and the order is load-bearing:

1. THE GATE. Production scoring is blocked until the validation check on
   known-answer controls has PASSED. This script refuses to emit a panel
   without that artifact. On the campaign harness the refusal lives in the
   scoring-batch builder; here it lives in this script, which is why the panel
   must be produced by running it rather than by assembling rows by hand.
2. THE ALGEBRA. final_score is the RAW mean of the realized terms; rank_zscore
   is the 4:1-weighted z-average of the same terms; z-scores are transductive,
   so they are comparable only within this batch. A term an arm did not produce
   is None -- never 0, never averaged in.
3. THE CAPS, then the RECOMPUTE. Selection applies the diversity caps and the
   relaxation ladder (one rung per call), then every gate that ran is recomputed
   from the row's own sequence and structure and matched to 1e-4. A mismatch
   HALTS, naming the row, because a row whose gates cannot be reproduced is not
   a row you can ship.

Formulas come from the vendored kernel (_kernel/VENDORED.md), never from here.

Usage:
  python3 select_panel.py candidates.json --gate gate.json --out design_sheet.csv
  python3 select_panel.py candidates.json --gate gate.json --panel-size 30 --json
  python3 select_panel.py candidates.json --gate gate.json --max-relaxation-rung 2

`candidates.json` is a list of rows carrying design_id, sequence, provenance
(root_backbone_id, parent_design_id, opt_round, structure_method, seq_method),
the per-arm term columns, and the gate evidence written by campaign_gates.py.
`--gate` is the validation-check artifact; its `status` must be PASS or
PASS_REDUCED.
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GATE_OK = ("PASS", "PASS_REDUCED")
IPSAE_PREFIX = "ipsae_"
SCDOCKQ_PREFIX = "sc_DockQ_"


def _load_rows(path):
    with open(path) as fh:
        if path.lower().endswith(".csv"):
            return list(csv.DictReader(fh))
        data = json.load(fh)
    for key in ("candidates", "designs", "rows", "items"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    if isinstance(data, list):
        return data
    raise SystemExit(f"{path}: expected a list of candidate rows")


def _check_gate(path):
    """Fail closed. No artifact, or a non-PASS one, and nothing is emitted."""
    if not path:
        raise SystemExit(
            "refusing to build a panel: --gate is required.\n"
            "The validation check on known-answer controls must PASS before any\n"
            "production scoring row is ranked. Run it, write the verdict, then retry."
        )
    if not os.path.exists(path):
        raise SystemExit(f"refusing to build a panel: gate artifact not found at {path}")
    with open(path) as fh:
        gate = json.load(fh)
    status = str(gate.get("status") or "").strip().upper()
    if status not in GATE_OK:
        raise SystemExit(
            f"refusing to build a panel: gate status is {status or 'MISSING'}, not PASS.\n"
            "This is the check that the scoring separates known binders from non-binders\n"
            "on this target. Do not edit the artifact to get past this."
        )
    return gate


def _num(value):
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def _term_matrix(rows, prefix):
    """`[design][term]` -- the orientation the kernel's algebra requires.

    NOT `[arm][design]`. The kernel validates only that the matrix is
    rectangular, so a transposed input with as many arms as designs is accepted
    and silently scores every design against the wrong terms. Build it per
    design, in one stable arm order, and never by zipping columns.
    """
    names = sorted({k for r in rows for k in r if k.startswith(prefix)})
    return names, [[_num(row.get(n)) for n in names] for row in rows]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidates")
    ap.add_argument("--gate", help="validation-check artifact; status must be PASS")
    ap.add_argument("--panel-size", type=int, default=30)
    ap.add_argument("--max-relaxation-rung", type=int, default=1)
    ap.add_argument("--out", help="write the design sheet here")
    ap.add_argument("--trace", help="write the cap/rejection/relaxation trace here")
    ap.add_argument("--skip-recompute", action="store_true",
                    help="emit the panel without the write-time gate recompute; DISCLOSE this")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    gate = _check_gate(args.gate)
    rows = _load_rows(args.candidates)
    if not rows:
        raise SystemExit("no candidate rows")

    try:
        from _kernel import qa_analysis_helpers as helpers
        from _kernel import qa_selection_helpers as selection
    except ImportError as exc:
        raise SystemExit(f"vendored kernel unavailable: {exc}")

    ipsae_names, ipsae_terms = _term_matrix(rows, IPSAE_PREFIX)
    dockq_names, dockq_terms = _term_matrix(rows, SCDOCKQ_PREFIX)
    if not ipsae_names:
        raise SystemExit(
            f"no {IPSAE_PREFIX}* columns on the candidate rows: there is nothing to rank.\n"
            "Every co-folding stage runs all three arms; a pool with no interface-confidence\n"
            "terms has not been scored."
        )

    final = helpers.final_score_from_terms(ipsae_terms, dockq_terms)
    rank_z = helpers.rank_zscore_from_terms(ipsae_terms, dockq_terms)
    realized = list(ipsae_names) + list(dockq_names)
    for row, fs, rz in zip(rows, final, rank_z):
        row["final_score"] = fs
        row["rank_zscore"] = rz
        row["score_instrument"] = ",".join(realized)

    # The sheet's column names and the selector's input names differ in one
    # place: the sheet writes `tm90_cluster_id`, the selector reads `tm_cluster`.
    # Alias rather than rename, so the shipped sheet keeps the protocol's column
    # name and the selector still sees the cluster. A row with neither is
    # refused as missing provenance -- absence of a cluster is not a pass.
    for row in rows:
        if not row.get("tm_cluster") and row.get("tm90_cluster_id"):
            row["tm_cluster"] = row["tm90_cluster_id"]

    result = selection.select_with_diversity_caps(
        rows, panel_size=args.panel_size, max_relaxation_rung=args.max_relaxation_rung
    )
    panel = result.get("panel") or result.get("selected") or []

    # Rank key: full seed tier first, then pose pass, then rank z-score. A pose
    # term that is NOT_RUN on every row is a constant and sorts as one -- it is
    # never coerced to true or false.
    def key(row):
        seeds = _num(row.get("n_seeds"))
        seeds = 0.0 if seeds is None else seeds
        pose = str(row.get("pose_PASS") or "").strip().upper()
        pose_rank = 1 if pose == "TRUE" else 0
        z = _num(row.get("rank_zscore"))
        # A z-score of exactly 0.0 is a real value; `or` would demote it to the
        # bottom alongside rows that have no score at all.
        z = float("-inf") if z is None else z
        return (-(1 if seeds >= 5 else 0), -pose_rank, -z)

    panel = sorted(panel, key=key)
    for i, row in enumerate(panel, 1):
        row["rank"] = i

    recompute = {"ran": False}
    if not args.skip_recompute and panel:
        from _kernel import sheet_recompute as sr
        report = sr.liability_recompute(panel)
        recompute = {"ran": True, "liability": report}
        mismatches = report.get("mismatches") or []
        if mismatches:
            ids = ", ".join(str(m.get("design_id") or m) for m in mismatches[:5])
            raise SystemExit(
                f"HALTED: {len(mismatches)} row(s) carry liability numbers that do not "
                f"reproduce from their own sequence to 1e-4 (first: {ids}).\n"
                "Do not ship a row whose gates you could not reproduce."
            )

    if args.out and panel:
        cols, seen = [], set()
        for r in panel:
            for k in r:
                if k not in seen:
                    seen.add(k)
                    cols.append(k)
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(panel)
    if args.trace:
        with open(args.trace, "w") as fh:
            json.dump({k: v for k, v in result.items() if k != "panel"}, fh, indent=2, default=str)

    # Why rows did not make it matters more than the count. A panel emptied by
    # `missing tm_cluster` is a pipeline gap; one emptied by the diversity caps
    # is an under-diverse pool. They have opposite repairs.
    summary = {
        "gate_status": gate.get("status"),
        "candidates": len(rows),
        "panel_size_requested": args.panel_size,
        "panel_size_shipped": len(panel),
        "short_of_request": max(0, args.panel_size - len(panel)),
        "realized_terms": realized,
        "rejection_counts": result.get("rejection_counts") or {},
        "target_mimic_not_run": len(result.get("target_mimic_not_run") or []),
        "distinct_structure_methods": result.get("distinct_structure_methods"),
        "campaign_failure": bool(result.get("campaign_failure")),
        "relaxations_applied": result.get("relaxations_applied") or [],
        "relaxation_rung": result.get("relaxation_rung"),
        "recompute": recompute,
        "design_sheet": args.out,
    }
    if args.json:
        json.dump(summary, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print(f"gate {summary['gate_status']}; {len(rows)} candidates -> {len(panel)} shipped")
        print(f"  realized terms: {', '.join(realized) or 'none'}")
        for cap, n in sorted(summary["rejection_counts"].items(), key=lambda kv: -kv[1]):
            print(f"  rejected by {cap}: {n}")
        if summary["target_mimic_not_run"]:
            print(f"  {summary['target_mimic_not_run']} row(s) carry NO mimic verdict - absence is not a pass")
        if summary["relaxations_applied"]:
            print(f"  relaxed: {', '.join(summary['relaxations_applied'])} - disclose every one")
        if summary["short_of_request"]:
            print(f"  SHORT by {summary['short_of_request']} - fix upstream; ship the real N, never pad")
        print(f"  gate recompute: {'ran' if recompute['ran'] else 'SKIPPED - disclose this'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
