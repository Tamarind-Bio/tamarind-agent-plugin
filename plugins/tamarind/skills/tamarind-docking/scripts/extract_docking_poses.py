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
  - gnina: prefer the per-record CNNscore (then CNNaffinity) embedded in
    out/result.sdf. If those properties are absent or incomplete, preserve
    gnina's source pose order; do not reinterpret Vina-like log columns as the
    GNINA ranking objective.
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
import math
import os
import re
import shutil
import sys

# Vina/gnina/smina log lines like:  "   1     -7.088      0.000      0.000"
# (mode/rank, affinity kcal/mol, then RMSD columns). Capture rank + affinity.
_AFFINITY_LINE = re.compile(r"^\s*(\d+)\s+(-?\d+\.\d+)")
_MODEL_NUMBER = re.compile(r"^MODEL[ \t]+(\d+)[ \t]*(?:\r?\n|$)")
_ATOM_RECORD = re.compile(r"^(?:ATOM|HETATM)\b")
# DiffDock filenames: rank3_confidence-1.23.sdf / rank1.sdf. The score's sign is
# part of the number (rank1_confidence-1.42.sdf), so only an underscore may act
# as a separator before it; a hyphen there is the value's minus sign, not a
# separator (the bug fixed here was `[_-]?` eating that minus -> sign flip).
_RANK_CONF = re.compile(r"rank_?(\d+).*?confidence_?(-?\d+(?:\.\d+)?)", re.I)
_RANK_ONLY = re.compile(r"rank_?(\d+)", re.I)
_SDF_PROPERTY = re.compile(r"^>\s*<([^>]+)>")

# A single multi-model ensemble a Vina/gnina/smina run writes (one file holds
# every pose). Preferred extension order: split just one, they hold the same
# poses. `*out*` is deliberately excluded (would catch output.log-style files).
_ENSEMBLE_GLOBS = ("*ligand_out*", "*result*", "*docked*", "*poses*")
_ENSEMBLE_EXT_PREF = (".sdf", ".pdbqt", ".pdb", ".mol2")


def _is_generated_output(path, run_dir):
    """Exclude files this helper wrote during an earlier run."""
    rel_parts = [part.lower() for part in os.path.relpath(path, run_dir).split(os.sep)]
    base = os.path.basename(path).lower()
    return "top_poses" in rel_parts or re.match(r"pose_rank\d+", base) is not None


def _find(run_dir, *names):
    for name in names:
        hits = sorted(glob.glob(os.path.join(run_dir, "**", name), recursive=True))
        hits = [hit for hit in hits if not _is_generated_output(hit, run_dir)]
        if hits:
            return hits
    return []


def _finite_number(value):
    return (not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value))


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
                affinity = float(m.group(2))
                if math.isfinite(affinity):
                    rows.append({"source_rank": int(m.group(1)),
                                 "affinity": affinity})
    return rows


def _split_models(path):
    """Split a multi-model pose file into per-pose text blocks, in file order.

    PDB/PDBQT split on MODEL..ENDMDL; SDF on the $$$$ record terminator. A file
    with no delimiter is returned as one block. Returns [(block_text, ext)]."""
    ext = os.path.splitext(path)[1].lower()
    with open(path) as fh:
        text = fh.read()
    if not text.strip():
        raise SystemExit(f"empty pose file {path}")
    blocks = []
    if ext in (".pdb", ".pdbqt"):
        cur, in_model = [], False
        for line in text.splitlines(keepends=True):
            if line.startswith("MODEL"):
                if in_model:
                    raise SystemExit(
                        f"malformed multi-model pose file {path}: MODEL before ENDMDL"
                    )
                cur, in_model = [line], True
            elif line.startswith("ENDMDL"):
                if not in_model:
                    raise SystemExit(
                        f"malformed multi-model pose file {path}: ENDMDL without MODEL"
                    )
                cur.append(line)
                blocks.append("".join(cur))
                cur, in_model = [], False
            elif in_model:
                cur.append(line)
        if in_model:
            raise SystemExit(
                f"malformed multi-model pose file {path}: truncated MODEL without ENDMDL"
            )
    elif ext == ".sdf":
        if not text.rstrip().endswith("$$$$"):
            raise SystemExit(f"malformed SDF pose file {path}: missing $$$$ terminator")
        for rec in text.split("$$$$"):
            if rec.strip():
                blocks.append(rec.lstrip("\n") + "$$$$\n")
        if not blocks:
            raise SystemExit(f"malformed SDF pose file {path}: no pose records")
    if not blocks:                 # no MODEL delimiters: one PDB/PDBQT/MOL2 pose
        blocks = [text]
    if ext in (".pdb", ".pdbqt"):
        for block in blocks:
            if not any(_ATOM_RECORD.match(line) for line in block.splitlines()):
                raise SystemExit(f"pose block in {path} contains no atom records")
    return [(b, ext) for b in blocks]


def _validate_affinity_alignment(blocks, affinity_rows, path):
    """Prove that positional pose/score pairing is complete and correctly ordered."""
    if len(blocks) != len(affinity_rows):
        raise SystemExit(
            f"pose/score count mismatch for {path}: "
            f"{len(blocks)} pose block(s), {len(affinity_rows)} score row(s)"
        )

    score_ranks = [row["source_rank"] for row in affinity_rows]
    expected_ranks = list(range(1, len(affinity_rows) + 1))
    if score_ranks != expected_ranks:
        raise SystemExit(
            f"pose/score rank mismatch for {path}: "
            f"expected score ranks {expected_ranks}, found {score_ranks}"
        )

    model_numbers = []
    for block, ext in blocks:
        if ext not in (".pdb", ".pdbqt") or not block.startswith("MODEL"):
            continue
        match = _MODEL_NUMBER.match(block)
        if match is None:
            raise SystemExit(f"malformed MODEL number in pose file {path}")
        model_numbers.append(int(match.group(1)))

    if model_numbers:
        if len(model_numbers) != len(blocks) or model_numbers != score_ranks:
            raise SystemExit(
                f"pose/score rank mismatch for {path}: "
                f"MODEL numbers {model_numbers}, score ranks {score_ranks}"
            )


def _sdf_numeric_properties(block):
    """Read finite GNINA CNN fields from one SDF record."""
    wanted = {"cnnscore": "cnnscore", "cnnaffinity": "cnnaffinity"}
    values = {}
    lines = block.splitlines()
    for index, line in enumerate(lines[:-1]):
        match = _SDF_PROPERTY.match(line.strip())
        if not match:
            continue
        key = re.sub(r"[^a-z0-9]", "", match.group(1).lower())
        logical = wanted.get(key)
        if logical is None:
            continue
        try:
            value = float(lines[index + 1].strip())
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values[logical] = value
    return values


def _logs_look_like_gnina(log_paths):
    markers = re.compile(r"\bgnina\b|cnn\s*(?:score|affinity)", re.I)
    for path in log_paths:
        try:
            with open(path, errors="replace") as fh:
                if markers.search(fh.read()):
                    return True
        except OSError:
            continue
    return False


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
    parents = {os.path.dirname(os.path.realpath(path)) for path in seen}
    stems = {os.path.splitext(os.path.basename(path))[0].lower() for path in seen}
    if len(parents) != 1 or len(stems) != 1:
        raise SystemExit(
            "multiple docking ensemble candidates found; provide one run directory: "
            + ", ".join(seen)
        )
    seen.sort(key=lambda p: _ENSEMBLE_EXT_PREF.index(os.path.splitext(p)[1].lower())
              if os.path.splitext(p)[1].lower() in _ENSEMBLE_EXT_PREF else 99)
    return seen[0]


def _parse_diffdock_poses(run_dir):
    """DiffDock writes one file per pose with rank + confidence in the name."""
    poses = []
    paths = []
    for pattern in ("*rank*.sdf", "*rank*.pdb", "*rank*.mol2"):
        for path in _find(run_dir, pattern):
            if path not in paths:
                paths.append(path)
    for path in paths:
        base = os.path.basename(path)
        m = _RANK_CONF.search(base)
        if m:
            confidence = float(m.group(2))
            poses.append({"source_rank": int(m.group(1)),
                          "confidence": confidence if math.isfinite(confidence) else None,
                          "file": path})
            continue
        m = _RANK_ONLY.search(base)
        if m:
            poses.append({"source_rank": int(m.group(1)),
                          "confidence": None, "file": path})
    if poses:
        parents = {
            os.path.dirname(os.path.realpath(pose["file"])) for pose in poses
        }
        extensions = {
            os.path.splitext(pose["file"])[1].lower() for pose in poses
        }
        ranks = sorted(pose["source_rank"] for pose in poses)
        expected_ranks = list(range(1, len(poses) + 1))
        if len(parents) != 1:
            raise SystemExit(
                "DiffDock poses span multiple directories; provide one run directory"
            )
        if len(extensions) != 1:
            raise SystemExit(
                "DiffDock poses use mixed file extensions; provide one complete run"
            )
        if ranks != expected_ranks:
            raise SystemExit(
                f"incomplete or duplicate DiffDock ranks: "
                f"expected {expected_ranks}, found {ranks}"
            )
    return poses


def load_poses(run_dir):
    """Load ranked poses from a docking results dir.

    Returns (metric, poses) where metric is 'affinity' (kcal/mol, lower better),
    'confidence'/'cnnscore'/'cnnaffinity' (higher better), or 'source_rank'
    (authoritative input order only). A pose dict keeps source_rank separate from
    the helper's output rank and carries EITHER a 'file' (a per-pose file to copy,
    e.g. DiffDock) OR 'content'+'ext' (a split-out model block to write)."""
    if not os.path.isdir(run_dir):
        raise SystemExit(f"{run_dir} is not a directory")

    # DiffDock: one file per ranked pose, confidence in the filename.
    dd = _parse_diffdock_poses(run_dir)
    if dd and all(_finite_number(p.get("confidence")) for p in dd):
        return "confidence", dd

    # Vina / gnina / smina: split the single multi-model ensemble into poses and
    # pair model i with affinity row i (the log table is in model order).
    logs = []
    for pattern in ("log.txt", "*log*.txt", "*.log"):
        for path in _find(run_dir, pattern):
            if path not in logs:
                logs.append(path)
    ensemble = _ensemble_file(run_dir)
    if ensemble:
        ensemble_dir = os.path.dirname(os.path.realpath(ensemble))
        local_logs = [
            path for path in logs
            if os.path.dirname(os.path.realpath(path)) == ensemble_dir
        ]
        local_affinity_logs = [
            (path, rows) for path in local_logs
            if (rows := _parse_affinity_log(path))
        ]
        remote_affinity_logs = [
            path for path in logs if path not in local_logs and _parse_affinity_log(path)
        ]
        blocks = _split_models(ensemble)
        sdf_metrics = [_sdf_numeric_properties(block) if ext == ".sdf" else {}
                       for block, ext in blocks]
        looks_like_gnina = (
            any(metrics for metrics in sdf_metrics)
            or _logs_look_like_gnina(local_logs)
            or os.path.basename(ensemble).lower() == "result.sdf"
        )
        aligned_affinity_rows = []
        if not looks_like_gnina and len(local_affinity_logs) > 1:
            raise SystemExit(
                f"multiple affinity logs found beside {ensemble}: "
                + ", ".join(path for path, _ in local_affinity_logs)
            )
        if not looks_like_gnina and not local_affinity_logs and remote_affinity_logs:
            raise SystemExit(
                f"affinity log is not colocated with pose ensemble {ensemble}; "
                "provide one downloaded run directory"
            )
        if not looks_like_gnina and local_affinity_logs:
            _, aff_rows = local_affinity_logs[0]
            _validate_affinity_alignment(blocks, aff_rows, ensemble)
            aligned_affinity_rows = aff_rows
        poses = []
        for i, (block, ext) in enumerate(blocks):
            source_rank = (
                aligned_affinity_rows[i]["source_rank"]
                if i < len(aligned_affinity_rows) else i + 1
            )
            row = {"source_rank": source_rank, "content": block, "ext": ext}
            row.update(sdf_metrics[i])
            if i < len(aligned_affinity_rows):
                row["affinity"] = aligned_affinity_rows[i]["affinity"]
            poses.append(row)

        if looks_like_gnina:
            for metric in ("cnnscore", "cnnaffinity"):
                if poses and all(_finite_number(p.get(metric)) for p in poses):
                    return metric, poses
            return "source_rank", poses
        if poses and all(_finite_number(p.get("affinity")) for p in poses):
            return "affinity", poses
        return "source_rank", poses

    # Fallback: DiffDock rank-only files (no confidence parsed).
    if dd:
        return "source_rank", dd
    raise SystemExit(f"no docked poses or affinity log found under {run_dir}")


def summarize(metric, poses, top=3):
    """Rank poses by the detected metric and select the top-N."""
    rows = []
    for index, pose in enumerate(poses, 1):
        row = dict(pose)
        if not _finite_number(row.get("source_rank")):
            row["source_rank"] = index
        for key in ("affinity", "confidence", "cnnscore", "cnnaffinity"):
            if key in row and not _finite_number(row[key]):
                row[key] = None
        rows.append(row)

    numeric_metrics = {"affinity", "confidence", "cnnscore", "cnnaffinity"}
    if metric in numeric_metrics and not all(
            _finite_number(row.get(metric)) for row in rows):
        metric = "source_rank"
    if metric == "affinity":          # kcal/mol: more negative is better
        ranked = sorted(rows, key=lambda p: p["affinity"])
    elif metric in {"confidence", "cnnscore", "cnnaffinity"}:
        ranked = sorted(rows, key=lambda p: p[metric], reverse=True)
    else:                              # preserve authoritative source order
        metric = "source_rank"
        ranked = sorted(rows, key=lambda p: p["source_rank"])
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
             "cnnscore": "GNINA CNN pose score (higher is better)",
             "cnnaffinity": "GNINA CNN affinity (higher is better)",
             "source_rank": "source pose order (no complete score parsed)"}[metric]
    print(f"Selection metric: {label} ({summary['n_poses']} pose(s))")
    print(f"{'rank':>4}  {metric:>10}  source")
    for p in summary["ranked"]:
        val = p.get(metric)
        vs = f"{float(val):.3f}" if _finite_number(val) else "-"
        src = (os.path.basename(p["file"]) if p.get("file")
               else f"model {p['source_rank']}")
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
        print(json.dumps(slim, indent=2, allow_nan=False))
    else:
        print_summary(summary, written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
