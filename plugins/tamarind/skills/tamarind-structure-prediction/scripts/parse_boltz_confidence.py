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
import math
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
CA_DISTANCE_MIN_ANGSTROM = 2.5
CA_DISTANCE_MAX_ANGSTROM = 4.5


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
    """Locate one logical score source per candidate directory.

    Deduplicate raw/processed copies within the same directory without dropping
    raw-only candidates in sibling directories.
    """
    all_csvs = sorted(
        glob.glob(os.path.join(run_dir, "**", "*.csv"), recursive=True)
    )
    by_directory = {}
    for path in all_csvs:
        by_directory.setdefault(os.path.dirname(path), []).append(path)

    selected = []
    for directory in sorted(by_directory):
        paths = by_directory[directory]
        score_files = [
            path for path in paths
            if "scores" in os.path.basename(path).lower()
            and "best" not in os.path.basename(path).lower()
        ]
        confidence_files = [
            path for path in paths
            if "confidence" in os.path.basename(path).lower()
            and "best" not in os.path.basename(path).lower()
        ]
        processed = [
            path for path in paths
            if os.path.basename(path).lower()
            in {"metrics-processed.csv", "metrics_processed.csv"}
        ]
        metrics = [
            path for path in paths
            if os.path.basename(path).lower() == "metrics.csv"
        ]
        best = [
            path for path in paths
            if "scores-best" in os.path.basename(path).lower()
        ]
        if score_files:
            selected.append(score_files[0])
        elif confidence_files:
            selected.append(confidence_files[0])
        elif processed:
            selected.append(processed[0])
        elif metrics:
            selected.append(metrics[0])
        elif best:
            selected.append(best[0])
    return selected


def _pdb_paths(run_dir):
    """Return result PDB paths under a model directory in stable order."""
    return sorted(glob.glob(os.path.join(run_dir, "**", "*.pdb"), recursive=True))


def _pdb_for_row(run_dir, row, row_count):
    """Map an unambiguous result PDB to one metrics row.

    Prefer a row's explicit structure filename. The one-row/one-PDB case is
    also unambiguous. Never infer multi-model mappings from lexical file order.
    """
    pdbs = _pdb_paths(run_dir)
    for key, value in row.items():
        normalized_key = key.strip().lower().replace("-", "_")
        if normalized_key not in {
            "structure_file", "pdb_file", "filename", "file"
        } or not isinstance(value, str) or not value.lower().endswith(".pdb"):
            continue
        requested = value.replace("\\", "/").lstrip("./")
        matches = [
            path
            for path in pdbs
            if os.path.relpath(path, run_dir).replace("\\", "/") == requested
            or os.path.basename(path) == os.path.basename(requested)
        ]
        if len(matches) == 1:
            return matches[0]
        return None
    if row_count == 1 and len(pdbs) == 1:
        return pdbs[0]
    return None


def _pdb_geometry(pdb_path):
    """Run a conservative adjacent-C-alpha continuity check on one PDB."""
    if pdb_path is None:
        return {
            "chain_count": None,
            "geometry_ok": None,
            "ca_pair_count": 0,
            "implausible_ca_pairs": 0,
            "nonfinite_ca_pairs": 0,
            "min_ca_distance": None,
            "max_ca_distance": None,
            "mean_ca_distance": None,
        }

    residues = []
    seen = set()
    atom_chains = set()
    hetero_atoms = {}
    water_names = {"DOD", "HOH", "SOL", "WAT"}
    with open(pdb_path, errors="replace") as handle:
        for line in handle:
            record = line[:6]
            chain = line[21:22].strip() or "_"
            if record == "ATOM  ":
                atom_chains.add(chain)
            elif record == "HETATM":
                residue_name = line[17:20].strip().upper()
                if residue_name not in water_names:
                    residue_id = (chain, line[22:27], residue_name)
                    hetero_atoms[residue_id] = hetero_atoms.get(residue_id, 0) + 1
            if not line.startswith("ATOM  ") or line[12:16].strip() != "CA":
                continue
            altloc = line[16:17]
            if altloc not in (" ", "A"):
                continue
            chain = line[21:22].strip() or "_"
            try:
                residue_number = int(line[22:26])
                coords = tuple(float(line[start:end]) for start, end in (
                    (30, 38), (38, 46), (46, 54)
                ))
            except ValueError:
                continue
            residue_id = (chain, residue_number, line[26:27])
            if residue_id in seen:
                continue
            seen.add(residue_id)
            residues.append((chain, residue_number, line[26:27], coords))

    distances = []
    nonfinite_pairs = 0
    for previous, current in zip(residues, residues[1:]):
        previous_chain, previous_number, previous_icode, previous_coords = previous
        current_chain, current_number, current_icode, current_coords = current
        consecutive = (
            current_number == previous_number + 1
            or (
                current_number == previous_number
                and current_icode.strip()
                and current_icode != previous_icode
            )
        )
        if current_chain != previous_chain or not consecutive:
            continue
        distance = math.dist(previous_coords, current_coords)
        if math.isfinite(distance):
            distances.append(distance)
        else:
            nonfinite_pairs += 1

    bad = nonfinite_pairs + sum(
        distance < CA_DISTANCE_MIN_ANGSTROM
        or distance > CA_DISTANCE_MAX_ANGSTROM
        for distance in distances
    )
    pair_count = len(distances) + nonfinite_pairs
    hetero_chains = {
        chain
        for (chain, _residue_id, _name), atom_count in hetero_atoms.items()
        if atom_count >= 2
    }
    chains = atom_chains | hetero_chains
    return {
        "chain_count": len(chains) or None,
        "geometry_ok": None if not pair_count else bad == 0,
        "ca_pair_count": pair_count,
        "implausible_ca_pairs": bad,
        "nonfinite_ca_pairs": nonfinite_pairs,
        "min_ca_distance": min(distances) if distances else None,
        "max_ca_distance": max(distances) if distances else None,
        "mean_ca_distance": (
            sum(distances) / len(distances) if distances else None
        ),
    }

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
        rows = _common.parse_scores_csv(csv_path)
        for j, raw in enumerate(rows):
            pdb_path = _pdb_for_row(os.path.dirname(csv_path), raw, len(rows))
            if pdb_path is None and os.path.isdir(path) and len(csvs) == 1:
                pdb_path = _pdb_for_row(path, raw, len(rows))
            geometry = _pdb_geometry(pdb_path)
            chain_count = geometry["chain_count"]
            label = _model_label(raw)
            if len(csvs) > 1:
                parent = os.path.basename(os.path.dirname(csv_path))
                label = f"{parent}:{label}" if label else parent
            models.append({
                "label": label or f"model_{i}_{j}",
                "plddt": _pick(raw, "plddt"),
                "ptm": _pick(raw, "ptm"),
                "iptm": _pick(raw, "iptm"),
                "ipsae": _pick(raw, "ipsae"),
                "pdockq": _pick(raw, "pdockq"),
                "confidence_score": _pick(raw, "confidence_score"),
                "source_csv": os.path.basename(csv_path),
                "chain_count": chain_count,
                "interface_applicable": (
                    None if chain_count is None else chain_count > 1
                ),
                **geometry,
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
        if key in INTERFACE_METRICS and not all(
            model.get("interface_applicable") is True for model in models
        ):
            continue
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
        if m.get("interface_applicable") is False:
            continue
        present = {k: m[k] for k in INTERFACE_METRICS
                   if _common.is_finite_number(m.get(k))}
        weak = any(_common.is_finite_number(m.get(k)) and m[k] < iptm_cutoff
                   for k in TM_INTERFACE_METRICS)
        weak = weak or (_common.is_finite_number(m.get("pdockq"))
                        and m["pdockq"] < PDOCKQ_CUTOFF)
        if present and weak:
            low.append({"label": m["label"], "rank": m["rank"], **present})

    geometry_failures = [
        {
            "label": model["label"],
            "rank": model["rank"],
            "ca_pair_count": model.get("ca_pair_count"),
            "implausible_ca_pairs": model.get("implausible_ca_pairs"),
            "nonfinite_ca_pairs": model.get("nonfinite_ca_pairs"),
            "min_ca_distance": model.get("min_ca_distance"),
            "max_ca_distance": model.get("max_ca_distance"),
        }
        for model in ranked
        if model.get("geometry_ok") is False
    ]
    geometry_unchecked = [
        {"label": model["label"], "rank": model["rank"]}
        for model in ranked
        if model.get("geometry_ok") is None
    ]

    return {
        "selection_metric": metric,
        "iptm_cutoff": iptm_cutoff,
        "n_models": len(ranked),
        "n_ranked": len(ranked) if metric is not None else 0,
        "ranked": ranked,
        "low_confidence_interfaces": low,
        "geometry_failures": geometry_failures,
        "geometry_unchecked": geometry_unchecked,
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
    failures = summary["geometry_failures"]
    if failures:
        print(
            "\nImplausible backbone geometry (adjacent C-alpha distance outside "
            f"{CA_DISTANCE_MIN_ANGSTROM}-{CA_DISTANCE_MAX_ANGSTROM} Å):"
        )
        for model in failures:
            print(
                f"  {model['label']}: {model['implausible_ca_pairs']}/"
                f"{model['ca_pair_count']} pair(s), "
                f"range {_fmt(model['min_ca_distance'])}-"
                f"{_fmt(model['max_ca_distance'])} Å"
            )
    unchecked = summary["geometry_unchecked"]
    if unchecked:
        labels = ", ".join(model["label"] for model in unchecked)
        print(f"\nGeometry unchecked (no unambiguous PDB mapping): {labels}")


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
