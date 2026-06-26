#!/usr/bin/env python3
"""Extract and rank docked poses from a docking results dir, write the top-N.

Reads a downloaded DiffDock / Autodock Vina / gnina / smina results directory and
prints a per-pose table ranked by the tool's selection metric, then writes the
top-N individual pose files into an output dir for downstream use.

Selection metric depends on the docker:
  - Autodock Vina / smina: binding affinity in kcal/mol from log.txt's score table
    (MORE NEGATIVE is better). Vina writes a SINGLE multi-model ligand_out.{pdbqt,
    sdf,pdb}; smina writes a multi-model ligand_out.pdbqt + a log.txt score table.
    The N models in the ensemble are in the same order as the N log rows, so model
    i pairs with affinity row i.
  - gnina: CNN affinity + pose score in out/log.txt, poses in a multi-model
    out/result.sdf (one record per pose, same order as the log).
  - DiffDock: one file per ranked pose, rank<N>_confidence<score>.sdf, no physics
    energy; HIGHER confidence is better and the score's sign is part of the number.

The script splits a multi-model ensemble into individual poses (PDB/PDBQT on
MODEL..ENDMDL, SDF on the $$$$ terminator) so each written pose is a distinct
structure, not the whole ensemble copied N times. Affinity (kcal/mol) is
ascending-better, confidence descending-better.

Usage:
  python3 extract_docking_poses.py <run-dir>
  python3 extract_docking_poses.py <run-dir> --top 5 --out top_poses
  python3 extract_docking_poses.py <run-dir> --json
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys

import _common

# Vina/gnina/smina log lines like:  "   1     -7.088      0.000      0.000"
# (mode/rank, affinity kcal/mol, then RMSD columns). Capture rank + affinity.
_AFFINITY_LINE = re.compile(r"^\s*(\d+)\s+(-?\d+\.\d+)")
# DiffDock filenames: rank3_confidence-1.23.sdf / rank1.sdf. The score's sign is
# part of the number (rank1_confidence-1.42.sdf), so only an underscore may act
# as a separator before it; a hyphen there is the value's minus sign, not a
# separator (the bug fixed here was `[_-]?` eating that minus -> sign flip).
_RANK_CONF = re.compile(r"rank_?(\d+).*?confidence_?(-?\d+(?:\.\d+)?)", re.I)
_RANK_ONLY = re.compile(r"rank_?(\d+)", re.I)

# A single multi-model ensemble a Vina/gnina/smina run writes (one file holds
# every pose). Preferred extension order: split just one, they hold the same
# poses. `*out*` is deliberately excluded (would catch output.log-style files).
_ENSEMBLE_GLOBS = ("*ligand_out*", "*result*", "*docked*", "*poses*")
_ENSEMBLE_EXT_PREF = (".sdf", ".pdbqt", ".pdb", ".mol2")


def _find(run_dir, *names):
    for name in names:
        hits = sorted(glob.glob(os.path.join(run_dir, "**", name), recursive=True))
        if hits:
            return hits
    return []


def _parse_affinity_log(log_path):
    """Pull (rank, affinity_kcal_mol) rows out of a Vina/gnina/smina log table.

    Header / separator lines don't start with `<int> <float>` so the regex
    excludes them; we do NOT filter on sign, a positive (unfavorable) affinity
    is a real pose, not an artifact."""
    rows = []
    with open(log_path) as fh:
        for line in fh:
            m = _AFFINITY_LINE.match(line)
            if m:
                rows.append({"rank": int(m.group(1)), "affinity": float(m.group(2))})
    return rows


def _split_models(path):
    """Split a multi-model pose file into per-pose text blocks, in file order.

    PDB/PDBQT split on MODEL..ENDMDL; SDF on the $$$$ record terminator. A file
    with no delimiter is returned as one block. Returns [(block_text, ext)]."""
    ext = os.path.splitext(path)[1].lower()
    with open(path) as fh:
        text = fh.read()
    blocks = []
    if ext in (".pdb", ".pdbqt"):
        cur, in_model = [], False
        for line in text.splitlines(keepends=True):
            if line.startswith("MODEL"):
                cur, in_model = [line], True
            elif line.startswith("ENDMDL"):
                cur.append(line)
                blocks.append("".join(cur))
                cur, in_model = [], False
            elif in_model:
                cur.append(line)
    elif ext == ".sdf":
        for rec in text.split("$$$$"):
            if rec.strip():
                blocks.append(rec.lstrip("\n") + "$$$$\n")
    if not blocks:                 # no delimiters: treat the whole file as one pose
        blocks = [text]
    return [(b, ext) for b in blocks]


def _ensemble_file(run_dir):
    """The single multi-model ensemble file to split (preferred extension)."""
    cands = []
    for g in _ENSEMBLE_GLOBS:
        for ext in _ENSEMBLE_EXT_PREF:
            cands += _find(run_dir, f"{g}{ext}")
    seen = []
    for p in cands:
        if p not in seen:
            seen.append(p)
    if not seen:
        return None
    seen.sort(key=lambda p: _ENSEMBLE_EXT_PREF.index(os.path.splitext(p)[1].lower())
              if os.path.splitext(p)[1].lower() in _ENSEMBLE_EXT_PREF else 99)
    return seen[0]


def _parse_diffdock_poses(run_dir):
    """DiffDock writes one file per pose with rank + confidence in the name."""
    poses = []
    for path in _find(run_dir, "*rank*.sdf", "*rank*.pdb", "*rank*.mol2"):
        base = os.path.basename(path)
        m = _RANK_CONF.search(base)
        if m:
            poses.append({"rank": int(m.group(1)),
                          "confidence": float(m.group(2)), "file": path})
            continue
        m = _RANK_ONLY.search(base)
        if m:
            poses.append({"rank": int(m.group(1)), "confidence": None, "file": path})
    return poses


def load_poses(run_dir):
    """Load ranked poses from a docking results dir.

    Returns (metric, poses) where metric is 'affinity' (kcal/mol, lower better),
    'confidence' (higher better), or 'rank' (file order only). A pose dict carries
    its rank, the metric value, and EITHER a 'file' (a per-pose file to copy, e.g.
    DiffDock) OR 'content'+'ext' (a split-out model block to write)."""
    if not os.path.isdir(run_dir):
        raise SystemExit(f"{run_dir} is not a directory")

    # DiffDock: one file per ranked pose, confidence in the filename.
    dd = _parse_diffdock_poses(run_dir)
    if dd and any(p.get("confidence") is not None for p in dd):
        return "confidence", dd

    # Vina / gnina / smina: split the single multi-model ensemble into poses and
    # pair model i with affinity row i (the log table is in model order).
    logs = _find(run_dir, "log.txt", "*log*.txt", "*.log")
    aff_rows = []
    for log_path in logs:
        aff_rows = _parse_affinity_log(log_path)
        if aff_rows:
            break
    ensemble = _ensemble_file(run_dir)
    if ensemble:
        poses = []
        for i, (block, ext) in enumerate(_split_models(ensemble)):
            row = {"rank": i + 1, "content": block, "ext": ext}
            if i < len(aff_rows):
                row["affinity"] = aff_rows[i]["affinity"]
            poses.append(row)
        if any("affinity" in p for p in poses):
            return "affinity", poses
        return "rank", poses

    # Fallback: DiffDock rank-only files (no confidence parsed).
    if dd:
        return "rank", dd
    raise SystemExit(f"no docked poses or affinity log found under {run_dir}")


def summarize(metric, poses, top=3):
    """Rank poses by the detected metric and select the top-N."""
    if metric == "affinity":          # kcal/mol: more negative is better
        ranked = sorted(poses, key=lambda p: p.get("affinity", float("inf")))
    elif metric == "confidence":      # higher is better
        ranked = sorted(poses, key=lambda p: (p.get("confidence") is None,
                                              -(p.get("confidence") or 0.0)))
    else:                             # rank: preserve given order
        ranked = sorted(poses, key=lambda p: p.get("rank", 0))
    for r, p in enumerate(ranked, 1):
        p["rank"] = r
    return {"selection_metric": metric, "n_poses": len(ranked),
            "top": top, "ranked": ranked}


def write_top(summary, out_dir):
    """Write the top-N ranked poses into out_dir, renamed by rank.

    A pose with 'content' is a model block we split out (written directly); a pose
    with 'file' is an existing per-pose file (copied)."""
    written = []
    os.makedirs(out_dir, exist_ok=True)
    for p in summary["ranked"][:summary["top"]]:
        dst = None
        if p.get("content") is not None:
            ext = p.get("ext") or ".pdb"
            dst = os.path.join(out_dir, f"pose_rank{p['rank']:02d}{ext}")
            with open(dst, "w") as fh:
                fh.write(p["content"])
        elif p.get("file") and os.path.exists(p["file"]):
            ext = os.path.splitext(p["file"])[1]
            dst = os.path.join(out_dir, f"pose_rank{p['rank']:02d}{ext}")
            shutil.copyfile(p["file"], dst)
        if dst:
            written.append(dst)
    return written


def print_summary(summary, written):
    metric = summary["selection_metric"]
    label = {"affinity": "binding affinity kcal/mol (lower is better)",
             "confidence": "DiffDock confidence (higher is better)",
             "rank": "pose order (no score parsed)"}[metric]
    print(f"Selection metric: {label} ({summary['n_poses']} pose(s))")
    print(f"{'rank':>4}  {metric:>10}  source")
    for p in summary["ranked"]:
        val = p.get(metric)
        vs = f"{val:.3f}" if isinstance(val, float) else "-"
        src = os.path.basename(p["file"]) if p.get("file") else f"model {p['rank']}"
        print(f"{p['rank']:>4}  {vs:>10}  {src}")
    if written:
        print(f"\nWrote top {len(written)} pose(s):")
        for w in written:
            print(f"  {w}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_dir", help="docking results dir to parse")
    p.add_argument("--top", type=int, default=3, help="N top poses to write (default 3)")
    p.add_argument("--out", default=None,
                   help="dir to write top poses into (default <run-dir>/top_poses)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    a = p.parse_args(argv)

    metric, poses = load_poses(a.run_dir)
    summary = summarize(metric, poses, top=a.top)
    out_dir = a.out or os.path.join(a.run_dir, "top_poses")
    written = write_top(summary, out_dir)

    if a.json:
        slim = {**summary, "ranked": [{k: v for k, v in p.items() if k != "content"}
                                      for p in summary["ranked"]], "written": written}
        print(json.dumps(slim, indent=2))
    else:
        print_summary(summary, written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
