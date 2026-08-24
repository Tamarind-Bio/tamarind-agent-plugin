"""Pre-written QA structural-analysis helpers for the E2B sandbox.

``run_analysis_code_json`` PREPENDS this module's source into the executed
analysis code whenever the code references one of the helper functions, so the
real contact logic runs inline and is persisted/displayed in the UI code panel
for review (no opaque command, no hidden uploaded file). The analysis code then
just calls the functions directly, e.g.:

    rows = []
    for pdb in ["design_1.pdb", "design_2.pdb"]:
        rows.append(check_hotspot_contacts(
            pdb, target_chain="B",
            hotspot_resids="56,58,52A,113,115,122-125",
            reference_pdb_path="target.pdb",
            cutoff=4.0, atom_selection="heavy",
        ))
    print(summarize_engagement(rows))

Pass ``hotspot_resids`` as PDB resseq from the epitope scratchpad / bindingSite
string. When design structures renumber the target chain to file index 1..N
(common on BoltzGen refolds), pass ``reference_pdb_path`` to the campaign
target PDB so hotspots are mapped before the contact check. With
``numbering_mode="auto"`` (default), the helper detects whether the design
uses PDB resseq or file index by matching residue identities.

The CALLER chooses the contact definition — nothing is hardcoded beyond
documented, overridable defaults:
  cutoff          distance threshold in Angstrom (default 4.0)
  atom_selection  which atoms count toward a contact: heavy | all | ca |
                  backbone | sidechain (default heavy)
Pick the definition that fits the question (e.g. a Cα 8 Å neighborhood, or
sidechain-only contacts) rather than assuming one.

Self-contained: standard library + numpy + biotite + biopython (all
pre-installed in the sandbox). Heavy imports are deferred so the module imports
in the app process / unit tests (where neither is present) for source
extraction and testing.

Design-sheet numerics
---------------------
The second half of this module is the pure-numeric layer behind the miniprotein
design sheet: ipSAE_min from per-chain-pair columns, sc_DockQ from a batch
aggregate CSV, sequence-liability flags, DSSP fold class, exact TM-0.90
single-linkage clustering and transductive z-scoring. The selection-cap panel
builder moved to ``qa_selection_helpers`` so a panel-selection analysis does not
inline this module too. Every one of those is a pure function over dicts/lists so it can be
unit-tested outside the sandbox and re-run verbatim by the sheet writer at
write time.

RETRACTED DEVIATION — Local Composition Perplexity (LCP)
    lcp_score IS reproduced as of 2026-08-23 — ``campaign/cda/subagents/lcp.py``
    (numpy port of Chroma's ``complexity_lcp``, under Figure 1's L/(L-w+1)
    normalisation), stamped on every shipped row by ``qa.stamp_lcp_scores``.
    w=30 and entropy_min=2.32 are confirmed against the source figure, which
    Anthropic released publicly; nothing here is provisional any more.
    ``composition_liability_flags`` is now the liability gate BESIDE LCP, not a
    substitute for it.

DISCLOSED DEVIATION — ipSAE mask
    ``ipsae_min_from_pair_columns`` reconstructs ipSAE_min from the per-ordered-
    chain-pair scalars the metrics CSV exposes. Union-mask ipSAE is provably not
    reconstructible from those scalars (merging protomers changes ``n0res`` ->
    ``d0`` -> every ``ptm_func`` term), so v1 ships
    ``max over target protomers X of min(ipSAE_XC, ipSAE_CX)`` and stamps every
    row with ``IPSAE_MASK_STAMP``. On a SINGLE-chain target this is exactly
    Anthropic's definition -- zero deviation.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Literal

__all__ = [
    "check_hotspot_contacts",
    "cif_to_pdb_text",
    "composition_liability_flags",
    "cys_parity_flag",
    "dssp_fold_class",
    "final_score_from_terms",
    "homopolymer_run_flag",
    "ipsae_min_from_pair_columns",
    "rank_zscore_from_terms",
    "sc_dockq_from_batch_csv",
    "summarize_engagement",
    "tm_cluster_single_linkage",
    "transductive_zscore",
    "verify_pdb_matches",
]

# bindingSite values are comma/space-delimited per chain, e.g.
# "56,58,66,113,115,122-125" or "52A,56,100A-100C" (see interface.py).
_RESID_SEPARATORS = re.compile(r"[,\s]+")
_RESID_TOKEN = re.compile(r"^(\d+)([A-Za-z]?)$")
_BACKBONE_ATOMS = ("N", "CA", "C", "O")
NumberingMode = Literal["auto", "pdb_resseq", "file_index"]

# Parsed hotspot: (PDB resseq, insertion code letter or "").
HotspotResid = tuple[int, str]


def _format_resid(res_id: int, insertion_code: str = "") -> str:
    """PDB residue identifier for bindingSite strings (preserves insertion code)."""
    return f"{res_id}{insertion_code or ''}"


def _parse_resid_token(token: str) -> HotspotResid | None:
    text = token.strip()
    if not text:
        return None
    match = _RESID_TOKEN.match(text)
    if not match:
        return None
    return int(match.group(1)), match.group(2).upper()


def _expand_resid_range(lo: HotspotResid, hi: HotspotResid) -> list[HotspotResid]:
    lo_num, lo_ins = lo
    hi_num, hi_ins = hi
    if lo_num == hi_num and lo_ins and hi_ins:
        start = ord(lo_ins)
        end = ord(hi_ins)
        if start <= end:
            return [(lo_num, chr(c)) for c in range(start, end + 1)]
        return [(lo_num, chr(c)) for c in range(end, start + 1)]
    if not lo_ins and not hi_ins and lo_num != hi_num:
        lo_n, hi_n = min(lo_num, hi_num), max(lo_num, hi_num)
        return [(n, "") for n in range(lo_n, hi_n + 1)]
    return [lo] if lo == hi else [lo, hi]


def _parse_hotspot_resids(hotspot_resids: Any) -> list[HotspotResid]:
    """Normalize hotspot inputs to sorted unique (resseq, insertion_code) pairs.

    Accepts ints, numeric strings, insertion-code residues (52A), comma/space-
    delimited bindingSite strings, numeric ranges (122-125), and insertion-code
    ranges on the same resseq (100A-100C).
    """
    out: set[HotspotResid] = set()
    if hotspot_resids is None:
        return []

    if isinstance(hotspot_resids, int):
        return [(hotspot_resids, "")]

    if isinstance(hotspot_resids, str):
        raw_items: list[str] = [hotspot_resids]
    else:
        try:
            raw_items = [str(item) for item in hotspot_resids]
        except TypeError:
            raw_items = [str(hotspot_resids)]

    tokens: list[str] = []
    for item in raw_items:
        tokens.extend(t for t in _RESID_SEPARATORS.split(item.strip()) if t)

    for text in tokens:
        if "-" in text[1:]:
            lo_s, _, hi_s = text.partition("-")
            lo = _parse_resid_token(lo_s)
            hi = _parse_resid_token(hi_s)
            if lo is None or hi is None:
                continue
            out.update(_expand_resid_range(lo, hi))
            continue
        parsed = _parse_resid_token(text)
        if parsed is not None:
            out.add(parsed)

    return sorted(out, key=lambda pair: (pair[0], pair[1]))


def _normalize_ins_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text


def _aa3_match(left: str, right: str) -> bool:
    return (left or "").strip().upper()[:3] == (right or "").strip().upper()[:3]


# Standard protein residues for reference-PDB indexing (matches interface.py).
_PROTEIN_RESIDUES = frozenset(
    {
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "CYS",
        "GLN",
        "GLU",
        "GLY",
        "HIS",
        "ILE",
        "LEU",
        "LYS",
        "MET",
        "MSE",
        "PHE",
        "PRO",
        "SER",
        "THR",
        "TRP",
        "TYR",
        "VAL",
    }
)


def _parse_pdb_chain_residues(
    pdb_path: str,
    chain: str,
) -> tuple[list[tuple[int, int, str, str]], dict[HotspotResid, tuple[int, str]]]:
    """Ordered target-chain residues from a reference PDB.

    Returns ``(ordered, by_resseq)`` where ``ordered`` entries are
    ``(file_index_1based, resseq, insertion_code, resname)`` and ``by_resseq``
    maps ``(resseq, insertion_code)`` to ``(file_index, resname)``.
    """
    chain = (chain or "").strip()
    seen: set[tuple[int, str]] = set()
    ordered: list[tuple[int, int, str, str]] = []
    by_resseq: dict[HotspotResid, tuple[int, str]] = {}
    file_index = 0

    with open(pdb_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            # Index protein polymer residues only. Waters/ligands/glycans are
            # skipped even when recorded as HETATM; modified amino acids (MSE)
            # are kept — they are often HETATM in deposited PDBs.
            if not line.startswith(("ATOM  ", "HETATM")):
                continue
            if (line[21].strip() or "_") != chain:
                continue
            resname = line[17:20].strip().upper()
            if resname not in _PROTEIN_RESIDUES:
                continue
            try:
                resseq = int(line[22:26])
            except ValueError:
                continue
            ins_code = _normalize_ins_code(line[26].strip())
            key = (resseq, ins_code)
            if key in seen:
                continue
            seen.add(key)
            file_index += 1
            ordered.append((file_index, resseq, ins_code, resname))
            by_resseq[key] = (file_index, resname)

    return ordered, by_resseq


def _is_contiguous_renumbered_chain(design_names: dict[HotspotResid, str]) -> bool:
    """True when the target chain uses residue ids 1..N without gaps."""
    res_ids = sorted({res_id for res_id, _ in design_names})
    return bool(res_ids) and res_ids[0] == 1 and res_ids[-1] - res_ids[0] + 1 == len(res_ids)


def _detect_numbering_mode(
    requested: list[HotspotResid],
    ref_by_resseq: dict[HotspotResid, tuple[int, str]],
    design_names: dict[HotspotResid, str],
) -> NumberingMode:
    """Choose PDB-resseq vs file-index lookup using residue-name agreement."""
    pdb_hits = 0
    index_hits = 0
    comparable = 0
    for resseq, ins_code in requested:
        ref = ref_by_resseq.get((resseq, ins_code))
        if ref is None:
            continue
        comparable += 1
        file_index, ref_name = ref
        if _aa3_match(design_names.get((resseq, ins_code), ""), ref_name):
            pdb_hits += 1
        if _aa3_match(design_names.get((file_index, ""), ""), ref_name):
            index_hits += 1

    if comparable == 0:
        return "pdb_resseq"

    contiguous = _is_contiguous_renumbered_chain(design_names)

    # Prefer file index on 1..N refolds even when a PDB resseq number collides
    # with a same-name residue at the wrong position (e.g. res_id 113 == ARG
    # while the intended R113 sits at file index 96).
    if contiguous and index_hits > 0:
        if index_hits > pdb_hits:
            return "file_index"
        if index_hits == pdb_hits:
            return "file_index"

    if pdb_hits == comparable and pdb_hits > index_hits:
        return "pdb_resseq"
    if index_hits >= pdb_hits and index_hits > 0:
        return "file_index"
    return "pdb_resseq"


def _resolve_hotspot_lookups(
    requested: list[HotspotResid],
    *,
    mode: NumberingMode,
    ref_by_resseq: dict[HotspotResid, tuple[int, str]],
) -> list[dict[str, Any]]:
    """Map PDB-resseq hotspot labels to residue ids present in the design file."""
    lookups: list[dict[str, Any]] = []
    for resseq, ins_code in requested:
        label = _format_resid(resseq, ins_code)
        ref = ref_by_resseq.get((resseq, ins_code))
        if mode == "file_index" and ref is not None:
            file_index, _ref_name = ref
            lookups.append(
                {
                    "label": label,
                    "res_id": file_index,
                    "ins_code": "",
                    "reference_file_index": file_index,
                }
            )
        else:
            lookups.append(
                {
                    "label": label,
                    "res_id": resseq,
                    "ins_code": ins_code,
                    "reference_file_index": ref[0] if ref else None,
                }
            )
    return lookups


def _design_chain_residue_names(arr, target_chain: str) -> dict[HotspotResid, str]:
    import numpy as np

    names: dict[HotspotResid, str] = {}
    chain_atoms = arr[arr.chain_id == target_chain]
    ins_codes = np.array([_normalize_ins_code(c) for c in chain_atoms.ins_code])
    for idx in range(chain_atoms.array_length()):
        key = (int(chain_atoms.res_id[idx]), str(ins_codes[idx]))
        if key not in names:
            names[key] = str(chain_atoms.res_name[idx]).strip().upper()
    return names


def _hotspot_mask_from_lookups(arr, target_chain: str, lookups: list[dict[str, Any]]):
    import numpy as np

    chain_mask = arr.chain_id == target_chain
    mask = np.zeros(arr.array_length(), dtype=bool)
    ins_codes = np.array([_normalize_ins_code(c) for c in arr.ins_code])
    for entry in lookups:
        residue_mask = arr.res_id == int(entry["res_id"])
        ins = str(entry.get("ins_code") or "")
        if ins:
            residue_mask &= ins_codes == ins.upper()
        else:
            residue_mask &= ins_codes == ""
        mask |= chain_mask & residue_mask
    return mask


def _select_atoms(arr, atom_selection: str):
    """Filter an AtomArray to the atom set the caller asked to count as contact."""
    import numpy as np

    sel = (atom_selection or "heavy").lower()
    if sel == "all":
        return arr
    if sel == "ca":
        return arr[arr.atom_name == "CA"]
    if sel == "backbone":
        return arr[np.isin(arr.atom_name, _BACKBONE_ATOMS)]
    if sel == "sidechain":
        return arr[(~np.isin(arr.atom_name, _BACKBONE_ATOMS)) & (arr.element != "H")]
    # default: heavy atoms (exclude hydrogens)
    return arr[arr.element != "H"]


def check_hotspot_contacts(
    structure_path: str,
    target_chain: str,
    hotspot_resids: Any,
    *,
    reference_pdb_path: str | None = None,
    numbering_mode: NumberingMode = "auto",
    binder_chain: str | None = None,
    cutoff: float = 4.0,
    atom_selection: str = "heavy",
    model: int = 1,
) -> dict[str, Any]:
    """Does the binder contact the target epitope/hotspots in one structure?

    Loads a single design structure and reports, for the given epitope residues
    on ``target_chain``, which ones the binder contacts within ``cutoff`` Å using
    the chosen ``atom_selection``. Pass ``hotspot_resids`` as PDB resseq from
    the epitope scratchpad / bindingSite (comma-delimited, optional insertion
    codes like ``52A``).

    When ``reference_pdb_path`` points at the campaign target PDB, hotspots are
    mapped through that file before lookup. This is required when the design
    structure renumbers the target chain to file index 1..N (typical BoltzGen
    refolds). ``numbering_mode`` may be ``auto`` (default), ``pdb_resseq``, or
    ``file_index``.

    Returns a dict with engaged/contacted_hotspots/missed_hotspots/coverage/
    min_distance_angstrom/per_hotspot_min_distance/n_contact_atom_pairs, or an
    ``error`` key when the structure could not be evaluated.
    """
    requested = _parse_hotspot_resids(hotspot_resids)
    requested_labels = [_format_resid(r, ic) for r, ic in requested]
    base = {
        "structure_path": structure_path,
        "target_chain": target_chain,
        "cutoff": cutoff,
        "atom_selection": atom_selection,
        "requested_hotspots": requested_labels,
        "reference_pdb_path": reference_pdb_path,
        "numbering_mode": numbering_mode,
    }
    if not requested:
        return {**base, "error": "no hotspot residues provided"}

    # Heavy deps imported here (after the cheap guard) so the module imports in
    # the app process / unit tests without the sandbox scientific stack.
    import numpy as np
    import biotite.structure as struc
    import biotite.structure.io as strucio

    ref_by_resseq: dict[HotspotResid, tuple[int, str]] = {}
    if reference_pdb_path:
        try:
            _, ref_by_resseq = _parse_pdb_chain_residues(reference_pdb_path, target_chain)
        except OSError as exc:
            return {**base, "error": f"failed to read reference PDB: {exc}"}
        if not ref_by_resseq:
            return {
                **base,
                "error": (
                    f"no residues found on chain {target_chain!r} in reference PDB "
                    f"{reference_pdb_path!r}"
                ),
            }

    try:
        arr = strucio.load_structure(structure_path)
    except Exception as exc:  # noqa: BLE001 — surface load failure to the agent
        return {**base, "error": f"failed to load structure: {exc}"}

    if isinstance(arr, struc.AtomArrayStack):
        idx = max(0, min(model - 1, arr.stack_depth() - 1))
        arr = arr[idx]

    arr = arr[~struc.filter_solvent(arr)]
    design_names = _design_chain_residue_names(arr, target_chain)

    mode: NumberingMode = numbering_mode
    if mode == "auto":
        if ref_by_resseq:
            mode = _detect_numbering_mode(requested, ref_by_resseq, design_names)
        else:
            mode = "pdb_resseq"
    elif mode not in ("pdb_resseq", "file_index"):
        return {**base, "error": f"invalid numbering_mode: {numbering_mode!r}"}

    lookups = _resolve_hotspot_lookups(
        requested,
        mode=mode,
        ref_by_resseq=ref_by_resseq,
    )
    label_for_structure_key = {
        (int(entry["res_id"]), str(entry.get("ins_code") or "")): entry["label"]
        for entry in lookups
    }

    arr = _select_atoms(arr, atom_selection)

    target_mask = _hotspot_mask_from_lookups(arr, target_chain, lookups)
    target_atoms = arr[target_mask]
    if target_atoms.array_length() == 0:
        present: set[str] = set()
        chain_atoms = arr[arr.chain_id == target_chain]
        for idx in range(chain_atoms.array_length()):
            present.add(
                _format_resid(
                    int(chain_atoms.res_id[idx]),
                    _normalize_ins_code(chain_atoms.ins_code[idx]),
                )
            )
        present_list = sorted(present, key=lambda label: (len(label), label))
        return {
            **base,
            "numbering_mode": mode,
            "error": (
                f"no hotspot atoms found on chain {target_chain!r} for residues "
                f"{requested_labels} (atom_selection={atom_selection!r}, "
                f"numbering_mode={mode!r}). Check chain id, reference PDB, and "
                f"numbering. Residues present on that chain: "
                f"{present_list[:40]}{'...' if len(present_list) > 40 else ''}"
            ),
        }

    if binder_chain:
        binder_mask = arr.chain_id == binder_chain
    else:
        binder_mask = arr.chain_id != target_chain
    binder_atoms = arr[binder_mask]
    binder_chains = sorted({str(c) for c in binder_atoms.chain_id})
    if binder_atoms.array_length() == 0:
        return {**base, "numbering_mode": mode, "error": "no binder atoms found (check binder_chain)"}

    cell_list = struc.CellList(target_atoms, cell_size=cutoff)
    contacts = cell_list.get_atoms(binder_atoms.coord, radius=cutoff)

    per_hotspot: dict[str, float] = {}
    n_pairs = 0
    min_distance: float | None = None
    for i in range(binder_atoms.array_length()):
        row = contacts[i]
        hits = row[row != -1]
        for t in hits:
            d = float(np.linalg.norm(binder_atoms.coord[i] - target_atoms.coord[t]))
            struct_key = (
                int(target_atoms.res_id[t]),
                _normalize_ins_code(target_atoms.ins_code[t]),
            )
            label = label_for_structure_key.get(
                struct_key,
                _format_resid(struct_key[0], struct_key[1]),
            )
            n_pairs += 1
            if label not in per_hotspot or d < per_hotspot[label]:
                per_hotspot[label] = d
            if min_distance is None or d < min_distance:
                min_distance = d

    contacted = sorted(per_hotspot)
    missed = [label for label in requested_labels if label not in per_hotspot]
    return {
        **base,
        "numbering_mode": mode,
        "engaged": bool(contacted),
        "contacted_hotspots": contacted,
        "missed_hotspots": missed,
        "coverage": round(len(contacted) / len(requested_labels), 3),
        "n_contact_atom_pairs": n_pairs,
        "min_distance_angstrom": round(min_distance, 3) if min_distance is not None else None,
        "per_hotspot_min_distance": {r: round(d, 3) for r, d in sorted(per_hotspot.items())},
        "binder_chains": binder_chains,
    }


def summarize_engagement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up many check_hotspot_contacts() results for a QA verdict table.

    Returns counts plus the design ids that engaged vs. missed the epitope, so
    the report can reject the non-engaging ones.
    """
    engaged_ids: list[str] = []
    missed_ids: list[str] = []
    errored_ids: list[str] = []
    for row in rows:
        name = str(row.get("name") or row.get("design") or row.get("structure_path") or "?")
        if row.get("error"):
            errored_ids.append(name)
        elif row.get("engaged"):
            engaged_ids.append(name)
        else:
            missed_ids.append(name)
    return {
        "n_total": len(rows),
        "n_engaged": len(engaged_ids),
        "n_missed_epitope": len(missed_ids),
        "n_errored": len(errored_ids),
        "engaged_ids": engaged_ids,
        "missed_epitope_ids": missed_ids,
        "errored_ids": errored_ids,
    }


# ===========================================================================
# Design-sheet numerics
# ===========================================================================
#
# Everything below is a pure function over plain dicts / lists so the design
# sheet writer can recompute each gate at write time (Anthropic's rule: a row is
# admitted only when the recomputed value matches the carried value to 1e-4) and
# so each rule is unit-testable outside the sandbox.
#
# Missing / non-finite input is NEVER coerced to 0.0. It propagates as ``None``
# (ineligible), because a silently-zeroed term is the exact failure mode these
# gates exist to catch.

# Stamped on every scored row: v1 reconstructs ipSAE_min per target protomer and
# takes the max, because union-mask ipSAE cannot be rebuilt from pair scalars.
IPSAE_MASK_STAMP = "PER_PROTOMER_MAX(not UNION)"

# Name kept so callers that propagate it keep working; sentence rewritten so
# the reports they build stop asserting something false.
LCP_SUBSTITUTE_DEVIATION = (
    "lcp_score IS reproduced (campaign/cda/subagents/lcp.py) and is stamped on "
    "every shipped row, at the source figure's w=30 / entropy_min=2.32 under "
    "its L/(L-w+1) normalisation. composition_liability_flags() is the "
    "supporting liability gate beside LCP, not a substitute for it."
)

# Batch aggregate CSVs suffix EVERY column with " - {jobType}"
# (process_outputs.py: csv_score_name = f"{score_name} - {scoring_job['Type']}"),
# e.g. "ipSAE_AB - esmfold2". A per-job metrics.csv carries the raw spelling.
_BATCH_COLUMN_SUFFIX = " - "

_ZERO_VARIANCE_ATOL = 1e-12


def _as_float(value: Any) -> float | None:
    """Parse a CSV cell to a finite float, or ``None``.

    ``None``, ``""``, non-numeric text, NaN and +/-inf all return ``None`` --
    never 0.0. Bools are rejected (a bool is not a score).
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _resolve_metric_column(
    fieldnames: Iterable[Any],
    candidates: tuple[str, ...],
    *,
    job_type: str | None = None,
) -> str | None:
    """Actual header for the first matching candidate, raw or batch-suffixed.

    Matches either the raw metrics.csv spelling (``ipSAE_AB``) or the batch
    aggregate spelling (``ipSAE_AB - esmfold2``), case-insensitively. Matching is
    exact-or-``" - "``-suffixed on purpose: a loose prefix match would let
    ``ipSAE_AB_max`` answer a request for ``ipSAE_AB``.

    NOTHING IS EVER PICKED BY GUESSING. A candidate that matches more than one
    header raises ``ValueError`` naming them. That covers two distinct hazards
    with one rule:

    * two arms' suffixed columns (``ipSAE_AB - esmfold2`` and
      ``ipSAE_AB - protenix``) -- picking one silently attributes an arm's score
      to another;
    * a bare column NEXT TO a suffixed one (``ipSAE_AB`` and
      ``ipSAE_AB - esmfold2``), which is exactly what joining a batch aggregate
      against a per-job metrics.csv produces. The bare header carries no arm
      label, so which arm it holds is not recoverable from the table.

    Pass ``job_type`` to name the arm. With ``job_type`` set, the
    ``"{column} - {job_type}"`` spelling WINS over a bare column -- the caller
    asked for that arm by name. If the table carries per-arm columns but none
    for the requested arm, the answer is ``None`` (that arm is absent), NOT the
    unlabeled bare column. A bare column is returned under ``job_type`` only
    when the table has no per-arm columns at all for that metric, i.e. it is a
    per-job metrics.csv where the bare spelling is the only spelling.
    """
    names = [(str(name), str(name).strip().lower()) for name in fieldnames]
    arm = job_type.strip().lower() if job_type else None
    # Candidates are alternative SPELLINGS of one metric ("GlobalDockQ" vs
    # "Global DockQ"), not a priority list, so matches are gathered across all of
    # them before resolving. Resolving per candidate would let a bare spelling
    # win over a labelled one purely because it was listed first.
    bare: list[str] = []
    suffixed: list[tuple[str, str]] = []
    for candidate in candidates:
        key = candidate.strip().lower()
        prefix = key + _BATCH_COLUMN_SUFFIX
        for actual, lowered in names:
            if lowered == key:
                if actual not in bare:
                    bare.append(actual)
            elif lowered.startswith(prefix) and all(seen != actual for seen, _ in suffixed):
                suffixed.append((actual, lowered[len(prefix) :]))
    if not bare and not suffixed:
        return None
    if arm is not None:
        for actual, tail in suffixed:
            if tail == arm:
                return actual
        if suffixed:
            return None
        return bare[0]
    if len(bare) + len(suffixed) == 1:
        return bare[0] if bare else suffixed[0][0]
    raise ValueError(
        f"ambiguous column {candidates[0]!r}: "
        f"{sorted([*bare, *(actual for actual, _ in suffixed)])}. "
        "Pass job_type=... to name the arm."
    )


def _row_float(
    row: Mapping[str, Any],
    candidates: tuple[str, ...],
    *,
    job_type: str | None = None,
) -> float | None:
    column = _resolve_metric_column(row.keys(), candidates, job_type=job_type)
    if column is None:
        return None
    return _as_float(row.get(column))


def _normalize_chain_ids(chains: Any) -> list[str]:
    """Chain ids from ``"A"`` / ``"AB"`` / ``"A,B"`` / ``["A", "B"]``.

    A separator-free multi-character string is split per character, matching the
    ``ipSAE_{Chn1}{Chn2}`` key format (which is only unambiguous for
    single-character chain ids). Pass a list for multi-character ids.
    """
    if chains is None:
        return []
    out: list[str] = []
    if isinstance(chains, str):
        tokens = [t for t in _RESID_SEPARATORS.split(chains.strip()) if t]
        if len(tokens) == 1 and len(tokens[0]) > 1:
            tokens = list(tokens[0])
        out = [t.strip() for t in tokens if t.strip()]
    elif isinstance(chains, Iterable):
        for item in chains:
            out.extend(_normalize_chain_ids(item))
    else:
        out = [str(chains).strip()]
    seen: set[str] = set()
    unique: list[str] = []
    for chain in out:
        if chain and chain not in seen:
            seen.add(chain)
            unique.append(chain)
    return unique


def ipsae_min_from_pair_columns(
    row: Mapping[str, Any],
    binder_chain: str,
    target_chains: Any,
    *,
    job_type: str | None = None,
) -> float | None:
    """Per-seed ipSAE_min for one design row of a metrics / batch-aggregate CSV.

    Anthropic's ``ipSAE_min`` is "min over both alignment directions, then max
    over seeds, then combine across arms". THIS FUNCTION IS THE PER-SEED PART
    ONLY -- the max over seeds belongs to the caller, which holds the per-seed
    rows.

    ``run_esmc.py::_ipsae_columns`` (the esmfold2 arms) emits one
    ``ipSAE_{Chn1}{Chn2}`` column per ORDERED chain pair (``ipSAE_AB``,
    ``ipSAE_BA``) plus a symmetric ``ipSAE_{XY}_max`` (chain letters sorted).

    PROTENIX EMITS THE SAME SPELLING.
    ``process_outputs.py::_protenix_ipsae_columns`` (tamarind-utils
    **origin/main**) runs the shared
    ipsae.py per sample and merges ``ipSAE_{Chn1}{Chn2}`` (asym rows) and
    ``ipSAE_{XY}_max`` (sorted pair) into metrics.csv, alongside pDockQ_* /
    pDockQ2_*. ``runIpsae`` IS a protenix setting and DEFAULTS TO TRUE. A real
    2-chain protenix job carries ipSAE_AB=0.83467 / ipSAE_BA=0.878154 /
    ipSAE_AB_max, and this function returns 0.83467 for it.

    An intermediate version of this docstring claimed the opposite — "there is
    no protenix equivalent" — after reading a STALE tamarind-utils working tree
    (the producer landed 2026-07-31) plus a MONOMER job, where ipSAE is
    correctly absent because it is an INTERCHAIN score. Both retractions are
    recorded because this docstring is a RUNTIME INPUT, not documentation:
    ``code_analysis.py`` allowlists this function and prepends this text
    verbatim into the sandbox analysis code the QA model reads, so a wrong
    sentence here is a wrong instruction to the model.

    ipSAE is still CONDITIONAL on every arm, protenix included: it is skipped
    for a monomer construct, and for a sample with no per-residue confidence
    sidecar. Those two do NOT warn alike. The monomer case is gated BEFORE the
    producer runs (``if run_ipsae and is_multimer``), so nothing is recorded and
    the warning block emits NOTHING -- and so does a run that scored no
    interface at all (protein+ligand), which returns an empty table the caller
    treats as a correct empty result. Only an absent confidence sidecar, or an
    ipSAE run that raised, warns. Never read "no warning" as "column present". So
    ``None`` from this function means "this row carries no ipSAE" — a real and
    expected state — and the caller must decide whether that is legitimate
    (monomer) or a gap to surface. Never infer from ``None`` that the ARM cannot
    produce ipSAE.
    In a batch aggregate every column is suffixed ``" - {jobType}"``; both
    spellings are accepted. A row carrying BOTH spellings of one column, or two
    arms' spellings, raises ``ValueError`` rather than guessing -- pass
    ``job_type`` to name the arm, and the labelled column then wins over the
    unlabelled one.

    v1 semantics (plan 3.4b)::

        ipSAE_min = max over target protomers X of min(ipSAE_XC, ipSAE_CX)

    where ``C`` is the binder chain. Union-mask ipSAE is provably NOT
    reconstructible from these pair scalars -- merging protomers changes
    ``n0res`` -> ``d0`` -> every ``ptm_func`` term -- so this is the shipped
    definition and every row must be stamped ``IPSAE_MASK_STAMP``.

    FOR A SINGLE-CHAIN TARGET THIS IS EXACTLY ANTHROPIC'S DEFINITION -- the max
    over one protomer collapses away and what remains is the min over the two
    alignment directions. Zero deviation. Prefer single-chain scoring constructs
    where the biology permits.

    Deliberately does NOT read ``ipSAE_{XY}_max``: that column is the MAX over
    the two directions, the opposite of the min this metric requires.

    Returns ``None`` -- never 0.0, never NaN -- when either direction of any
    requested protomer pair is missing or unparseable, so an incomplete row can
    never masquerade as a weak-but-real score.
    """
    if not isinstance(row, Mapping):
        raise TypeError("row must be a metrics-CSV row mapping")
    binder = str(binder_chain or "").strip()
    if not binder:
        raise ValueError("binder_chain is required")
    targets = _normalize_chain_ids(target_chains)
    if not targets:
        raise ValueError("target_chains is required (the target protomer chain ids)")
    if binder in targets:
        raise ValueError(f"binder_chain {binder!r} must not appear in target_chains {targets}")

    best: float | None = None
    for chain in targets:
        forward = _row_float(row, (f"ipSAE_{chain}{binder}",), job_type=job_type)
        reverse = _row_float(row, (f"ipSAE_{binder}{chain}",), job_type=job_type)
        if forward is None or reverse is None:
            return None
        per_protomer = min(forward, reverse)
        best = per_protomer if best is None else max(best, per_protomer)
    return best


# process_dockq() writes results.csv with GlobalDockQ / best_dockq /
# best_mapping_str / {sorted(pair)}_DockQ. The BATCH aggregate for a dockq batch
# does NOT go through that file: dockq is absent from BATCH_CSV_CONFIG, so it
# falls through generate_generic_csv_each_row_is_variant, whose score names come
# from get_output_value ("Global DockQ", "Best DockQ", "Best Mapping Str",
# "{sorted(pair)}_DockQ") and are then suffixed " - dockq". Both spellings are
# accepted here because a caller may hold either table.
#
# PROVENANCE, stated because this module is the one that got burned by an
# unstated one: these CSV spellings are read off the PRODUCER on
# tamarind-utils@origin/main (process_outputs.process_dockq and
# run_scripts/dockq_to_csv.py), NOT off an observed file. All 8 archived dockq
# jobs on the platform predate that producer and carry only results.json, where
# the per-interface values are NESTED (best_result.{pair}.DockQ, bare pair keys)
# rather than flat. What IS observed on a real job (41oc3) is GlobalDockQ as a
# results.json key, best_mapping_str as "MODEL:NATIVE", and the DDB Score
# field's space-separated "Global DockQ" / "Best DockQ" — which is why both
# spellings are accepted below.
_DOCKQ_GLOBAL_COLUMNS = ("GlobalDockQ", "Global DockQ")

# NEVER read. Upstream's field of this name is the SUM over interfaces for the
# winning mapping — observed at 1.2132 on a 0-to-1 metric in real job 41oc3 —
# and our converter redefines it as the MAX. So it is neither Anthropic's
# sc_DockQ nor comparable to GlobalDockQ under either definition. Named only so
# tests can assert it is not consulted.
_DOCKQ_NEVER_READ_COLUMNS = ("best_dockq", "Best DockQ")


def _split_chain_roles(native_chain_map: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """``{chain: role}`` -> ``(binder_chains, target_chains)``.

    A role token starting with ``binder`` (case-insensitive) marks the binder;
    every other chain is a target protomer.
    """
    if not isinstance(native_chain_map, Mapping) or not native_chain_map:
        raise ValueError(
            "native_chain_map must map every NATIVE chain id to a role, "
            "e.g. {'A': 'target', 'B': 'target', 'C': 'binder'}"
        )
    binders: list[str] = []
    targets: list[str] = []
    for chain, role in native_chain_map.items():
        name = str(chain).strip()
        if not name:
            continue
        if str(role).strip().lower().startswith("binder"):
            binders.append(name)
        else:
            targets.append(name)
    if not binders or not targets:
        raise ValueError(
            f"native_chain_map needs at least one binder and one target chain; got "
            f"binders={binders} targets={targets}"
        )
    return binders, targets


# Columns that may carry the per-design id in a scores CSV. "_index" and
# "Job Name" are what generate_generic_csv_each_row_is_variant stamps.
_DESIGN_ID_COLUMNS = (
    "design_id",
    "design",
    "_index",
    "id",
    "name",
    "design_name",
    "job name",
    "jobname",
    "job_name",
    "label",
    "complex",
    "pdb_filepath",
    "pdb path",
    "pdb_path",
)

# ``scoring_batch.sanitize_design_id`` and ``_COLLISION_SUFFIX_RE``,
# RE-IMPLEMENTED rather than imported: this module is INLINED into the E2B
# sandbox, where ``campaign.cda.tools.scoring_batch`` does not exist, so an
# import (even a deferred one) is a NameError minutes into a scoring run.
# ``test_the_local_sanitizer_matches_the_builders`` pins them together.
_SANITIZE_NON_TOKEN = re.compile(r"[^A-Za-z0-9_]+")
_SANITIZE_RUNS = re.compile(r"_{2,}")
# The shape that sanitizer emits, i.e. the design half of a member job name.
_MEMBER_DESIGN_TOKEN = re.compile(r"^[A-Za-z0-9_]+$")
# ``resolve_scoring_member_names`` appends ``_2``, ``_3``, ... (never ``_0``/``_1``).
_COLLISION_SUFFIX_RE = re.compile(r"_(?:[2-9]|[1-9]\d+)$")


def _sanitized_design_token(design_id: Any) -> str:
    cleaned = _SANITIZE_NON_TOKEN.sub("_", str(design_id or "").strip())
    return _SANITIZE_RUNS.sub("_", cleaned).strip("_")


def _member_design_token(cell: str) -> str | None:
    """The design token of a member-job-name cell, or ``None``.

    ``scoring_member_job_name`` builds ``{batch}-{sanitize_design_id(id)}`` and
    the sanitizer maps ``-`` to ``_``, so the design token never contains ``-``
    and the tail after the LAST ``-`` IS the token, whatever the batch holds.
    """
    tail = cell.rsplit("-", 1)[-1]
    return tail if _MEMBER_DESIGN_TOKEN.match(tail) else None


def _member_token_matches_design(token: str, sanitized: str, digest: str) -> bool:
    """Was ``token`` built by ``resolve_scoring_member_names`` for this design?

    Three spellings, all EXACT replays of that builder, never prefix guesses:
    the plain sanitized token; ``"design"``, substituted for an id that
    sanitizes to nothing; and ``{head}_{sha1(design_id)[:8]}``, the truncation
    an over-long token gets. The digest is over the ORIGINAL id, so a token
    carrying it was built from THIS design and no other. Without that arm a long
    id joined nothing and its score was silently dropped from the panel.
    """
    if not token:
        return False
    if token == (sanitized or "design"):
        return True
    if len(token) > 9 and token.endswith(f"_{digest}"):
        head = token[:-9]
        return bool(head) and sanitized.startswith(head)
    return False


def _token_is_collision_ambiguous(token: str, table_tokens: set[str]) -> bool:
    """Does this table show BOTH spellings of a sanitize collision for ``token``?

    ``a-1`` and ``a_1`` both sanitize to ``a_1``, so the builder names the second
    member ``a_1_2``. That discriminator is POSITIONAL over its pool and is not
    recoverable from the string, so the sanitized token alone points at the wrong
    row. The evidence is that BOTH spellings appear; a numeric tail on its own is
    NOT evidence (real ids are spelled ``design_spec_402``). Same rule as
    ``load_pose_source_rows``' ``ambiguous_tokens``.
    """
    if not token:
        return False
    base = _COLLISION_SUFFIX_RE.sub("", token)
    if base != token and base in table_tokens:
        return True
    return any(
        other != token and _COLLISION_SUFFIX_RE.sub("", other) == token
        for other in table_tokens
    )


def _find_row_by_design_id(
    rows: Iterable[Any],
    design_id: str,
    *,
    score_job_name: str | None = None,
    design_id_by_job_name: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """THE row for one design, or ``None``. Never a guess.

    AMBIGUITY IS REFUSED, never resolved by position. All three pose arms carry
    jobType ``dockq``, so an sc_DockQ read off a sibling arm's row is a plausible
    number nothing downstream can catch -- and because ``pose_dockq`` is the MIN
    over arms, the best arm's PASS ships in place of the worst arm's REJECT.

    Scopes, strongest first. ``design_id_by_job_name`` is the builder's
    ``{member job name: design id}`` map, carried on every buildScoringBatch
    result; it is AUTHORITATIVE because it is the only inverse of the member-name
    transform that survives a sanitize collision or an over-long id's
    truncation-plus-sha1, and ONE arm's map scopes the read to that arm.
    ``score_job_name`` names one exact MolDB long-form observation arm.

    Unscoped, three ordered passes over the id columns: exact cell equality; then
    the member-name tail, because a ``{batch}-scores.csv`` carries
    ``{batch}-{sanitize_design_id(id)}`` and NEVER the bare id; then a
    boundary-anchored token match so a path-encoded id
    (``.../d_7_model_1.pdb``) still joins. The token pass SKIPS a cell whose
    member tail names a DIFFERENT design -- ``_`` is not in that pattern's
    boundary class, so ``d_42`` otherwise matches inside ``d_42_2``.

    More than one row surviving every scope the caller supplied RAISES.
    """
    wanted = str(design_id or "").strip()
    if not wanted:
        raise ValueError("design_id is required")
    materialized = [row for row in rows if isinstance(row, Mapping)]
    if not materialized:
        return None
    lowered_wanted = wanted.lower()

    def id_cells(row: Mapping[str, Any]) -> list[str]:
        cells: list[str] = []
        for column in _DESIGN_ID_COLUMNS:
            try:
                actual = _resolve_metric_column(row.keys(), (column,))
            except ValueError:
                # An id column spelled two ways is not worth aborting a join
                # over -- the remaining id columns can still resolve the row.
                continue
            if actual is None:
                continue
            value = str(row.get(actual) or "").strip()
            if value:
                cells.append(value)
        return cells

    def rows_where(pred: Any) -> list[dict[str, Any]]:
        return [
            dict(row) for row in materialized if any(pred(c) for c in id_cells(row))
        ]

    if design_id_by_job_name is not None:
        if not isinstance(design_id_by_job_name, Mapping):
            raise TypeError(
                "design_id_by_job_name must map member job name -> design id"
            )
        by_name = {
            str(name).strip().lower(): str(value).strip()
            for name, value in design_id_by_job_name.items()
            if str(name).strip()
        }
        table_names = {cell.lower() for row in materialized for cell in id_cells(row)}
        if by_name and table_names and not (by_name.keys() & table_names):
            raise ValueError(
                "design_id_by_job_name names none of the jobs in this table, so "
                "it cannot scope anything: pass the map returned by the batch "
                f"whose rows these are (map has e.g. {sorted(by_name)[0]!r}; the "
                f"table has e.g. {sorted(table_names)[0]!r})."
            )
        mine = {n for n, v in by_name.items() if v.lower() == lowered_wanted}
        matches = rows_where(lambda c: c.lower() in mine)
    else:
        sanitized = _sanitized_design_token(wanted).lower()
        digest = hashlib.sha1(
            wanted.encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:8]
        matches = rows_where(lambda c: c.lower() == lowered_wanted)
        if not matches:
            # A sanitize collision is resolved by POSITION over the builder's
            # pool, so once the table shows both spellings the sanitized token
            # names neither design. Refuse BEFORE matching -- the row it would
            # otherwise pick is the other design's, and its DockQ is a plausible
            # number nothing downstream can contradict.
            table_tokens = {
                (_member_design_token(c) or "").lower()
                for row in materialized
                for c in id_cells(row)
            } - {""}
            if sanitized and _token_is_collision_ambiguous(sanitized, table_tokens):
                raise ValueError(
                    f"design {design_id!r} sanitizes to member token "
                    f"{sanitized!r}, and this table carries both that token and "
                    "a discriminated spelling of it. That is the signature of a "
                    "sanitize collision, whose '_2' discriminator is POSITIONAL "
                    "and cannot be re-derived from the id, so matching on the "
                    "token would read the other design's row. Pass the batch's "
                    "design_id_by_job_name, the only inverse of that transform."
                )
            matches = rows_where(
                lambda c: _member_token_matches_design(
                    (_member_design_token(c) or "").lower(), sanitized, digest
                )
            )
        if not matches:
            token = re.compile(
                rf"(?<![A-Za-z0-9]){re.escape(wanted)}(?![A-Za-z0-9])", re.IGNORECASE
            )

            def token_hit(cell: str) -> bool:
                other = _member_design_token(cell)
                if other is not None and other.lower() not in (
                    lowered_wanted,
                    sanitized,
                ):
                    return False
                return bool(token.search(cell))

            matches = rows_where(token_hit)
    if not matches:
        return None

    requested_job_name = str(score_job_name or "").strip()
    if requested_job_name:
        matches = [
            row
            for row in matches
            if str(row.get("score_job_name") or "").strip() == requested_job_name
        ]
        if not matches:
            return None
    else:
        named_arms = {
            str(row.get("score_job_name") or "").strip()
            for row in matches
            if str(row.get("score_job_name") or "").strip()
        }
        if len(named_arms) > 1:
            raise ValueError(
                "multiple score_job_name observation arms match design "
                f"{design_id!r}; pass one exact score_job_name"
            )
        if named_arms:
            only_arm = next(iter(named_arms))
            matches = [
                row
                for row in matches
                if str(row.get("score_job_name") or "").strip() == only_arm
            ]
    if len(matches) > 1:
        raise ValueError(
            f"{len(matches)} rows match design {design_id!r} after every scope "
            "supplied. All three pose arms carry jobType 'dockq', so nothing "
            "downstream can tell their rows apart and picking one would ship an "
            "arm's score under another arm's name. Pass the batch's "
            "design_id_by_job_name (one arm's map scopes the read to that arm), "
            "or an exact score_job_name for a MolDB long-form table."
        )
    return matches[0]


def _declared_interface_tokens(
    expected_interfaces: Any,
    available: Mapping[str, str],
) -> set[str]:
    """Normalize a declared interface set to ``{sorted(pair)}`` tokens.

    Accepts ``"AC"``, ``"A,C"`` or ``("A", "C")``. A token that is not a
    binder<->target pair of ``native_chain_map`` RAISES: it would set a
    denominator describing a different complex than the one being scored.
    """
    if isinstance(expected_interfaces, (str, bytes)) or not isinstance(
        expected_interfaces, Iterable
    ):
        raise ValueError(
            "expected_interfaces must be a collection of binder<->target chain "
            f"pairs, e.g. ['AC', 'BC']; got {expected_interfaces!r}"
        )
    declared: set[str] = set()
    for item in expected_interfaces:
        chains = _normalize_chain_ids(item)
        if len(chains) != 2:
            raise ValueError(
                f"expected_interfaces entry {item!r} does not name exactly two "
                "chains; spell each interface as a pair, e.g. 'AC'"
            )
        token = "".join(sorted(chains))
        if token not in available:
            raise ValueError(
                f"expected_interfaces names {token!r}, which is not a "
                "binder<->target interface of native_chain_map (those are "
                f"{sorted(available)})."
            )
        declared.add(token)
    if not declared:
        raise ValueError(
            "expected_interfaces is empty; omit it to expect every "
            f"binder<->target pair ({sorted(available)})."
        )
    return declared


def sc_dockq_from_batch_csv(
    rows: Iterable[Any],
    design_id: str,
    native_chain_map: Mapping[str, Any],
    *,
    job_type: str | None = None,
    score_job_name: str | None = None,
    design_id_by_job_name: Mapping[str, Any] | None = None,
    expected_interfaces: Any = None,
) -> float | None:
    """sc_DockQ for one design from a ``dockq`` batch aggregate CSV.

    DockQ v2 already argmaxes over chain mappings (it reports
    ``best_mapping_str``), so NO symmetric-relabeling enumeration is needed here.

    Two-chain native (one binder + one target protomer)
        return ``GlobalDockQ``.

    Multimeric native (>2 chains)
        do NOT use ``GlobalDockQ``: it averages the target-target interfaces in
        alongside the one we care about. Take the mean over the target<->binder
        per-interface columns only (``{sorted(pair)}_DockQ``, e.g. ``AC_DockQ``).

        THE DENOMINATOR IS DECLARED, NEVER INFERRED FROM THE TABLE. It is the
        binder<->target pair count of ``native_chain_map``, or exactly the set
        named in ``expected_interfaces``, and every one of those columns must be
        present and parseable or this REFUSES. Averaging over "whatever columns
        happened to be there" is the defect that rule exists to stop: on an
        ``{AC, BC}`` native a table that lost ``BC`` scores ``{AC: 0.80}`` as
        0.80 where the truth is 0.45 -- a REJECT shipped as a PASS, with no
        signal that the mean ran over one term.

    ``best_dockq`` / ``Best DockQ`` is NEVER read: our converter redefines it as
    the max over interfaces. Both the per-job ``results.csv`` spelling
    (``GlobalDockQ``, ``AB_DockQ``) and the batch-aggregate spelling
    (``Global DockQ - dockq``) are accepted; a table carrying both raises, so
    pass ``job_type="dockq"`` to name the arm.

    SCOPING TO ONE ARM -- see ``_find_row_by_design_id``. Pass
    ``design_id_by_job_name`` (the arm's own buildScoringBatch map; the scope
    that works on a ``{batch}-scores.csv``, whose ``Job Name`` carries the member
    job name and never the bare design id) or ``score_job_name`` (one MolDB
    long-form arm). With neither, a design matching rows from more than one arm
    RAISES rather than returning the first observation.

    Returns ``None`` when the design has no row, when the two-chain
    ``GlobalDockQ`` cell is missing/unparseable, or when a multimeric row exposes
    NO target<->binder interface at all (no pose data, as opposed to partial).

    RAISES when a multimeric row exposes SOME but not all expected interfaces.
    That gap reads two ways -- a truncated table, or a protomer the binder
    genuinely does not touch (DockQ only emits interfaces present in the native)
    -- and nothing in the row separates them. Name the interfaces this native
    forms in ``expected_interfaces`` (e.g. ``["AC"]``); that then IS the
    denominator.

    ``native_chain_map`` maps every NATIVE chain id to a role token; a role
    starting with ``binder`` marks the binder. A map without both a binder and a
    target raises -- a caller bug, not a data condition.
    """
    binders, targets = _split_chain_roles(native_chain_map)
    row = _find_row_by_design_id(
        rows,
        design_id,
        score_job_name=score_job_name,
        design_id_by_job_name=design_id_by_job_name,
    )
    if row is None:
        return None

    if len(binders) + len(targets) == 2:
        return _row_float(row, _DOCKQ_GLOBAL_COLUMNS, job_type=job_type)

    # Every binder<->target pair the ROLES describe, as column names.
    available = {
        "".join(sorted((b, t))): f"{''.join(sorted((b, t)))}_DockQ"
        for b in binders
        for t in targets
    }
    expected = (
        set(available)
        if expected_interfaces is None
        else _declared_interface_tokens(expected_interfaces, available)
    )

    found: dict[str, float] = {}
    missing: list[str] = []
    for token in sorted(expected):
        value = _row_float(row, (available[token],), job_type=job_type)
        if value is None:
            missing.append(token)
        else:
            found[token] = value

    if not found:
        # No pose data at all -- a condition the caller already reads as "no
        # score", not a partial mean.
        return None
    if missing:
        raise ValueError(
            f"design {design_id!r} exposes {len(found)} of {len(expected)} "
            f"expected target<->binder DockQ interfaces: have {sorted(found)}, "
            f"missing {missing} (columns {[available[t] for t in missing]}"
            + (f", arm {job_type!r}" if job_type else "")
            + "). The denominator is declared, so this will not average over "
            "the ones that happen to be present: a missing interface is either "
            "a truncated/mis-typed table or a protomer the binder does not "
            "touch, and those give different scores. If this native genuinely "
            f"forms only {sorted(found)}, pass expected_interfaces="
            f"{sorted(found)!r}; otherwise re-read the aggregate (and pass "
            "job_type to name the arm if its columns are suffixed)."
        )
    return sum(found.values()) / len(found)


# ---------------------------------------------------------------------------
# mmCIF -> PDB, in-sandbox (the FALLBACK route for a .cif structure)
# ---------------------------------------------------------------------------
#
# ``dockq`` takes only ``.pdb``; some generators emit ``.cif``. The platform's
# ``file-converter`` JOB stays the FIRST choice -- this is the fallback, the
# same MMCIFParser -> PDBIO call plus the refusal that job lacks. Route, limits,
# evidence: ``CIF_TO_PDB_SANDBOX_FALLBACK`` in campaign/tools/scoring_batch.py.

# PDB fixed-column ceilings. Not style choices -- the format cannot encode past
# them, and Biopython's own objections arrive MID-WRITE and vary by version.
PDB_MAX_ATOM_SERIAL = 99_999
PDB_MAX_RESSEQ = 9_999
PDB_MIN_RESSEQ = -999


class CifToPdbError(Exception):
    """The structure cannot be represented in PDB without corrupting it."""


def _structure_census(structure) -> tuple[dict[str, int], dict[str, int]]:
    """``(chain -> residue count, chain -> atom count)`` for model 0.

    No model -> :class:`CifToPdbError`, never ``StopIteration``: a write cut
    before its first ATOM record parses to exactly that, and ``StopIteration``
    escapes an ``except CifToPdbError`` handler.
    """
    residues: dict[str, int] = {}
    atoms: dict[str, int] = {}
    try:
        model = next(iter(structure))
    except StopIteration:
        raise CifToPdbError("structure contains no model") from None
    for chain in model:
        n_res = 0
        n_atm = 0
        for residue in chain:
            n_res += 1
            n_atm += sum(1 for _ in residue)
        residues[chain.id] = n_res
        atoms[chain.id] = n_atm
    return residues, atoms


def cif_to_pdb_text(cif_path: str) -> tuple[str, dict[str, Any]]:
    """``(pdb_text, census)`` for one mmCIF, or raise :class:`CifToPdbError`.

    THE REFUSAL IS THE POINT. PDB is fixed-column: ``chainID`` is ONE column,
    ``serial`` five, ``resSeq`` four. Every limit is checked HERE, before any
    write, as one typed :class:`CifToPdbError` -- a wrong pose score is strictly
    worse than none, because a missing one is disclosed NOT_RUN while a wrong
    one gets RANKED.

    ``census`` is the chain ids and per-chain residue / atom counts read from
    the mmCIF: hand it to :func:`verify_pdb_matches` to assert the PDB still
    describes the same thing.
    """
    from Bio.PDB import PDBIO, MMCIFParser

    structure = MMCIFParser(QUIET=True).get_structure("structure", cif_path)

    try:
        model = next(iter(structure))
    except StopIteration:
        raise CifToPdbError("mmCIF contains no model") from None

    chains = list(model)
    if not chains:
        raise CifToPdbError("mmCIF model contains no chains")

    total_atoms = 0
    for chain in chains:
        if len(str(chain.id)) != 1:
            raise CifToPdbError(
                f"chain id {chain.id!r} is {len(str(chain.id))} characters; PDB "
                "allows exactly 1. Converting would rename or drop it, and the "
                "binder/target mapping would no longer be recoverable."
            )
        for residue in chain:
            resseq = residue.id[1]
            if not (PDB_MIN_RESSEQ <= resseq <= PDB_MAX_RESSEQ):
                raise CifToPdbError(
                    f"residue number {resseq} in chain {chain.id} is outside the "
                    f"PDB range [{PDB_MIN_RESSEQ}, {PDB_MAX_RESSEQ}]"
                )
            total_atoms += sum(1 for _ in residue)

    if total_atoms == 0:
        raise CifToPdbError("mmCIF contains no atoms")
    if total_atoms > PDB_MAX_ATOM_SERIAL:
        raise CifToPdbError(
            f"{total_atoms} atoms exceeds the PDB serial ceiling of "
            f"{PDB_MAX_ATOM_SERIAL}; serials would wrap and the file would be "
            "silently wrong"
        )

    residues, atoms = _structure_census(structure)

    handle = io.StringIO()
    writer = PDBIO()
    writer.set_structure(structure)
    writer.save(handle)
    return handle.getvalue(), {
        "chains": sorted(residues),
        "residues_per_chain": residues,
        "atoms_per_chain": atoms,
        "total_atoms": total_atoms,
    }


def verify_pdb_matches(pdb_text: str, census: Mapping[str, Any]) -> None:
    """Re-parse the PDB just written and assert it still describes the mmCIF.

    Catches a SILENT truncation -- the one failure the guards in
    :func:`cif_to_pdb_text` cannot see, because they run BEFORE the write.
    Raises :class:`CifToPdbError` on any disagreement. Run it before the
    ``.pdb`` reaches dockq, never after reading the score.
    """
    from Bio.PDB import PDBParser
    from Bio.PDB.PDBExceptions import PDBException

    # Biopython's own failures become CifToPdbError too (empty file -> bare
    # ValueError). FAILING TO RE-READ WHAT WE JUST WROTE IS A FAILED CONVERSION.
    try:
        structure = PDBParser(QUIET=True).get_structure("rt", io.StringIO(pdb_text))
        residues, atoms = _structure_census(structure)
    except CifToPdbError:
        raise
    except (PDBException, ValueError) as exc:
        raise CifToPdbError(
            f"the PDB just written could not be re-read ({exc}); treat it as a "
            "failed conversion, never as a structure to score"
        ) from exc

    if sorted(residues) != list(census["chains"]):
        raise CifToPdbError(
            f"chains changed in conversion: {list(census['chains'])} -> {sorted(residues)}"
        )
    for cid in census["chains"]:
        if residues[cid] != census["residues_per_chain"][cid]:
            raise CifToPdbError(
                f"chain {cid} residue count changed: "
                f"{census['residues_per_chain'][cid]} -> {residues[cid]}"
            )
        if atoms[cid] != census["atoms_per_chain"][cid]:
            raise CifToPdbError(
                f"chain {cid} atom count changed: "
                f"{census['atoms_per_chain'][cid]} -> {atoms[cid]}"
            )


# ---------------------------------------------------------------------------
# Sequence liability gates (the LCP substitute)
# ---------------------------------------------------------------------------

_HYDROPHOBIC_RESIDUES = frozenset("AVILMFWYC")

# Windowed-composition defaults, calibrated on real folds. Worst 12-residue
# window entropy observed: ubiquitin 2.59, barstar 2.63, GB1 2.09, an affibody
# 2.46, a de novo 3-helix bundle 2.63 -- so natural and de novo sequences sit in
# a ~2.1-2.6 bit band. An idealized "SEEEAKKLAEEAKKQ..." repeat helix drops to
# 1.83 and a "GGGGGG SSSSSS" stretch to 1.0. The 2.0-bit default therefore sits
# just under the natural band; freeze a per-target value at the validation gate
# if a target's controls argue for a different one.
_COMPOSITION_WINDOW = 12
_LOW_ENTROPY_THRESHOLD_BITS = 2.0
_HYDROPHOBIC_PATCH_THRESHOLD = 0.75
_DEFAULT_MAX_HOMOPOLYMER_RUN = 4


def _clean_sequence(sequence: Any) -> str:
    """Uppercase single-letter residues only (whitespace / digits dropped)."""
    return "".join(ch for ch in str(sequence or "").upper() if ch.isalpha())


def _shannon_entropy_bits(window: str) -> float:
    if not window:
        return 0.0
    counts = Counter(window)
    total = len(window)
    bits = -sum((n / total) * math.log2(n / total) for n in counts.values() if n)
    return max(0.0, bits)  # a single-residue window computes to -0.0


def _windows(sequence: str, window: int) -> list[tuple[int, str]]:
    """``(1-based start, window text)``; the whole sequence when it is shorter."""
    if not sequence:
        return []
    if len(sequence) <= window:
        return [(1, sequence)]
    return [
        (start + 1, sequence[start : start + window]) for start in range(len(sequence) - window + 1)
    ]


def cys_parity_flag(sequence: Any) -> dict[str, Any]:
    """Odd cysteine count = an unpaired thiol = a liability.

    Returns the count, the parity, the 1-based positions and the flag. An empty
    or non-residue sequence returns ``flag=True`` with an ``error`` -- fail
    closed, so an unreadable sequence can never pass the gate silently.
    """
    cleaned = _clean_sequence(sequence)
    if not cleaned:
        return {
            "sequence_length": 0,
            "n_cys": None,
            "parity": None,
            "positions": [],
            "flag": True,
            "error": "empty or non-residue sequence",
        }
    positions = [i + 1 for i, residue in enumerate(cleaned) if residue == "C"]
    n_cys = len(positions)
    return {
        "sequence_length": len(cleaned),
        "n_cys": n_cys,
        "parity": "odd" if n_cys % 2 else "even",
        "positions": positions,
        "flag": bool(n_cys % 2),
    }


def homopolymer_run_flag(
    sequence: Any,
    max_run: int = _DEFAULT_MAX_HOMOPOLYMER_RUN,
) -> dict[str, Any]:
    """Longest single-residue run, its residue and position, vs ``max_run``.

    ``max_run`` is the largest ALLOWED run, so a run of exactly ``max_run`` does
    NOT flag and ``max_run + 1`` does. Returns every offending run as numeric
    evidence, not just the worst one. An empty sequence returns ``flag=True``
    with an ``error`` (fail closed).
    """
    threshold = int(max_run)
    if threshold < 1:
        raise ValueError("max_run must be >= 1")
    cleaned = _clean_sequence(sequence)
    if not cleaned:
        return {
            "sequence_length": 0,
            "max_run": threshold,
            "longest_run": None,
            "residue": None,
            "start": None,
            "end": None,
            "runs_over_max": [],
            "flag": True,
            "error": "empty or non-residue sequence",
        }

    runs: list[dict[str, Any]] = []
    start = 0
    for index in range(1, len(cleaned) + 1):
        if index == len(cleaned) or cleaned[index] != cleaned[start]:
            runs.append(
                {
                    "residue": cleaned[start],
                    "start": start + 1,
                    "end": index,
                    "length": index - start,
                }
            )
            start = index
    worst = max(runs, key=lambda run: (run["length"], -run["start"]))
    return {
        "sequence_length": len(cleaned),
        "max_run": threshold,
        "longest_run": worst["length"],
        "residue": worst["residue"],
        "start": worst["start"],
        "end": worst["end"],
        "runs_over_max": [run for run in runs if run["length"] > threshold],
        "flag": bool(worst["length"] > threshold),
    }


def composition_liability_flags(
    sequence: Any,
    *,
    window: int = _COMPOSITION_WINDOW,
    low_entropy_threshold_bits: float = _LOW_ENTROPY_THRESHOLD_BITS,
    hydrophobic_patch_threshold: float = _HYDROPHOBIC_PATCH_THRESHOLD,
    max_homopolymer_run: int = _DEFAULT_MAX_HOMOPOLYMER_RUN,
) -> dict[str, Any]:
    """Per-sequence composition liabilities WITH the numeric evidence for each.

    NOT the LCP substitute any more: ``lcp_score`` IS reproduced (see
    ``lcp.py`` / ``qa.stamp_lcp_scores``). This is the L79-L88 liability gate
    beside it — homopolymer runs, windowed Shannon entropy over amino-acid
    composition (worst window and its 1-based position), hydrophobic-patch
    fraction. Both are kept, which is why this did not go away when LCP landed.

    Every liability returns its number, not just a boolean, so the sheet writer
    can recompute and match to 1e-4. An empty / non-residue sequence returns
    ``flagged=True`` with an ``error`` -- fail closed.
    """
    cleaned = _clean_sequence(sequence)
    base: dict[str, Any] = {
        "sequence_length": len(cleaned),
        "window": int(window),
        "low_entropy_threshold_bits": float(low_entropy_threshold_bits),
        "hydrophobic_patch_threshold": float(hydrophobic_patch_threshold),
        "lcp_substitute": False,
        "deviation": LCP_SUBSTITUTE_DEVIATION,
    }
    if int(window) < 1:
        raise ValueError("window must be >= 1")
    if not cleaned:
        return {
            **base,
            "error": "empty or non-residue sequence",
            "flags": ["unreadable_sequence"],
            "flagged": True,
        }

    entropies = [
        (start, text, _shannon_entropy_bits(text)) for start, text in _windows(cleaned, int(window))
    ]
    worst_start, worst_text, worst_bits = min(entropies, key=lambda item: (item[2], item[0]))
    mean_bits = sum(item[2] for item in entropies) / len(entropies)

    patches = [
        (
            start,
            text,
            sum(1 for residue in text if residue in _HYDROPHOBIC_RESIDUES) / len(text),
        )
        for start, text in _windows(cleaned, int(window))
    ]
    patch_start, patch_text, patch_fraction = max(patches, key=lambda item: (item[2], -item[0]))

    homopolymer = homopolymer_run_flag(cleaned, max_homopolymer_run)
    cysteine = cys_parity_flag(cleaned)

    low_entropy = bool(worst_bits < float(low_entropy_threshold_bits))
    hydrophobic_patch = bool(patch_fraction >= float(hydrophobic_patch_threshold))

    flags: list[str] = []
    if low_entropy:
        flags.append("low_composition_entropy")
    if hydrophobic_patch:
        flags.append("hydrophobic_patch")
    if homopolymer.get("flag"):
        flags.append("homopolymer_run")
    if cysteine.get("flag"):
        flags.append("odd_cys_parity")

    return {
        **base,
        "n_windows": len(entropies),
        "min_window_entropy_bits": round(worst_bits, 6),
        "min_entropy_window_start": worst_start,
        "min_entropy_window_sequence": worst_text,
        "mean_window_entropy_bits": round(mean_bits, 6),
        "low_entropy_flag": low_entropy,
        "hydrophobic_fraction": round(
            sum(1 for residue in cleaned if residue in _HYDROPHOBIC_RESIDUES) / len(cleaned), 6
        ),
        "max_hydrophobic_patch_fraction": round(patch_fraction, 6),
        "max_hydrophobic_patch_start": patch_start,
        "max_hydrophobic_patch_sequence": patch_text,
        "hydrophobic_patch_flag": hydrophobic_patch,
        "homopolymer": homopolymer,
        "cys_parity": cysteine,
        "flags": flags,
        "flagged": bool(flags),
    }


# ---------------------------------------------------------------------------
# Fold class (Anthropic's >=10% non-all-alpha fold-diversity target)
# ---------------------------------------------------------------------------

# Anthropic: "a design counts as not-all-alpha under DSSP if it has at least one
# beta-strand of >=3 consecutive E/B residues OR its helical fraction is below
# seventy percent."
_ALL_ALPHA_MIN_HELIX_FRACTION = 0.70
_MIN_BETA_STRAND_RUN = 3
# Below this helix fraction a strand-bearing fold is called all_beta rather than
# alpha_beta (a single N-terminal turn should not make a beta sandwich mixed).
_ALL_BETA_MAX_HELIX_FRACTION = 0.10

# DSSP 8-state codes plus biotite annotate_sse's 3-state a/b/c.
_SS_HELIX_CODES = frozenset("HGIhgia")
_SS_STRAND_CODES = frozenset("EBeb")
_SS_ANY_CODES = frozenset("HGIEBTSCXhgiebtscxa-. ")

FoldClass = Literal["all_alpha", "all_beta", "alpha_beta", "other", "unknown"]


def _normalize_ss_codes(codes: Any) -> str:
    """Collapse DSSP-8 / biotite-3 codes to H (helix), E (strand), C (coil)."""
    if codes is None:
        return ""
    if isinstance(codes, str):
        raw: Iterable[Any] = codes
    else:
        raw = codes
    out: list[str] = []
    for code in raw:
        text = str(code).strip() or "-"
        char = text[0]
        if char in _SS_HELIX_CODES:
            out.append("H")
        elif char in _SS_STRAND_CODES:
            out.append("E")
        else:
            out.append("C")
    return "".join(out)


def _longest_run(codes: str, symbol: str) -> int:
    best = 0
    current = 0
    for char in codes:
        current = current + 1 if char == symbol else 0
        best = max(best, current)
    return best


def _fold_class_from_ss(codes: str) -> FoldClass:
    if not codes:
        return "unknown"
    total = len(codes)
    helix_fraction = codes.count("H") / total
    has_strand = _longest_run(codes, "E") >= _MIN_BETA_STRAND_RUN
    if helix_fraction >= _ALL_ALPHA_MIN_HELIX_FRACTION and not has_strand:
        return "all_alpha"
    if has_strand:
        return "all_beta" if helix_fraction < _ALL_BETA_MAX_HELIX_FRACTION else "alpha_beta"
    return "other"


def _pdb_chain_ca_residues(text: str, chain: str | None) -> tuple[str, list[tuple[int, str]]]:
    """``(chain_id, ordered [(resseq, icode)])`` from CA records of one chain."""
    ordered: dict[str, list[tuple[int, str]]] = {}
    for line in text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if line[12:16].strip() != "CA":
            continue
        if line[17:20].strip().upper() not in _PROTEIN_RESIDUES:
            continue
        chain_id = line[21].strip() or "_"
        try:
            resseq = int(line[22:26])
        except ValueError:
            continue
        ordered.setdefault(chain_id, []).append((resseq, _normalize_ins_code(line[26])))
    if not ordered:
        return "", []
    if chain is not None:
        key = str(chain).strip() or "_"
        return key, ordered.get(key, [])
    if len(ordered) > 1:
        raise ValueError(
            f"dssp_fold_class expects a MONOMER; found chains {sorted(ordered)}. "
            "Pass chain=... to pick the binder."
        )
    only = next(iter(ordered))
    return only, ordered[only]


def _ss_from_pdb_records(text: str, chain: str | None) -> str:
    """Per-residue SS from HELIX/SHEET records, or ``""`` when there are none."""
    chain_id, residues = _pdb_chain_ca_residues(text, chain)
    if not residues:
        return ""
    index = {residue: position for position, residue in enumerate(residues)}
    codes = ["C"] * len(residues)

    def paint(start: tuple[int, str], end: tuple[int, str], symbol: str) -> bool:
        """Paint one HELIX/SHEET span; False when it names residues not present.

        A record that paints nothing must NOT count as an annotation -- otherwise
        a malformed file yields an all-coil "other" instead of "unknown", and
        "other" is counted as non-all-alpha by the fold-diversity target.
        """
        lo = index.get(start)
        hi = index.get(end)
        if lo is None or hi is None:
            return False
        if lo > hi:
            lo, hi = hi, lo
        for position in range(lo, hi + 1):
            codes[position] = symbol
        return True

    found = False
    for line in text.splitlines():
        try:
            if line.startswith("HELIX "):
                if (line[19].strip() or "_") != chain_id:
                    continue
                found |= paint(
                    (int(line[21:25]), _normalize_ins_code(line[25])),
                    (int(line[33:37]), _normalize_ins_code(line[37])),
                    "H",
                )
            elif line.startswith("SHEET "):
                if (line[21].strip() or "_") != chain_id:
                    continue
                found |= paint(
                    (int(line[22:26]), _normalize_ins_code(line[26])),
                    (int(line[33:37]), _normalize_ins_code(line[37])),
                    "E",
                )
        except (IndexError, ValueError):
            continue
    return "".join(codes) if found else ""


def _looks_like_path(text: str) -> bool:
    """True only for a plausible single-line filesystem path that exists.

    Guards ``os.path.exists`` against multi-line PDB text (and the embedded-NUL
    ``ValueError`` a raw blob can trigger).
    """
    import os

    if "\n" in text or "\x00" in text or len(text) > 4096:
        return False
    try:
        return os.path.exists(text)
    except (OSError, ValueError):
        return False


def _ss_from_biotite(path_or_text: str, chain: str | None) -> str:
    """P-SEA annotation via biotite (pre-installed in the sandbox only)."""
    try:
        import biotite.structure as struc
        import biotite.structure.io as strucio
    except ImportError:
        return ""
    import os
    import tempfile

    try:
        if _looks_like_path(path_or_text):
            array = strucio.load_structure(path_or_text)
        else:
            with tempfile.NamedTemporaryFile("w", suffix=".pdb", delete=False) as handle:
                handle.write(path_or_text)
                temp_path = handle.name
            try:
                array = strucio.load_structure(temp_path)
            finally:
                os.unlink(temp_path)
        if isinstance(array, struc.AtomArrayStack):
            array = array[0]
        array = array[struc.filter_amino_acids(array)]
        if chain is not None:
            array = array[array.chain_id == str(chain).strip()]
        return _normalize_ss_codes(list(struc.annotate_sse(array)))
    except Exception:  # noqa: BLE001 - any biotite failure degrades to "unknown"
        return ""


def dssp_fold_class(
    pdb_text_or_path: Any,
    *,
    ss_codes: Any = None,
    chain: str | None = None,
) -> FoldClass:
    """Classify a MONOMER's fold from secondary structure.

    Returns ``all_alpha`` | ``all_beta`` | ``alpha_beta`` | ``other`` |
    ``unknown``, feeding Anthropic's >=10% non-all-alpha fold-diversity target.

    Classification (thresholds are module constants)::

        all_alpha   helix fraction >= 0.70 AND no run of >= 3 consecutive E/B
        all_beta    has such a strand run AND helix fraction < 0.10
        alpha_beta  has such a strand run AND helix fraction >= 0.10
        other       no strand run and helix fraction < 0.70 (mostly coil)

    ``all_alpha`` is exactly the complement of Anthropic's "not-all-alpha"
    predicate, so ``dssp_fold_class(...) != "all_alpha"`` is their fold-diversity
    counter -- EXCEPT for ``unknown``.

    ``unknown`` means the secondary structure could NOT be determined. It must
    NOT be counted toward the diversity target and must be reported NOT_RUN; a
    gate counts as run only when its rejects are traceably absent downstream.

    Secondary structure is resolved in this order:
      1. ``ss_codes`` when given (DSSP 8-state ``HGIEBTSC-`` or biotite's
         3-state ``abc``) -- the canonical, dependency-free path;
      2. a bare SS string passed as ``pdb_text_or_path`` (no ATOM records);
      3. HELIX / SHEET records in the PDB text (a real DSSP-or-equivalent
         annotation already carried by the file);
      4. biotite's ``annotate_sse`` (P-SEA), deferred-imported -- available in
         the E2B sandbox where this module runs, absent in the app process.
    Biotite is NOT a declared dependency of this repo and none is added, which
    is why 1-3 exist and why 4 degrades to ``unknown`` rather than raising.
    """
    if ss_codes is not None:
        return _fold_class_from_ss(_normalize_ss_codes(ss_codes))

    if pdb_text_or_path is None:
        return "unknown"
    text = str(pdb_text_or_path)
    if not text.strip():
        return "unknown"

    looks_like_structure = "ATOM  " in text or "HETATM" in text
    if not looks_like_structure and "\n" not in text.strip():
        stripped = text.strip()
        if stripped and all(char in _SS_ANY_CODES for char in stripped):
            return _fold_class_from_ss(_normalize_ss_codes(stripped))

    body = text
    if not looks_like_structure and _looks_like_path(text):
        try:
            with open(text, encoding="utf-8", errors="replace") as handle:
                body = handle.read()
        except OSError:
            return "unknown"

    from_records = _ss_from_pdb_records(body, chain)
    if from_records:
        return _fold_class_from_ss(from_records)

    from_biotite = _ss_from_biotite(text if _looks_like_path(text) else body, chain)
    if from_biotite:
        return _fold_class_from_ss(from_biotite)
    return "unknown"


# ---------------------------------------------------------------------------
# Exact TM-0.90 single-linkage clustering
# ---------------------------------------------------------------------------


def tm_cluster_single_linkage(
    tm_matrix: Any,
    threshold: float = 0.90,
    *,
    symmetrize: str = "max",
) -> list[int]:
    """Single-linkage clusters over a TM-score matrix; one cluster id per row.

    This is the criterion that actually ships for the selection cap. Foldseek's
    ``easy-cluster`` hardcodes ``-c 0.9``, which is a COVERAGE threshold and a
    different criterion; the broad pass uses Foldseek, and the final panel's cap
    check uses this. 30 designs = 435 pairs, so an O(n^2) union-find is exact
    and instant.

    Single linkage, not complete linkage: ``a~b`` and ``b~c`` put a, b and c in
    one cluster even when ``TM(a,c)`` is far below ``threshold``. That is the
    defining property and it is what makes the cap conservative.

    Rows i and j are linked when the score is ``>= threshold`` (0.90 links
    exactly). TM-score is length-normalized and therefore asymmetric in general;
    ``symmetrize`` picks how the two directions collapse -- ``max`` (default,
    merges more, so the diversity cap binds harder), ``min``, ``mean``, or
    ``none`` (use ``[i][j]`` as given). Non-finite entries never link.

    Cluster ids are assigned by first appearance in row order (0, 1, 2, ...), so
    the output is deterministic and diffable.
    """
    if tm_matrix is None:
        raise ValueError("tm_matrix is required")
    rows = [list(row) for row in tm_matrix]
    size = len(rows)
    if size == 0:
        return []
    for index, row in enumerate(rows):
        if len(row) != size:
            raise ValueError(
                f"tm_matrix must be square; row {index} has {len(row)} entries, expected {size}"
            )
    mode = str(symmetrize or "max").strip().lower()
    if mode not in ("max", "min", "mean", "none"):
        raise ValueError(f"unknown symmetrize mode {symmetrize!r}")

    parent = list(range(size))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    limit = float(threshold)
    for i in range(size):
        for j in range(i + 1, size):
            forward = _as_float(rows[i][j])
            reverse = _as_float(rows[j][i])
            if mode == "none":
                score = forward
            elif forward is None or reverse is None:
                score = forward if reverse is None else reverse
                if mode == "min":
                    score = None
            elif mode == "max":
                score = max(forward, reverse)
            elif mode == "min":
                score = min(forward, reverse)
            else:
                score = (forward + reverse) / 2.0
            if score is not None and score >= limit:
                union(i, j)

    labels: dict[int, int] = {}
    out: list[int] = []
    for index in range(size):
        root = find(index)
        if root not in labels:
            labels[root] = len(labels)
        out.append(labels[root])
    return out


# ---------------------------------------------------------------------------
# Transductive z-scoring and the two summary scores
# ---------------------------------------------------------------------------


def transductive_zscore(values: Iterable[Any]) -> list[float | None]:
    """Z-score a vector against ITSELF (mu, sigma from the ranked set).

    Anthropic: "z-score is transductive (mu, sigma depend on the scored pool):
    comparable only within the batch used to calculate it". So mu/sigma are
    recomputed over whatever set is being ranked -- never against a global or
    historical reference -- and a z-score is meaningless across targets, waves
    or campaigns.

    sigma is the POPULATION standard deviation (ddof=0): the ranked set is the
    whole population being standardized, not a sample of a larger one.

    ``None`` / NaN / +-inf / unparseable entries are INELIGIBLE. They are
    excluded from mu and sigma and come back as ``None`` -- never 0.0, which
    would silently place a missing score at the pool mean.

    Zero variance (every eligible value identical) and fewer than two eligible
    values both return all ``None``: the z-score is undefined, and returning
    zeros would fabricate agreement.
    """
    parsed = [_as_float(value) for value in values]
    eligible = [value for value in parsed if value is not None]
    if len(eligible) < 2:
        return [None] * len(parsed)
    mean = sum(eligible) / len(eligible)
    variance = sum((value - mean) ** 2 for value in eligible) / len(eligible)
    sigma = math.sqrt(variance)
    if sigma <= _ZERO_VARIANCE_ATOL:
        return [None] * len(parsed)
    return [None if value is None else (value - mean) / sigma for value in parsed]


def _as_term_matrix(values: Any, label: str) -> list[list[float | None]]:
    """``[design][term]`` matrix of parsed floats; validated rectangular.

    A bare scalar entry means that design has exactly one term.
    """
    if values is None:
        raise ValueError(f"{label} is required")
    rows: list[list[float | None]] = []
    for entry in values:
        if entry is None or isinstance(entry, (str, bytes)) or not isinstance(entry, Iterable):
            rows.append([_as_float(entry)])
        else:
            rows.append([_as_float(item) for item in entry])
    widths = {len(row) for row in rows}
    if len(widths) > 1:
        raise ValueError(f"{label} is ragged: per-design term counts {sorted(widths)}")
    return rows


def _term_columns(
    ipsae_values: Any,
    scdockq_values: Any,
) -> tuple[list[list[float | None]], list[list[float | None]], list[bool]]:
    ipsae = _as_term_matrix(ipsae_values, "ipsae_values")
    dockq = _as_term_matrix(scdockq_values, "scdockq_values")
    if len(ipsae) != len(dockq):
        raise ValueError(
            f"ipsae_values has {len(ipsae)} designs but scdockq_values has {len(dockq)}"
        )
    if ipsae and not ipsae[0] and not dockq[0]:
        raise ValueError("no score terms supplied")
    eligible = [
        all(value is not None for value in ipsae[index])
        and all(value is not None for value in dockq[index])
        for index in range(len(ipsae))
    ]
    return ipsae, dockq, eligible


def rank_zscore_from_terms(
    ipsae_values: Any,
    scdockq_values: Any,
    *,
    ipsae_weight: float = 4.0,
    scdockq_weight: float = 1.0,
) -> list[float | None]:
    """Per-target 4:1 ipSAE:sc_DockQ weighted z-score average -- RANKING ONLY.

    Anthropic: "rank_zscore = the per-target weighted z-score average of the
    same six terms, with each ipSAE_min z-term weighted 4 and each sc_DockQ
    z-term weighted 1, used for ranking only". So::

        rank_zscore_i = (4 * sum_k z(ipSAE_k)_i + 1 * sum_m z(scDockQ_m)_i)
                        / (4 * n_ipsae_terms + 1 * n_dockq_terms)

    -- a weighted MEAN (denominator 15 for the standard three-arm instrument),
    not a weighted sum.

    DO NOT CONFUSE WITH ``final_score_from_terms``, which is the RAW mean of the
    same six terms and is NOT z-scored. rank_zscore ranks; final_score is the
    reported headline value. Swapping them is the single easiest thing to get
    backwards.

    Each argument is one entry per design, holding that design's per-arm values
    (``[[ef2full, ef2fast, ptxv2], ...]``); a bare scalar means one term.

    ROW-WISE NaN-REJECT. A design missing ANY of its terms is ineligible: it
    returns ``None`` AND is excluded from every term's mu/sigma, so all six
    columns stay standardized over the same population. Anthropic's rule is that
    a NaN is never a sentinel.

    If any term column has undefined z (zero variance, or <2 eligible designs)
    the whole vector is ``None`` -- a constant term carries no ranking
    information and zeroing it would fabricate agreement.
    """
    ipsae, dockq, eligible = _term_columns(ipsae_values, scdockq_values)
    count = len(ipsae)
    if count == 0:
        return []

    columns: list[list[float | None]] = []
    weights: list[float] = []
    for term in range(len(ipsae[0])):
        columns.append([ipsae[i][term] if eligible[i] else None for i in range(count)])
        weights.append(float(ipsae_weight))
    for term in range(len(dockq[0])):
        columns.append([dockq[i][term] if eligible[i] else None for i in range(count)])
        weights.append(float(scdockq_weight))

    total_weight = sum(weights)
    if total_weight == 0:
        raise ValueError("term weights sum to zero")

    z_columns = [transductive_zscore(column) for column in columns]
    out: list[float | None] = []
    for index in range(count):
        if not eligible[index]:
            out.append(None)
            continue
        accumulator = 0.0
        complete = True
        for z_column, weight in zip(z_columns, weights):
            z_value = z_column[index]
            if z_value is None:
                complete = False
                break
            accumulator += weight * z_value
        out.append(accumulator / total_weight if complete else None)
    return out


def final_score_from_terms(ipsae_values: Any, scdockq_values: Any) -> list[float | None]:
    """``final_score`` -- the RAW mean of the six terms. NOT z-scored.

    Anthropic: "final_score = mean of the six raw terms (three ipSAE_min, three
    sc_DockQ), reported as the headline value". Unweighted, un-standardized, and
    therefore comparable within a target but not across targets.

    The counterpart to ``rank_zscore_from_terms``: that one z-scores and weights
    4:1 and is for RANKING; this one does neither and is for REPORTING.

    Under a disclosed REDUCED_MASK the mean runs over the realized terms only --
    which happens naturally here by the caller passing fewer arm columns, with
    ``score_instrument`` naming them on the row. A design missing any of the
    terms it WAS given returns ``None`` (NaN-reject), never a mean over the
    survivors: that would silently change the mask per row.
    """
    ipsae, dockq, eligible = _term_columns(ipsae_values, scdockq_values)
    out: list[float | None] = []
    for index in range(len(ipsae)):
        if not eligible[index]:
            out.append(None)
            continue
        terms = [value for value in ipsae[index] + dockq[index] if value is not None]
        out.append(sum(terms) / len(terms) if terms else None)
    return out
