#!/usr/bin/env python3
"""Rank a batch's completed subjobs by a Score metric into a CSV.

Reads a batch parent row + its per-subjob rows and emits a ranked CSV of
candidate -> metric, the "submit a batch, then rank whatever completed" readout.
This is the post-run companion to the batch recipe in
references/workflows.md (poll the PARENT on batchStatus, then read per-subjob Score).

Input is a directory or JSON file holding the saved rows. Accepted shapes:
  - a DOWNLOADED batch dir: one subdir per subjob (named <batch>-<subjob>/), each
    holding that subjob's metrics.csv + result files (the shape `download` unzips to)
  - {"parent": <parent-row>, "subjobs": [<subjob-row>, ...]}
  - a bare list of subjob rows (no parent), or a dir with parent.json + subjobs.json
The parent row carries the aggregate tally (batchStatus + statuses, e.g.
{"Complete": 3, "Running": 0, "In Queue": 0, "Stopped": 0}); each subjob row
carries its own JobStatus + Score (a JSON STRING per _common.read_score_field).

Selection metric: whichever Score key you pass with --metric (the Score dict
varies by tool); if omitted, the script auto-picks the first numeric Score key
common to the most completed subjobs and names it. Higher is better by default;
pass --ascending for lower-better metrics (e.g. an energy / pAE).

Usage:
  python3 rank_batch.py <run-dir-or-json>
  python3 rank_batch.py <run-dir-or-json> --metric iptm --out ranked.csv
  python3 rank_batch.py <run-dir-or-json> --metric pae --ascending --json
"""
import argparse
import csv
import glob
import json
import os
import sys

import _common


def _rows_from_download_dir(path):
    """A downloaded+unzipped batch is one subdir per subjob, each with a metrics.csv.
    Synthesize subjob rows (name + a numeric Score dict from the first metrics row).
    Returns [] if the dir does not look like a downloaded batch."""
    rows = []
    for sub in sorted(d for d in glob.glob(os.path.join(path, "*")) if os.path.isdir(d)):
        csvs = glob.glob(os.path.join(sub, "**", "metrics*.csv"), recursive=True)
        if not csvs:
            continue
        score = {}
        try:
            with open(csvs[0], newline="") as fh:
                r = next(csv.DictReader(fh), {}) or {}
            for k, v in r.items():
                try:
                    score[k] = float(v)
                except (TypeError, ValueError):
                    pass
        except OSError:
            pass
        rows.append({"JobName": os.path.basename(sub), "JobStatus": "Complete",
                     "Score": json.dumps(score)})
    return rows


def _load_rows(path):
    """Return (parent_row_or_None, [subjob_rows]) from a dir or a JSON file."""
    if os.path.isdir(path):
        parent, subs = None, []
        pj = os.path.join(path, "parent.json")
        sj = os.path.join(path, "subjobs.json")
        if os.path.exists(pj):
            with open(pj) as fh:
                parent = json.load(fh)
        if os.path.exists(sj):
            with open(sj) as fh:
                subs = json.load(fh)
        if not subs and not parent:
            # A downloaded+unzipped batch: per-subjob subdirs with metrics.csv.
            subs = _rows_from_download_dir(path)
        if not subs and not parent:
            raise SystemExit(
                f"{path} has no parent.json / subjobs.json and no per-subjob "
                f"metrics.csv subdirs (is this a downloaded batch dir?)")
        return parent, subs

    with open(path) as fh:
        data = json.load(fh)
    if isinstance(data, dict) and "subjobs" in data:
        return data.get("parent"), data["subjobs"]
    if isinstance(data, list):
        return None, data
    if isinstance(data, dict) and ("JobStatus" in data or "Score" in data):
        return None, [data]
    raise SystemExit(f"{path} is not a recognized batch-rows shape")


def _subjob_name(row):
    for key in ("JobName", "jobName", "name"):
        if row.get(key):
            return str(row[key])
    return "<unnamed>"


def load_batch(path):
    """Load the batch parent tally + per-subjob (name, status, score-dict) rows.

    Returns {batch_status, statuses, subjobs:[{name, status, score}]}. score is the
    parsed Score dict (or {} when absent / unparseable)."""
    parent, subs = _load_rows(path)
    out = {
        "batch_status": (parent or {}).get("batchStatus"),
        "statuses": (parent or {}).get("statuses"),
        "subjobs": [],
    }
    for row in subs:
        try:
            score = _common.read_score_field(row) or {}
        except (ValueError, TypeError):
            score = {}
        if not isinstance(score, dict):
            score = {}
        out["subjobs"].append({
            "name": _subjob_name(row),
            "status": row.get("JobStatus") or row.get("jobStatus"),
            "score": {k: v for k, v in score.items() if isinstance(v, (int, float))},
        })
    return out


def _auto_metric(subjobs):
    """Pick the numeric Score key present on the most completed subjobs."""
    counts = {}
    for s in subjobs:
        if s["status"] == "Complete":
            for k in s["score"]:
                counts[k] = counts.get(k, 0) + 1
    if not counts:
        return None
    return max(sorted(counts), key=counts.get)


def summarize(batch, metric=None, ascending=False):
    """Rank completed subjobs by the chosen Score metric.

    Returns {batch_status, statuses, selection_metric, ascending, n_subjobs,
    n_ranked, ranked:[{rank, name, status, metric_value, score}]}. Subjobs missing
    the metric (incomplete or no Score) are listed after the ranked ones with a
    None value."""
    subjobs = batch["subjobs"]
    metric = metric or _auto_metric(subjobs)

    scored, unscored = [], []
    for s in subjobs:
        val = s["score"].get(metric) if metric else None
        rec = {"name": s["name"], "status": s["status"],
               "metric_value": val, "score": s["score"]}
        (scored if isinstance(val, (int, float)) else unscored).append(rec)

    scored.sort(key=lambda r: r["metric_value"], reverse=not ascending)
    ranked = scored + unscored
    for r, rec in enumerate(ranked, 1):
        rec["rank"] = r

    return {
        "batch_status": batch["batch_status"],
        "statuses": batch["statuses"],
        "selection_metric": metric,
        "ascending": ascending,
        "n_subjobs": len(subjobs),
        "n_ranked": len(scored),
        "ranked": ranked,
    }


def write_csv(summary, out_path):
    """Write the ranked candidate -> metric table to a CSV."""
    metric = summary["selection_metric"] or "metric"
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "candidate", "status", metric])
        for rec in summary["ranked"]:
            val = rec["metric_value"]
            w.writerow([rec["rank"], rec["name"], rec["status"],
                        "" if val is None else val])
    return out_path


def print_summary(summary, written):
    metric = summary["selection_metric"]
    order = "ascending (lower is better)" if summary["ascending"] \
        else "descending (higher is better)"
    print(f"Batch status: {summary['batch_status']}   "
          f"tally: {summary['statuses']}")
    if metric:
        print(f"Selection metric: {metric}, {order} "
              f"({summary['n_ranked']}/{summary['n_subjobs']} subjob(s) scored)")
    else:
        print("Selection metric: none found in subjob Scores "
              "(pass --metric, or subjobs may not be Complete)")
    print(f"{'rank':>4}  {'candidate':<28} {'status':<12} {metric or 'value':>12}")
    for rec in summary["ranked"]:
        val = rec["metric_value"]
        vs = f"{val:.3f}" if isinstance(val, float) else (str(val) if val is not None else "-")
        print(f"{rec['rank']:>4}  {rec['name'][:28]:<28} "
              f"{str(rec['status'] or '-')[:12]:<12} {vs:>12}")
    if written:
        print(f"\nWrote ranked CSV: {written}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_dir",
                   help="dir (parent.json + subjobs.json) or a JSON file of batch rows")
    p.add_argument("--metric", default=None,
                   help="Score key to rank by (auto-picked when omitted)")
    p.add_argument("--ascending", action="store_true",
                   help="rank low-to-high (for energy / pAE-style metrics)")
    p.add_argument("--out", default=None,
                   help="ranked CSV path (default <run-dir>/ranked_batch.csv)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    a = p.parse_args(argv)

    summary = summarize(load_batch(a.run_dir), metric=a.metric, ascending=a.ascending)
    base = a.run_dir if os.path.isdir(a.run_dir) else os.path.dirname(a.run_dir) or "."
    out_path = a.out or os.path.join(base, "ranked_batch.csv")
    written = write_csv(summary, out_path)

    if a.json:
        print(json.dumps({**summary, "written": written}, indent=2))
    else:
        print_summary(summary, written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
