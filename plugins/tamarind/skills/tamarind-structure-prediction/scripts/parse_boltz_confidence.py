#!/usr/bin/env python3
"""Parse confidence metrics from a structure-prediction results dir and rank models.

Reads a downloaded Boltz / Chai / AlphaFold / Protenix / ESMFold2 results directory
(or a single scores CSV), surfaces interface metrics (ipTM, ipSAE, pDockQ), and
flags models below a configured interface cutoff.

Ranking uses the first finite metric shared by every model in this priority:
confidence_score, then ipTM, then pTM. Rows may therefore be reordered from the
CSV. If no finite metric is shared by every model, source order is preserved and
no numeric ranks are assigned; the helper never invents a total ordering from a
partial metric column.

Metric names are grounded in research/dossiers/structure-prediction.md:
  pLDDT  - per-residue / mean predicted local distance difference test (B-factor col)
  pTM    - predicted TM-score (global fold confidence)
  ipTM   - interface predicted TM-score (complex interface confidence)
  ipSAE  - IPSAE interface metric (runIpsae / runIpsae=true; protein-protein interface)
  pDockQ - predicted DockQ (interface quality estimate)

Usage:
  python3 parse_boltz_confidence.py <run-dir-or-csv>
  python3 parse_boltz_confidence.py <run-dir-or-csv> --json
  python3 parse_boltz_confidence.py <run-dir-or-csv> --iptm-cutoff 0.6
"""
import argparse
import glob
import json
import os
import sys

import _common

# Per-model confidence metric aliases. CSV column names vary across folders
# (Boltz, Chai, AlphaFold, Protenix), so map every known spelling to one key.
METRIC_ALIASES = {
    "plddt": ["plddt", "mean_plddt", "complex_plddt", "ptm_plddt", "avg_plddt"],
    "ptm": ["ptm", "complex_ptm", "ptm_score"],
    "iptm": ["iptm", "complex_iptm", "interface_ptm", "iptm_score"],
    "ipsae": ["ipsae", "ipsae_score", "max_ipsae"],
    "pdockq": ["pdockq", "pdockq2", "pdockq_score"],
    "confidence_score": ["confidence_score", "confidence", "ranking_score",
                         "aggregate_score", "model_confidence"],
}
# Selection priority. A candidate is usable only when every model has a finite
# value for it, so a partial column never creates a misleading total ordering.
RANK_PRIORITY = ["confidence_score", "iptm", "ptm"]
# Interface metrics whose low values flag a weak complex interface. ipTM and ipSAE
# share the TM (0-1) scale, so the --iptm-cutoff applies to both; pDockQ uses a
# different scale, so it gets its own conventional acceptable-interface threshold.
INTERFACE_METRICS = ["iptm", "ipsae", "pdockq"]
TM_INTERFACE_METRICS = ["iptm", "ipsae"]
PDOCKQ_CUTOFF = 0.23


def _pick(row, key):
    """Return the first present alias for a logical metric, coerced to float."""
    for alias in METRIC_ALIASES[key]:
        for col, val in row.items():
            if col.strip().lower() == alias and _common.is_finite_number(val):
                return val
    return None


def _model_label(row):
    for col in ("model", "model_name", "name", "rank", "sample", "structure"):
        for k, v in row.items():
            if k.strip().lower() == col:
                return str(v)
    return None


def _find_scores_csv(run_dir):
    """Locate the per-model scores CSV(s). Prefer the all-models file over -best."""
    patterns = ["*-scores.csv", "*scores*.csv", "*confidence*.csv"]
    for pat in patterns:
        hits = sorted(glob.glob(os.path.join(run_dir, "**", pat), recursive=True))
        hits = [h for h in hits if "best" not in os.path.basename(h).lower()]
        if hits:
            return hits
    # Some result bundles contain only the platform-selected best row. It is
    # still useful as a one-model summary and its source order is authoritative.
    best = sorted(glob.glob(os.path.join(run_dir, "**", "*scores-best.csv"),
                            recursive=True))
    if best:
        return best
    # Cross-tool fallback for result bundles that do not use a conventional
    # scores/confidence filename.
    return sorted(glob.glob(os.path.join(run_dir, "**", "*.csv"), recursive=True))


def load_models(path):
    """Load per-model confidence rows from a results dir or a single CSV.

    Returns a list of normalized model dicts: {label, plddt, ptm, iptm, ipsae,
    pdockq, confidence_score, source_csv}. Missing metrics stay None."""
    if os.path.isdir(path):
        csvs = _find_scores_csv(path)
        if not csvs:
            raise SystemExit(f"no scores CSV under {path} (looked for *-scores.csv)")
    elif path.lower().endswith(".csv"):
        csvs = [path]
    else:
        raise SystemExit(f"{path} is not a directory or a .csv")

    models = []
    for i, csv_path in enumerate(csvs):
        for j, raw in enumerate(_common.parse_scores_csv(csv_path)):
            models.append({
                "label": _model_label(raw) or f"model_{i}_{j}",
                "plddt": _pick(raw, "plddt"),
                "ptm": _pick(raw, "ptm"),
                "iptm": _pick(raw, "iptm"),
                "ipsae": _pick(raw, "ipsae"),
                "pdockq": _pick(raw, "pdockq"),
                "confidence_score": _pick(raw, "confidence_score"),
                "source_csv": os.path.basename(csv_path),
            })
    return models


def _selection_metric(models):
    """Choose one finite metric shared by every model.

    A partial column cannot define an honest total ordering: assigning numeric
    ranks to rows missing that metric would imply evidence that is not present.
    """
    if not models:
        return None
    for key in RANK_PRIORITY:
        if all(_common.is_finite_number(model.get(key)) for model in models):
            return key
    return None


def summarize(models, iptm_cutoff=0.6):
    """Rank models by the selection metric and flag low-confidence interfaces.

    Returns {selection_metric, ranked:[...], low_confidence_interfaces:[...]}.
    A model is flagged when a TM-scaled interface metric (ipTM/ipSAE) is below
    iptm_cutoff, or pDockQ is below its own conventional threshold."""
    if not _common.is_finite_number(iptm_cutoff):
        raise SystemExit("iptm cutoff must be a finite number")
    normalized = [_common.normalize_non_finite(dict(model)) for model in models]
    metric = _selection_metric(normalized)
    if metric is None:
        ranked = normalized
        for model in ranked:
            model["rank"] = None
    else:
        ranked = sorted(normalized, key=lambda model: model[metric], reverse=True)
        for r, model in enumerate(ranked, 1):
            model["rank"] = r

    low = []
    for m in ranked:
        present = {k: m[k] for k in INTERFACE_METRICS
                   if _common.is_finite_number(m.get(k))}
        weak = any(_common.is_finite_number(m.get(k)) and m[k] < iptm_cutoff
                   for k in TM_INTERFACE_METRICS)
        weak = weak or (_common.is_finite_number(m.get("pdockq"))
                        and m["pdockq"] < PDOCKQ_CUTOFF)
        if present and weak:
            low.append({"label": m["label"], "rank": m["rank"], **present})

    return {
        "selection_metric": metric,
        "iptm_cutoff": iptm_cutoff,
        "n_models": len(ranked),
        "n_ranked": len(ranked) if metric is not None else 0,
        "ranked": ranked,
        "low_confidence_interfaces": low,
    }


def _fmt(v):
    return f"{v:.3f}" if _common.is_finite_number(v) else "-"


def print_summary(summary):
    metric = summary["selection_metric"]
    if metric is None:
        print("Selection metric: none (no finite metric is shared by every model; "
              "source order preserved without numeric ranks)")
    else:
        print(f"Selection metric: {metric} "
              f"(ranked best first; {summary['n_models']} model(s))")
    print(f"{'rank':>4}  {'model':<22} {'pLDDT':>7} {'pTM':>6} "
          f"{'ipTM':>6} {'ipSAE':>6} {'pDockQ':>6}")
    for m in summary["ranked"]:
        rank = "-" if m["rank"] is None else str(m["rank"])
        print(f"{rank:>4}  {m['label'][:22]:<22} "
              f"{_fmt(m['plddt']):>7} {_fmt(m['ptm']):>6} {_fmt(m['iptm']):>6} "
              f"{_fmt(m['ipsae']):>6} {_fmt(m['pdockq']):>6}")
    low = summary["low_confidence_interfaces"]
    if low:
        print(f"\nLow-confidence interface(s) (ipTM/ipSAE < {summary['iptm_cutoff']} "
              f"or pDockQ < {PDOCKQ_CUTOFF}):")
        for m in low:
            vals = ", ".join(f"{k}={_fmt(v)}" for k, v in m.items()
                             if k not in ("label", "rank"))
            rank = m["rank"] if m["rank"] is not None else "-"
            print(f"  rank {rank}: {m['label']} ({vals})")
    elif any(_common.is_finite_number(m.get(k)) for m in summary["ranked"]
             for k in INTERFACE_METRICS):
        print("\nNo low-confidence interfaces flagged.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_dir", help="results dir (or a scores CSV) to parse")
    p.add_argument("--iptm-cutoff", type=float, default=0.6,
                   help="flag interfaces below this confidence (default 0.6)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    a = p.parse_args(argv)

    summary = summarize(load_models(a.run_dir), iptm_cutoff=a.iptm_cutoff)
    if a.json:
        print(json.dumps(summary, indent=2, allow_nan=False))
    else:
        print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
