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

# Columns that share a score prefix but carry provenance, not a measurement.
# `ipsae_mask` is the one that bites: every scored row is REQUIRED to carry it,
# it is a string, and swept into the algebra it parses to None and makes the
# whole row ineligible -- so a correctly-stamped campaign scores nothing.
# Suffix-matched as well, so a future `*_tool` / `*_job` / `*_path` stamp under
# either prefix cannot silently become a seventh term.
NON_TERM_SUFFIXES = ("_mask", "_stamp", "_tool", "_job", "_path", "_reason", "_status")

# The residue alphabet a shipped sequence must be drawn from, in full. A value
# outside it is refused rather than salvaged: the kernel's normalizer strips
# punctuation and digits, so `results/design1.pdb` would otherwise survive as
# `RESULTSDESIGNPDB` and ship as a protein.
AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWYXBZJUO")


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
    # A bare {"status": "PASS"} is a word, not a verdict. The artifact has to
    # carry what was measured and what it was measured on, or a truncated or
    # hand-authored file unlocks ranking with no auditable evidence that the
    # scoring was ever validated.
    if _num(gate.get("separation")) is None:
        raise SystemExit(
            "refusing to build a panel: the gate artifact carries no numeric `separation`.\n"
            "PASS has to say what separated the controls, not merely that something did."
        )
    controls = gate.get("controls") or []
    if not isinstance(controls, (list, tuple)) or len(controls) < 2:
        raise SystemExit(
            "refusing to build a panel: the gate artifact names fewer than two `controls`.\n"
            "The check needs a positive control and at least one negative; a target-self-pair\n"
            "control belongs there too, since it is what falsifies target-mimic inflation."
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

    Only real per-arm metric columns count as terms; see NON_TERM_SUFFIXES.
    """
    names = sorted(
        k
        for k in {k for r in rows for k in r}
        if k.startswith(prefix) and not k.endswith(NON_TERM_SUFFIXES)
    )
    return names, [[_num(row.get(n)) for n in names] for row in rows]


def _bad_sequence(value):
    """Reason this is not a protein sequence, or None if it is one."""
    seq = "" if value is None else str(value).strip().upper()
    if not seq:
        return "empty sequence"
    offenders = sorted({ch for ch in seq if ch not in AMINO_ACIDS})
    if offenders:
        return f"non-residue characters {''.join(offenders)!r} in sequence"
    return None


def _bad_lineage(row):
    """Reason this row's optimization lineage does not close, or None.

    The per-root cap is counted on `root_backbone_id`, so a child that mints a
    fresh root escapes it while looking like ordinary provenance. Round 0 is de
    novo and cannot claim a parent.
    """
    raw = row.get("opt_round")
    if raw is None or str(raw).strip() == "":
        return "opt_round is blank (round 0 is de novo, and it still has to say so)"
    try:
        rnd = int(str(raw).strip())
    except ValueError:
        return f"opt_round {raw!r} is not a whole number"
    if rnd < 0:
        return f"opt_round {rnd} is negative"
    parent = str(row.get("parent_design_id") or "").strip()
    if rnd == 0 and parent:
        return "a round-0 design claims a parent, but round 0 is de novo"
    if rnd > 0 and not parent:
        return f"opt_round {rnd} carries no parent_design_id"
    if parent and parent == str(row.get("design_id") or "").strip():
        return "design is its own parent"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidates")
    ap.add_argument("--gate", help="validation-check artifact; status must be PASS")
    ap.add_argument("--panel-size", type=int, default=30)
    ap.add_argument("--max-relaxation-rung", type=int, default=1)
    ap.add_argument("--monomer-floor", type=float, default=0.70,
                    help="frozen binder-alone mean-pLDDT floor, on the scale the arm emits")
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

    # Refuse rows the algebra could not score, and rows whose sequence or
    # lineage is malformed, BEFORE selection. The protocol reserves the unranked
    # section for rows with missing scores and never relaxes a non-null
    # final_score, so a null-score row that lands in the panel is a ranked row
    # asserting a measurement nobody made.
    ranked, unranked = [], []
    for row in rows:
        reason = None
        if row.get("final_score") is None:
            reason = "final_score is null: a realized term is missing or unparseable"
        elif _bad_sequence(row.get("sequence")):
            reason = _bad_sequence(row.get("sequence"))
        elif _bad_lineage(row):
            reason = _bad_lineage(row)
        if reason:
            row["unranked_reason"] = reason
            unranked.append(row)
        else:
            ranked.append(row)

    # The sheet's column names and the selector's input names differ in one
    # place: the sheet writes `tm90_cluster_id`, the selector reads `tm_cluster`.
    # Alias rather than rename, so the shipped sheet keeps the protocol's column
    # name and the selector still sees the cluster. A row with neither is
    # refused as missing provenance -- absence of a cluster is not a pass.
    for row in ranked:
        if not row.get("tm_cluster") and row.get("tm90_cluster_id"):
            row["tm_cluster"] = row["tm90_cluster_id"]

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

    # Sort BEFORE the caps, not after. The selector admits greedily in input
    # order, so an unsorted pool lets a low-scoring row consume a cap that a
    # better row then cannot use -- and sorting the finished panel cannot
    # recover a candidate the caps already excluded.
    ranked.sort(key=key)

    result = selection.select_with_diversity_caps(
        ranked, panel_size=args.panel_size, max_relaxation_rung=args.max_relaxation_rung
    )
    panel = result.get("selected") or result.get("panel") or []
    panel = sorted(panel, key=key)
    for i, row in enumerate(panel, 1):
        row["rank"] = i

    recompute = {"ran": False, "gates": {}, "skipped": []}
    if not args.skip_recompute and panel:
        try:
            from _kernel import sheet_recompute as sr
        except ImportError as exc:
            # sheet_recompute pulls in structure_plausibility, which needs numpy.
            # Degrade to a named, disclosed skip rather than crashing the run or
            # forcing the caller to discover --skip-recompute.
            recompute = {
                "ran": False,
                "gates": {},
                "skipped": [f"every gate: {exc}"],
                "reason": "recompute unavailable in this environment",
            }
            sr = None
        if sr is not None:
            reports = {"liability": sr.liability_recompute(panel)}

            # Plausibility reproduces only where the row names the structure it
            # was measured on and the chain within it. Rows that name neither
            # are recorded as not-recomputable, never as reproduced.
            structures = {
                str(r.get("design_id")): r.get("designed_structure_path")
                for r in panel
                if r.get("designed_structure_path")
            }
            chains = {
                str(r.get("design_id")): r.get("binder_chain")
                for r in panel
                if r.get("binder_chain")
            }
            if structures and chains:
                try:
                    reports["plausibility"] = sr.plausibility_recompute(
                        panel, structures, chain_by_design_id=chains
                    )
                except Exception as exc:
                    recompute["skipped"].append(f"plausibility: {exc}")
            else:
                recompute["skipped"].append(
                    "plausibility: no row names both a designed structure and its binder chain"
                )

            # Monomer foldability reproduces against the per-design pLDDT the
            # binder-alone fold produced. Absent that column there is nothing to
            # check against, which is a disclosed skip and not a pass.
            plddt = {
                str(r.get("design_id")): _num(r.get("monomer_plddt"))
                for r in panel
                if _num(r.get("monomer_plddt")) is not None
            }
            if plddt:
                try:
                    reports["monomer"] = sr.monomer_recompute(
                        panel, plddt, floor=args.monomer_floor
                    )
                except Exception as exc:
                    recompute["skipped"].append(f"monomer: {exc}")
            else:
                recompute["skipped"].append("monomer: no row carries monomer_plddt")

            # Novelty needs the known-binder corpus and the reference chains,
            # which are deployment inputs the campaign stages out of band.
            recompute["skipped"].append(
                "novelty: needs the known-binder corpus and reference chains, "
                "which are campaign deployment inputs rather than sheet columns"
            )

            recompute["ran"] = True
            # `recomputed` is the list of GATE NAMES the report covered, not a
            # row count -- read rows_checked for that.
            recompute["gates"] = {
                name: {
                    "rows_checked": rep.get("rows_checked") or 0,
                    "not_recomputable": len(rep.get("not_recomputable") or []),
                    "mismatches": len(rep.get("mismatches") or []),
                }
                for name, rep in reports.items()
            }
            # A recompute that checked nothing is not a recompute that passed.
            # Without this the summary reads "ran" on a panel carrying no
            # evidence at all, which is the shape every gate in this campaign is
            # supposed to make impossible.
            recompute["vacuous"] = sorted(
                name for name, tally in recompute["gates"].items()
                if not tally["rows_checked"]
            )
            failed = {
                name: rep.get("mismatches") or []
                for name, rep in reports.items()
                if rep.get("mismatches")
            }
            if failed:
                lines = []
                for name, rows_bad in failed.items():
                    ids = ", ".join(str(m.get("design_id") or m) for m in rows_bad[:5])
                    lines.append(f"  {name}: {len(rows_bad)} row(s) (first: {ids})")
                raise SystemExit(
                    "HALTED: carried gate numbers do not reproduce from the row's own "
                    "sequence and structure to 1e-4:\n"
                    + "\n".join(lines)
                    + "\nDo not ship a row whose gates you could not reproduce."
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
        "unranked": len(unranked),
        "unranked_reasons": sorted({r["unranked_reason"] for r in unranked}),
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
        for reason in summary["unranked_reasons"]:
            print(f"  unranked: {reason}")
        for cap, n in sorted(summary["rejection_counts"].items(), key=lambda kv: -kv[1]):
            print(f"  rejected by {cap}: {n}")
        if summary["target_mimic_not_run"]:
            print(f"  {summary['target_mimic_not_run']} row(s) carry NO mimic verdict - absence is not a pass")
        if summary["relaxations_applied"]:
            print(f"  relaxed: {', '.join(summary['relaxations_applied'])} - disclose every one")
        if summary["short_of_request"]:
            print(f"  SHORT by {summary['short_of_request']} - fix upstream; ship the real N, never pad")
        if recompute["ran"]:
            for name, tally in recompute["gates"].items():
                note = "  <- checked NOTHING; not a pass" if not tally["rows_checked"] else ""
                print(
                    f"  recomputed {name}: {tally['rows_checked']} row(s), "
                    f"{tally['mismatches']} mismatch(es), "
                    f"{tally['not_recomputable']} not recomputable{note}"
                )
        else:
            print("  gate recompute: SKIPPED - disclose this")
        for skip in recompute.get("skipped") or []:
            print(f"  not recomputed - {skip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
