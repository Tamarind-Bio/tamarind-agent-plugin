#!/usr/bin/env python3
"""Pure structure/IO helpers for the Tamarind analysis scripts. NO API calls.

These read a downloaded results directory or a job's Score field. Structure parsing
uses gemmi (probe-first: import only fails if the optional deps are missing). Keep
this file side-effect-free so any per-skill script can import it.
"""
import csv
import json
import math


def is_finite_number(value):
    """True only for ordinary finite JSON-style numbers (booleans excluded)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def normalize_non_finite(value):
    """Recursively replace NaN and +/-Infinity with ``None``.

    Python's JSON decoder accepts these non-standard constants by default, and
    CSV float coercion accepts their spellings. Scientific result tables use
    them for missing measurements, so expose them as missing rather than letting
    them enter rankings or invalid JSON output.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: normalize_non_finite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_non_finite(item) for item in value]
    if isinstance(value, tuple):
        return tuple(normalize_non_finite(item) for item in value)
    return value


def load_chain(path, chain_id=None):
    """Load a CIF/PDB structure with gemmi and return the requested chain (or the
    first chain if chain_id is None). Returns a gemmi Chain. Requires gemmi."""
    import gemmi
    st = gemmi.read_structure(path)
    model = st[0]
    if chain_id is None:
        return model[0]
    for chain in model:
        if chain.name == chain_id:
            return chain
    raise KeyError(f"chain {chain_id!r} not in {path} (have {[c.name for c in model]})")


def residue_plddt(chain):
    """Per-residue pLDDT for a predicted structure: the mean B-factor over each
    residue's atoms (AlphaFold/Boltz/ESMFold store pLDDT in the B-factor column).
    Returns a list of (residue_number, mean_bfactor). Requires gemmi (the chain)."""
    out = []
    for res in chain:
        bfacs = [atom.b_iso for atom in res]
        if bfacs:
            out.append((res.seqid.num, sum(bfacs) / len(bfacs)))
    return out


def atom_coords(chain, atom_name="CA"):
    """Return [(residue_number, (x, y, z))] for the named atom in each residue
    (default CA backbone). Requires gemmi (the chain)."""
    out = []
    for res in chain:
        for atom in res:
            if atom.name == atom_name:
                pos = atom.pos
                out.append((res.seqid.num, (pos.x, pos.y, pos.z)))
                break
    return out


def parse_scores_csv(path):
    """Parse a Tamarind scores/metrics CSV into a list of dicts (one per row).
    Numeric-looking values are coerced to float; everything else stays a string."""
    rows = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append({k: _maybe_float(v) for k, v in row.items()})
    return rows


def read_score_field(row, key=None):
    """Read the Score field off a job row. Score is stored as a JSON STRING (not a
    nested object), so parse it. With key, return that metric; else the whole dict."""
    raw = row.get("Score")
    if raw is None:
        return None
    score = json.loads(raw) if isinstance(raw, str) else raw
    score = normalize_non_finite(score)
    return score.get(key) if key is not None else score


def _maybe_float(v):
    try:
        value = float(v)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return v
