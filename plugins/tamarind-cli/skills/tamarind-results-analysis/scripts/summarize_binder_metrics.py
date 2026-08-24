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


def _find_metrics_csvs(run_dir):
    """Return every logical metrics CSV under run_dir, one per directory.

    An aggregate file (BoltzGen all_designs_metrics.csv, BindCraft
    final_design_stats.csv) already holds every design, so when one is present it
    is used directly. Otherwise per-design scores are split across sibling
    directories (RFdiffusion / rfantibody / igdesign layouts), so collect one CSV
    per directory instead of silently reading only the first match."""
    aggregate = []
    for name in ("all_designs_metrics.csv", "final_design_stats.csv"):
        aggregate += glob.glob(os.path.join(run_dir, "**", name), recursive=True)
    if aggregate:
        # Collect every aggregate file (both filename conventions) so a parent that
        # holds runs from different tools isn't truncated to whichever name matches first.
        return sorted(aggregate)

    by_directory = {}
    for path in sorted(glob.glob(os.path.join(run_dir, "**", "*.csv"), recursive=True)):
        by_directory.setdefault(os.path.dirname(path), []).append(path)

    def _priority(path):
        # Rank within a directory: design-*stats* files, then a processed metrics
        # file over its raw sibling, then generic scores. A bare design/input
        # manifest (e.g. designs.csv, no metric columns) must NOT outrank scores.csv,
        # so match "stats" — not a bare "design" — as the old *design*stats*.csv glob did.
        name = os.path.basename(path).lower()
        for rank, fragment in enumerate(
            ("stats", "metrics-processed", "metrics_processed", "metrics", "scores")
        ):
            if fragment in name:
                return rank
        return 99

    selected = []
    fallback = []
    for directory in sorted(by_directory):
        ranked = sorted(by_directory[directory], key=lambda p: (_priority(p), p))
        fallback.append(ranked[0])
        # Within a directory, take the highest-priority CSV that actually carries a
        # metric column. This skips an input/manifest file (e.g. designs.csv,
        # stats.csv) even when it outranks the real scores.csv by name, without
        # dropping the directory's genuine results.
        metric_csvs = [p for p in ranked if _csv_has_metric_column(p)]
        if metric_csvs:
            selected.append(metric_csvs[0])
    # Fall back to the name-priority pick only if no directory has any metric CSV
    # (e.g. a single unconventional results file), so callers still get a candidate.
    return selected or fallback


def _csv_has_metric_column(csv_path):
    """True if the CSV header carries any recognized interface-metric column."""
    aliases = {alias for names in HIGHER_BETTER.values() for alias in names}
    rows = _common.parse_scores_csv(csv_path)
    if not rows:
        return False
    return any(
        col is not None and col.strip().lower() in aliases for col in rows[0]
    )


def load_designs(path):
    """Load per-design rows from a results dir or a single CSV.

    Returns a list of dicts: {label, ipsae, iptm, pdockq, plddt, ptm}. Missing
    metrics stay None. A results dir may split designs across sibling
    directories, so every metrics CSV is read; when more than one contributes,
    labels are prefixed with each CSV's path relative to the run dir to stay
    unique (a bare parent name collides when the layout uses a fixed
    intermediate directory such as BoltzGen's final_ranked_designs/)."""
    if os.path.isdir(path):
        run_root = path
        csv_paths = _find_metrics_csvs(path)
        if not csv_paths:
            raise SystemExit(f"no metrics CSV under {path} "
                             "(looked for all_designs_metrics / final_design_stats)")
    elif path.lower().endswith(".csv"):
        run_root = os.path.dirname(path)
        csv_paths = [path]
    else:
        raise SystemExit(f"{path} is not a directory or a .csv")

    multi = len(csv_paths) > 1
    designs = []
    for csv_path in csv_paths:
        prefix = ""
        if multi:
            rel = os.path.relpath(os.path.dirname(csv_path), run_root)
            if rel in (".", ""):
                rel = os.path.splitext(os.path.basename(csv_path))[0]
            prefix = f"{rel}/"
        for i, raw in enumerate(_common.parse_scores_csv(csv_path)):
            base = _design_label(raw) or f"design_{i}"
            d = {"label": f"{prefix}{base}"}
            for key, aliases in HIGHER_BETTER.items():
                d[key] = _pick(raw, aliases)
            designs.append(d)
    if not designs:
        raise SystemExit(f"{', '.join(csv_paths)} has no rows")
    return designs


def _resolve_metric(designs, forced):
    if forced:
        if forced not in HIGHER_BETTER:
            raise SystemExit(f"unknown metric {forced}; "
                             f"choose from {list(HIGHER_BETTER)}")
        return forced
    counts = {
        key: sum(_common.is_finite_number(d.get(key)) for d in designs)
        for key in METRIC_PRIORITY
    }
    best = max(counts.values(), default=0)
    for key in METRIC_PRIORITY:
        if counts[key] == best and best > 0:
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
    unscored = [
        {**d, "rank": None, "unranked_reason": "missing-metric"}
        for d in normalized
        if not _common.is_finite_number(d.get(metric))
    ]
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
        "n_unscored": len(unscored),
        "max": vals[0] if vals else None,
        "tenth": vals[9] if len(vals) >= 10 else None,
        "n_above_cutoff": len(above),
        "fraction_above_cutoff": round(frac, 4),
        "ranked": ranked,
        "unranked": unscored,
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
    if summary["unranked"]:
        labels = ", ".join(d["label"] for d in summary["unranked"])
        print(f"\nUnranked (missing {metric}): {labels}")


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
