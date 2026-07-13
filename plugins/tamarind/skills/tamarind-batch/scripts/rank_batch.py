#!/usr/bin/env python3
"""Rank a batch's completed subjobs by a Score metric into a CSV.

Reads a batch parent row + its per-subjob rows and emits a ranked CSV of
candidate -> metric, the "submit a batch, then rank whatever completed" readout.
This is the post-run companion to the batch recipe in
references/workflows.md (poll the PARENT on batchStatus, then read per-subjob Score).

Input is a directory or JSON file holding the saved rows. Accepted shapes:
  - a DOWNLOADED batch dir: one subdir per subjob (named <batch>-<subjob>/), each
    holding that subjob's metrics.csv + result files (status is unknown, so these
    rows are reported as unranked unless status-bearing JSON is also supplied)
  - the native CLI envelope: {"jobs": [<subjob-row>, ...], ...}
  - {"parent": <parent-row>, "subjobs": [<subjob-row>, ...]}
  - a bare list of subjob rows (no parent), or a dir with parent.json + subjobs.json
The parent row carries the aggregate tally (batchStatus + statuses, e.g.
{"Complete": 3, "Running": 0, "In Queue": 0, "Stopped": 0}); each subjob row
carries its own JobStatus + Score (a JSON STRING per _common.read_score_field).

Selection metric: whichever Score key you pass with --metric (the Score dict
varies by tool); if omitted, the script auto-picks the first numeric Score key
common to the most completed subjobs and names it. Direction is inferred for
known lower-better metrics (affinity, energy, pAE, RMSD, Kd/Ki/IC50); use
--ascending or --descending to override explicitly.

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
import re
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
                parsed = _common._maybe_float(v)
                if _common.is_finite_number(parsed):
                    score[k] = parsed
        except OSError:
            pass
        # A metrics file proves that an artifact exists, not that the remote job
        # reached a successful terminal state. Keep the status explicit and
        # unrankable until authoritative job JSON is supplied.
        rows.append({"JobName": os.path.basename(sub), "JobStatus": "Unknown",
                     "Score": json.dumps(score, allow_nan=False)})
    return rows


def _rows_from_document(data):
    """Return (parent, rows) from a supported JSON document shape."""
    if isinstance(data, dict) and isinstance(data.get("jobs"), list):
        parent = {"statuses": data.get("statuses")} if data.get("statuses") else None
        return parent, data["jobs"]
    if isinstance(data, dict) and isinstance(data.get("subjobs"), list):
        return data.get("parent"), data["subjobs"]
    if isinstance(data, list):
        return None, data
    if isinstance(data, dict) and ("JobStatus" in data or "Score" in data):
        return None, [data]
    return None


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
                subdoc = json.load(fh)
            parsed = _rows_from_document(subdoc)
            if parsed is None:
                raise SystemExit(f"{sj} is not a recognized subjob JSON shape")
            embedded_parent, subs = parsed
            parent = parent or embedded_parent
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
    parsed = _rows_from_document(data)
    if parsed is not None:
        return parsed
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
            "score": {k: v for k, v in score.items()
                      if _common.is_finite_number(v)},
        })
    return out


def _auto_metric(subjobs):
    """Pick the numeric Score key present on the most completed subjobs."""
    counts = {}
    for s in subjobs:
        if str(s["status"] or "").strip().lower() in {"complete", "completed"}:
            for k, value in s["score"].items():
                if _common.is_finite_number(value):
                    counts[k] = counts.get(k, 0) + 1
    if not counts:
        return None
    return max(sorted(counts), key=counts.get)


def _infer_ascending(metric):
    """Infer direction only for conventional lower-better metric names."""
    raw = str(metric or "")
    # Split both ordinary camelCase (bindingAffinity) and acronym boundaries
    # (RMSDValue) before lowercasing, then normalize punctuation consistently.
    words = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", raw)
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", words)
    normalized = re.sub(r"[^a-z0-9]+", "_", words.lower()).strip("_")
    tokens = set(normalized.split("_"))
    acronym_lower_better = (
        re.search(r"(?:^|_)(?:i_?)?p_?ae(?:_|$)", normalized)
        or re.search(r"(?:^|_)(?:delta_?g|dd?_?g)(?:_|$)", normalized)
    )
    return bool(
        tokens.intersection({"affinity", "energy", "pae", "rmsd", "ddg", "ic50", "kd", "ki"})
        or normalized in {"delta_g", "binding_energy", "binding_affinity"}
        or acronym_lower_better
    )


def summarize(batch, metric=None, ascending=None):
    """Rank completed subjobs by the chosen Score metric.

    Returns {batch_status, statuses, selection_metric, ascending, n_subjobs,
    n_ranked, ranked:[...], unranked:[...]}. Only successfully completed rows
    carrying the selected numeric metric appear in ``ranked``. Every other row
    appears in ``unranked`` with ``rank: null`` and an explicit reason."""
    subjobs = batch["subjobs"]
    metric = metric or _auto_metric(subjobs)
    direction_source = "explicit" if ascending is not None else "inferred"
    if ascending is None:
        ascending = _infer_ascending(metric)

    scored, unscored = [], []
    for s in subjobs:
        score = _common.normalize_non_finite(s["score"])
        val = score.get(metric) if metric else None
        status = str(s["status"] or "Unknown")
        rec = {"name": s["name"], "status": status,
               "metric_value": val, "score": score}
        is_complete = status.strip().lower() in {"complete", "completed"}
        if is_complete and _common.is_finite_number(val):
            scored.append(rec)
        else:
            rec["rank"] = None
            rec["unranked_reason"] = (
                "status-not-complete" if not is_complete else "missing-metric"
            )
            unscored.append(rec)

    scored.sort(key=lambda r: r["metric_value"], reverse=not ascending)
    for r, rec in enumerate(scored, 1):
        rec["rank"] = r

    return {
        "batch_status": batch["batch_status"],
        "statuses": batch["statuses"],
        "selection_metric": metric,
        "ascending": ascending,
        "direction_source": direction_source,
        "n_subjobs": len(subjobs),
        "n_ranked": len(scored),
        "n_unranked": len(unscored),
        "ranked": scored,
        "unranked": unscored,
    }


def write_csv(summary, out_path):
    """Write ranked rows followed by explicitly unranked rows to a CSV."""
    metric = summary["selection_metric"] or "metric"
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "candidate", "status", metric, "unranked_reason"])
        for rec in summary["ranked"] + summary["unranked"]:
            val = rec["metric_value"]
            w.writerow(["" if rec["rank"] is None else rec["rank"],
                        rec["name"], rec["status"],
                        "" if val is None else val,
                        rec.get("unranked_reason", "")])
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
    if summary["unranked"]:
        print("\nUnranked:")
        for rec in summary["unranked"]:
            print(f"   -  {rec['name'][:28]:<28} "
                  f"{str(rec['status'] or '-')[:12]:<12} "
                  f"{rec['unranked_reason']}")
    if written:
        print(f"\nWrote ranked CSV: {written}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_dir",
                   help="dir (parent.json + subjobs.json) or a JSON file of batch rows")
    p.add_argument("--metric", default=None,
                   help="Score key to rank by (auto-picked when omitted)")
    direction = p.add_mutually_exclusive_group()
    direction.add_argument("--ascending", action="store_true",
                           help="rank low-to-high")
    direction.add_argument("--descending", action="store_true",
                           help="rank high-to-low")
    p.add_argument("--out", default=None,
                   help="ranked CSV path (default <run-dir>/ranked_batch.csv)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    a = p.parse_args(argv)

    requested_direction = True if a.ascending else False if a.descending else None
    summary = summarize(
        load_batch(a.run_dir), metric=a.metric, ascending=requested_direction
    )
    base = a.run_dir if os.path.isdir(a.run_dir) else os.path.dirname(a.run_dir) or "."
    out_path = a.out or os.path.join(base, "ranked_batch.csv")
    written = write_csv(summary, out_path)

    if a.json:
        print(json.dumps({**summary, "written": written}, indent=2,
                         allow_nan=False))
    else:
        print_summary(summary, written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
