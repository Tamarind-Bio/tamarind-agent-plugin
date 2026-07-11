#!/usr/bin/env python3
"""Rank de-novo binder designs by interface metric and report the pass fraction.

Reads a downloaded binder-design results dir (BoltzGen / BindCraft / RFdiffusion /
rfantibody / igdesign) and prints designs ranked by the interface metric, plus the
max + 10th-best + fraction-above-cutoff summary (the Boltz analyze_results.py
"max / 10th / frac>cutoff" shape).

Selection metric (grounded in research/dossiers/protein-binder-design.md and
antibody-nanobody-design.md):
  - BoltzGen  -> ipSAE (runIpsae interface metric; also pDockQ) in
                 final_ranked_designs/all_designs_metrics.csv
  - BindCraft -> ipTM (i_pTM) / i_pAE interface metrics in final_design_stats.csv
  - RFdiffusion (verify=true) / rfantibody / igdesign -> pLDDT / pAE / interface
    confidence in the per-design scores CSV
Higher is better for ipSAE / ipTM / pDockQ / pLDDT; pAE-family columns are
lower-better and excluded from the default ranking metric.

Usage:
  python3 summarize_binder_metrics.py <run-dir>
  python3 summarize_binder_metrics.py <run-dir> --metric ipsae --cutoff 0.7
  python3 summarize_binder_metrics.py <run-dir> --json
"""
import argparse
import glob
import json
import os
import sys

import _common

# Interface metrics where HIGHER is better, in selection-priority order. The first
# metric actually present in the CSV becomes the ranking key unless --metric forces one.
HIGHER_BETTER = {
    "ipsae": ["ipsae", "ipsae_score", "max_ipsae"],
    "iptm": ["iptm", "i_ptm", "complex_iptm", "interface_ptm"],
    "pdockq": ["pdockq", "pdockq2"],
    "plddt": ["plddt", "binder_plddt", "mean_plddt", "complex_plddt"],
    "ptm": ["ptm", "complex_ptm"],
}
METRIC_PRIORITY = ["ipsae", "iptm", "pdockq", "plddt", "ptm"]
DEFAULT_CUTOFF = {"ipsae": 0.7, "iptm": 0.6, "pdockq": 0.23, "plddt": 80.0,
                  "ptm": 0.6}


def _pick(row, aliases):
    for alias in aliases:
        for col, val in row.items():
            if col.strip().lower() == alias and _common.is_finite_number(val):
                return val
    return None


def _design_label(row):
    for col in ("design", "design_name", "name", "model", "id", "rank"):
        for k, v in row.items():
            if k.strip().lower() == col:
                return str(v)
    return None


def _find_metrics_csv(run_dir):
    """BoltzGen all_designs_metrics.csv, BindCraft final_design_stats.csv, or any
    per-design scores CSV under the results dir."""
    patterns = ["all_designs_metrics.csv", "final_design_stats.csv",
                "*design*stats*.csv", "*metrics*.csv", "*scores*.csv", "*.csv"]
    for pat in patterns:
        hits = sorted(glob.glob(os.path.join(run_dir, "**", pat), recursive=True))
        if hits:
            return hits[0]
    return None


def load_designs(path):
    """Load per-design rows from a results dir or a single CSV.

    Returns a list of dicts: {label, ipsae, iptm, pdockq, plddt, ptm}. Missing
    metrics stay None."""
    if os.path.isdir(path):
        csv_path = _find_metrics_csv(path)
        if not csv_path:
            raise SystemExit(f"no metrics CSV under {path} "
                             "(looked for all_designs_metrics / final_design_stats)")
    elif path.lower().endswith(".csv"):
        csv_path = path
    else:
        raise SystemExit(f"{path} is not a directory or a .csv")

    designs = []
    for i, raw in enumerate(_common.parse_scores_csv(csv_path)):
        d = {"label": _design_label(raw) or f"design_{i}"}
        for key, aliases in HIGHER_BETTER.items():
            d[key] = _pick(raw, aliases)
        designs.append(d)
    if not designs:
        raise SystemExit(f"{csv_path} has no rows")
    return designs


def _resolve_metric(designs, forced):
    if forced:
        if forced not in HIGHER_BETTER:
            raise SystemExit(f"unknown metric {forced}; "
                             f"choose from {list(HIGHER_BETTER)}")
        return forced
    for key in METRIC_PRIORITY:
        if any(_common.is_finite_number(d.get(key)) for d in designs):
            return key
    raise SystemExit("no rankable interface metric present in the CSV")


def summarize(designs, metric=None, cutoff=None):
    """Rank designs by the interface metric; report max, 10th-best, and the
    fraction at/above the confidence cutoff.

    Returns {selection_metric, cutoff, n_designs, n_scored, max, tenth,
    fraction_above_cutoff, n_above_cutoff, ranked:[...]}."""
    metric = _resolve_metric(designs, metric)
    if cutoff is None:
        cutoff = DEFAULT_CUTOFF[metric]
    if not _common.is_finite_number(cutoff):
        raise SystemExit("cutoff must be a finite number")

    normalized = [_common.normalize_non_finite(d) for d in designs]
    scored = [d for d in normalized if _common.is_finite_number(d.get(metric))]
    ranked = sorted(scored, key=lambda d: d[metric], reverse=True)
    for r, d in enumerate(ranked, 1):
        d["rank"] = r

    vals = [d[metric] for d in ranked]
    above = [d for d in ranked if d[metric] >= cutoff]
    frac = (len(above) / len(scored)) if scored else 0.0

    return {
        "selection_metric": metric,
        "cutoff": cutoff,
        "n_designs": len(designs),
        "n_scored": len(scored),
        "max": vals[0] if vals else None,
        "tenth": vals[9] if len(vals) >= 10 else None,
        "n_above_cutoff": len(above),
        "fraction_above_cutoff": round(frac, 4),
        "ranked": ranked,
    }


def _fmt(v):
    return f"{v:.3f}" if isinstance(v, float) else "-"


def print_summary(summary, show=10):
    metric = summary["selection_metric"]
    print(f"Selection metric: {metric} (higher is better; "
          f"{summary['n_scored']}/{summary['n_designs']} design(s) scored)")
    print(f"max {metric}: {_fmt(summary['max'])}   "
          f"10th-best: {_fmt(summary['tenth'])}   "
          f"frac >= {summary['cutoff']}: {summary['fraction_above_cutoff']} "
          f"({summary['n_above_cutoff']} design(s))")
    print(f"\nTop {min(show, len(summary['ranked']))} by {metric}:")
    print(f"{'rank':>4}  {'design':<24} {'ipSAE':>6} {'ipTM':>6} "
          f"{'pDockQ':>6} {'pLDDT':>7} {'pTM':>6}")
    for d in summary["ranked"][:show]:
        print(f"{d['rank']:>4}  {d['label'][:24]:<24} "
              f"{_fmt(d.get('ipsae')):>6} {_fmt(d.get('iptm')):>6} "
              f"{_fmt(d.get('pdockq')):>6} {_fmt(d.get('plddt')):>7} "
              f"{_fmt(d.get('ptm')):>6}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_dir", help="binder-design results dir (or a metrics CSV)")
    p.add_argument("--metric", default=None,
                   help="force the ranking metric (ipsae/iptm/pdockq/plddt/ptm)")
    p.add_argument("--cutoff", type=float, default=None,
                   help="confidence cutoff for the pass fraction (metric default)")
    p.add_argument("--show", type=int, default=10, help="rows to print (default 10)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    a = p.parse_args(argv)

    summary = summarize(load_designs(a.run_dir), metric=a.metric, cutoff=a.cutoff)
    if a.json:
        print(json.dumps(summary, indent=2, allow_nan=False))
    else:
        print_summary(summary, show=a.show)
    return 0


if __name__ == "__main__":
    sys.exit(main())
