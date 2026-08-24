"""In-sandbox TM-score, and the target-mimic gate it exists to run.

``run_analysis_code_json`` inlines this module into the executed analysis code
the same way it inlines ``qa_analysis_helpers`` — call the functions by name and
the real logic is what runs, and what a reviewer reads in the code panel::

    screen = target_mimic_screen(
        "design_1.pdb",
        [("target.pdb", "A"), ("target.pdb", "B"), ("control_pos.pdb", "A")],
        design_chain="C",
    )
    print(screen["verdict"], screen["tm_max"])   # REJECT / PASS / NOT_RUN

WHY THIS FILE EXISTS. The playbook asserted in six places that a target-mimic
check runs and is never dropped, and named Foldseek as the tool. Foldseek is in
neither T2 resource config and has never completed a job here; ``us-align`` is
one pair per job. So the gate was prompt text with nothing behind it, while a
live campaign against PD-L1 — whose IgV domain IS an Ig fold — produced designs
carrying canonical antibody heavy-chain framework signatures. A design that
reproduces the target's own fold scores WELL on interface confidence on all
three arms, which is what makes this the failure that reaches a wet lab looking
like a success. Screening one design against a handful of NAMED chains is not a
database search, which is exactly why it fits in-sandbox where Foldseek does not.

A SEPARATE MODULE ON PURPOSE. ``qa_analysis_helpers`` is inlined whole whenever
the dependency slice cannot be bounded, and at ~99.6k characters it sits one row
of ``test_helper_source_still_leaves_room_for_analysis_code`` from its ceiling.
Keeping the TM kernel here means a mimic screen pays this module's size instead
of that one's, and the design-sheet analyses pay nothing. The cost is that this
module may not import from that one — each must stand alone once inlined — so
``_PROTEIN_RESIDUES`` and the CA reader are deliberately duplicated.

Self-contained: standard library + numpy (pre-installed in the sandbox). numpy
is imported lazily so this module still imports in the app process and in unit
tests that only read its source.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = [
    "TARGET_MIMIC_GATE_STAMP",
    "TM_MIMIC_THRESHOLD",
    "TmScoreError",
    "target_mimic_screen",
    "tm_score",
]

# Anthropic's novelty gate verbatim: "REJECT ... OR TM-score >= 0.5 to any target
# or control chain (so target-mimic protomers are caught here, not downstream)".
# 0.5 is also the literature's fold-identity line (Xu & Zhang 2010) — below it a
# pair is no more similar than two structures drawn at random.
TM_MIMIC_THRESHOLD = 0.5

TARGET_MIMIC_GATE_STAMP = "TM_ALIGN_INSANDBOX(numpy; d0 per Zhang-Skolnick 2004)"

# One design against a target ectodomain, not a database scan. The DP is
# O(n1*n2) per iteration; refusing above the cap stops a wrong input from
# stalling a scoring run for minutes and then calling the result a measurement.
MAX_CHAIN_RESIDUES = 1200

_PROTEIN_RESIDUES = frozenset(
    {
        "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU",
        "LYS", "MET", "MSE", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    }
)  # fmt: skip

_SYMMETRIZE_MODES = ("max", "min", "mean", "none")

# TM-align runs its DP refinement at two gap penalties and keeps the better
# result: -0.6 is the published value, and a zero penalty finds the register on
# pairs needing many short gaps. Dropping the 0.0 pass cost 0.03 mean / 0.07 max
# TM against reference TM-align on the validation set, so both stay.
_DP_GAP_PENALTIES = (-0.6, 0.0)

# TM-align's make_sec tolerances: the six intra-window CA distances
# (d13 d14 d15 d24 d25 d35) for an ideal helix and an ideal strand.
_HELIX_DISTANCES = (5.45, 5.18, 6.37, 5.45, 5.18, 5.45)
_STRAND_DISTANCES = (6.1, 10.4, 13.0, 6.1, 10.4, 6.1)


class TmScoreError(Exception):
    """The pair cannot be scored, so the gate is NOT_RUN — never a pass."""


def _structure_text(pdb_text_or_path: Any) -> str:
    """PDB text, from either the text itself or a path to it."""
    text = str(pdb_text_or_path or "")
    if not text.strip():
        raise TmScoreError("empty structure input")
    if "\n" in text or "ATOM  " in text or "HETATM" in text:
        return text
    try:
        with open(text, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as exc:
        raise TmScoreError(f"could not read structure {text!r}: {exc}") from exc


def _ca_coordinates(pdb_text_or_path: Any, chain: Any = None):
    """``(chain_id, (N, 3) CA array)`` for one protein chain of model 1.

    First model only (stops at ``ENDMDL``), first altloc per residue, protein
    polymer residues only — MSE kept, waters/ligands/glycans dropped, the same
    residue set ``qa_analysis_helpers`` indexes. ``chain=None`` is allowed only
    when the file holds exactly one protein chain: a design file that still
    carries its target would otherwise be scored with the TARGET as the binder,
    which reads as a perfect mimic of itself.
    """
    import numpy as np

    text = _structure_text(pdb_text_or_path)
    wanted = None if chain is None else (str(chain).strip() or "_")
    seen: set[tuple[str, int, str]] = set()
    coords: dict[str, list[tuple[float, float, float]]] = {}
    for line in text.splitlines():
        if line.startswith("ENDMDL"):
            break
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if line[12:16].strip() != "CA":
            continue
        if line[17:20].strip().upper() not in _PROTEIN_RESIDUES:
            continue
        chain_id = line[21].strip() or "_"
        if wanted is not None and chain_id != wanted:
            continue
        try:
            key = (chain_id, int(line[22:26]), line[26].strip())
            xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        except ValueError:
            continue
        if key in seen:
            continue
        seen.add(key)
        coords.setdefault(chain_id, []).append(xyz)

    if not coords:
        raise TmScoreError(
            f"no protein CA atoms in chain {wanted!r}" if wanted else "no protein CA atoms"
        )
    if wanted is None and len(coords) > 1:
        raise TmScoreError(
            f"structure holds chains {sorted(coords)}; name the chain so the binder is "
            "scored rather than whichever chain happens to come first"
        )
    chain_id = wanted if wanted is not None else next(iter(coords))
    array = np.asarray(coords[chain_id], dtype=float)
    # ``float("nan")`` parses happily out of a corrupt or truncated PDB, and a
    # non-finite coordinate does not surface until numpy raises LinAlgError
    # ("SVD did not converge") from inside the superposition search. That is not
    # a TmScoreError, so it escapes target_mimic_screen's handler and kills the
    # whole analysis instead of recording NOT_RUN for the one bad structure.
    # Catch it at the boundary, where it can still be named.
    if not np.isfinite(array).all():
        raise TmScoreError(
            f"chain {chain_id} carries a non-finite CA coordinate (NaN or inf); the "
            "structure is corrupt and cannot be scored"
        )
    if len(array) > MAX_CHAIN_RESIDUES:
        raise TmScoreError(
            f"chain {chain_id} has {len(array)} residues, above the {MAX_CHAIN_RESIDUES} cap"
        )
    return chain_id, array


def _d0(length: int) -> float:
    """Zhang & Skolnick's length-dependent normalising distance, in Angstrom.

    ``1.24 * (L - 15)^(1/3) - 1.8``, floored at 0.5 A exactly as the reference
    ``TMscore`` program floors it, so short chains keep a finite scale.
    """
    if length <= 15:
        return 0.5
    return max(0.5, 1.24 * (length - 15.0) ** (1.0 / 3.0) - 1.8)


def _superpose(mobile, fixed):
    """Kabsch rotation+translation carrying ``mobile`` onto ``fixed``."""
    import numpy as np

    mobile_center, fixed_center = mobile.mean(0), fixed.mean(0)
    left, _singular, right = np.linalg.svd((mobile - mobile_center).T @ (fixed - fixed_center))
    reflection = np.sign(np.linalg.det(right.T @ left.T))
    rotation = right.T @ np.diag([1.0, 1.0, reflection]) @ left.T
    return rotation, fixed_center - rotation @ mobile_center


def _fit_distances(moving, target, rotation, translation):
    """Squared CA distances between two paired sets after applying a transform."""
    import numpy as np

    offset = moving @ rotation.T + translation - target
    return np.einsum("ij,ij->i", offset, offset)


def _tm_from_distances(dist_sq, d0_sq: float, ref_len: int) -> float:
    """``(1/L_ref) * sum 1/(1 + (d/d0)^2)`` over already-computed distances.

    Split from :func:`_fit_distances` on purpose: the superposition search reads
    the same distances twice — once for the score, once to pick the next
    residue subset — and recomputing them there tripled the cost of a pair.
    """
    import numpy as np

    return float(np.sum(1.0 / (1.0 + dist_sq / d0_sq)) / ref_len)


def _tm_for_alignment(subject, reference, sub_idx, ref_idx, ref_len: int, d0: float):
    """``(tm, rotation, translation)`` — the published TM-score for ONE pairing.

    The MAXIMUM over rigid-body superpositions of
    ``(1/L_ref) * sum_i 1/(1 + (d_i/d0)^2)`` over the aligned pairs. The maximum
    is found the way the reference ``TMscore`` program finds it — seed on
    contiguous sub-blocks of length L, L/2, L/4 ... >= 4, then re-superimpose on
    whichever pairs fall inside a growing distance cutoff until the set stops
    changing. Every superposition visited is scored, so this is a max over a
    search, never a single fit.

    The denominator is ``ref_len``, the FULL normalising chain length, not the
    aligned count: unaligned residues contribute zero. That is what makes
    TM-score length-normalised, and asymmetric.

    The winning transform comes back too, because the alignment refinement in
    :func:`_tm_directional` steers by it: re-aligning against the TM-OPTIMAL
    superposition (which fits the well-matched core) rather than a least-squares
    fit of every current pair is what keeps the search unbiased — measured
    against reference TM-align over 462 chain pairs, mean |delta| 0.019 with
    bias -0.002, versus 0.023 and -0.016 for the least-squares variant.
    """
    import numpy as np

    # Below the reference program's L_init_min there is no sub-block to seed on,
    # so there is no search to run and no score to report.
    if len(sub_idx) < 4:
        return 0.0, np.eye(3), np.zeros(3)
    moving, target = subject[sub_idx], reference[ref_idx]
    best = 0.0
    best_rotation, best_translation = np.eye(3), np.zeros(3)
    d0_sq = d0 * d0

    # L, L/2, L/4 ... down to the reference program's L_init_min of 4. The final
    # 4 is appended when halving skipped past it (7 // 2 == 3): those short
    # blocks are what find a well-superposed core inside an otherwise poor
    # alignment, and dropping them cost 0.06 TM on PD-L1 vs ubiquitin.
    seed_lengths = []
    seed_length = len(sub_idx)
    while seed_length >= 4:
        seed_lengths.append(seed_length)
        seed_length //= 2
    if seed_lengths[-1] != 4:
        seed_lengths.append(4)
    for length in seed_lengths:
        for start in range(0, len(sub_idx) - length + 1, max(1, length // 2)):
            selected = np.arange(start, start + length)
            for _ in range(20):
                rotation, translation = _superpose(moving[selected], target[selected])
                dist_sq = _fit_distances(moving, target, rotation, translation)
                score = _tm_from_distances(dist_sq, d0_sq, ref_len)
                if score > best:
                    best, best_rotation, best_translation = score, rotation, translation
                cutoff = max(d0, 3.5)
                keep = np.flatnonzero(dist_sq < cutoff * cutoff)
                while len(keep) < 4 and cutoff < 100.0:
                    cutoff += 0.5
                    keep = np.flatnonzero(dist_sq < cutoff * cutoff)
                if len(keep) < 3 or np.array_equal(keep, selected):
                    break
                selected = keep
    return best, best_rotation, best_translation


def _needleman_wunsch(score_matrix, gap: float):
    """Global alignment maximising ``score_matrix`` under a LINEAR gap penalty.

    Vectorised per row, not per cell. For a linear (non-affine) gap the
    within-row recurrence ``H[j] = max(M[j], H[j-1] + gap)`` unrolls to
    ``H[j] = j*gap + max_{k<=j}(M[k] - k*gap)`` — a prefix maximum — so each row
    is a few numpy calls instead of an O(m) Python loop. Traceback reads the
    winner back off the stored table; the comparisons are exact because the
    stored value came from exactly those expressions.
    """
    import numpy as np

    n_rows, n_cols = score_matrix.shape
    table = np.zeros((n_rows + 1, n_cols + 1))
    ramp = np.arange(n_cols + 1, dtype=float) * gap
    for row in range(1, n_rows + 1):
        best_of_two = np.empty(n_cols + 1)
        best_of_two[0] = 0.0
        best_of_two[1:] = np.maximum(
            table[row - 1, :-1] + score_matrix[row - 1], table[row - 1, 1:] + gap
        )
        table[row] = ramp + np.maximum.accumulate(best_of_two - ramp)

    sub_idx: list[int] = []
    ref_idx: list[int] = []
    row, col = n_rows, n_cols
    while row > 0 and col > 0:
        here = table[row, col]
        if here <= table[row - 1, col - 1] + score_matrix[row - 1, col - 1] + 1e-12:
            sub_idx.append(row - 1)
            ref_idx.append(col - 1)
            row -= 1
            col -= 1
        elif here <= table[row - 1, col] + gap + 1e-12:
            row -= 1
        else:
            col -= 1
    return np.array(sub_idx[::-1], dtype=int), np.array(ref_idx[::-1], dtype=int)


def _secondary_structure(coords):
    """TM-align's ``make_sec``: coarse per-residue state from CA geometry alone.

    1 coil, 2 helix, 3 strand, 4 turn, from the six CA distances inside the
    i-2..i+2 window against TM-align's own tolerances. It exists ONLY to seed the
    alignment search and nothing else reads it — ``dssp_fold_class`` in
    ``qa_analysis_helpers`` remains the fold-class call.
    """
    import numpy as np

    n = len(coords)
    states = np.ones(n, dtype=int)
    if n < 5:
        return states
    dist = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=-1)
    i = np.arange(2, n - 2)
    window = np.stack(
        [
            dist[i - 2, i],
            dist[i - 2, i + 1],
            dist[i - 2, i + 2],
            dist[i - 1, i + 1],
            dist[i - 1, i + 2],
            dist[i, i + 2],
        ]
    )
    inner = np.ones(len(i), dtype=int)
    inner[(np.abs(window - np.array(_HELIX_DISTANCES)[:, None]) < 2.1).all(0)] = 2
    inner[(np.abs(window - np.array(_STRAND_DISTANCES)[:, None]) < 1.42).all(0)] = 3
    inner[window[2] < 8.0] = 4
    states[2 : n - 2] = inner
    return states


def _tm_directional(subject, reference, n_seeds: int, dp_iterations: int) -> float:
    """TM-score of ``subject`` onto ``reference``, normalised by len(reference).

    Alignment search, TM-align style: seed from gapless threading (every
    sequential offset, quick-scored) plus the secondary-structure alignment, then
    refine each seed with Needleman-Wunsch on the superposed
    ``1/(1 + (d/d0_search)^2)`` matrix until the correspondence stops moving.
    Every alignment the refinement visits is scored by the published
    superposition search (:func:`_tm_for_alignment`), and that search's optimal
    transform is what the next re-alignment superposes on, so the best score seen
    anywhere in the search is what comes back.
    """
    import numpy as np

    ref_len = len(reference)
    d0 = _d0(ref_len)
    d0_sq = d0 * d0
    # TM-align widens d0 for the ALIGNMENT search only (clamped to 4.5-8 A) so
    # the score matrix stays informative for distant pairs. The reported score
    # always uses the true d0 above.
    d0_search_sq = min(8.0, max(4.5, d0)) ** 2

    seeds: list[tuple[float, Any, Any]] = []
    for shift in range(-(len(subject) - 1), ref_len):
        low, high = max(0, -shift), min(len(subject), ref_len - shift)
        if high - low < 5:
            continue
        sub_idx = np.arange(low, high)
        ref_idx = sub_idx + shift
        rotation, translation = _superpose(subject[sub_idx], reference[ref_idx])
        quick = _tm_from_distances(
            _fit_distances(subject[sub_idx], reference[ref_idx], rotation, translation),
            d0_sq,
            ref_len,
        )
        seeds.append((quick, sub_idx, ref_idx))
    seeds.sort(key=lambda seed: -seed[0])
    starts = [(sub_idx, ref_idx) for _quick, sub_idx, ref_idx in seeds[: max(1, n_seeds)]]

    # TM-align's second initial alignment. It is what recovers a shared fold
    # whose sequential register no gapless threading reaches.
    ss_match = (
        _secondary_structure(subject)[:, None] == _secondary_structure(reference)[None, :]
    ).astype(float)
    ss_sub, ss_ref = _needleman_wunsch(ss_match, -1.0)
    if len(ss_sub) >= 3:
        starts.append((ss_sub, ss_ref))
    if not starts:
        return 0.0

    # Different seeds converge on the same correspondence constantly — a dozen
    # gapless-threading offsets around the right register all walk to one
    # alignment, and the trailing scoring call repeats whatever the loop last
    # scored. The superposition search is the expensive part of the whole
    # function, so scoring each distinct correspondence once cuts the cost of a
    # pair roughly in half with no effect on the result.
    #
    # The key cannot collide even though 0x7C can occur inside the index bytes:
    # the two arrays are always the SAME length (they are a pairing), so the key
    # length fixes the split point and no two distinct pairings can share one.
    scored: dict[bytes, tuple[float, Any, Any]] = {}

    def search(sub_idx, ref_idx):
        key = sub_idx.tobytes() + b"|" + ref_idx.tobytes()
        if key not in scored:
            scored[key] = _tm_for_alignment(subject, reference, sub_idx, ref_idx, ref_len, d0)
        return scored[key]

    best = 0.0
    for start_sub, start_ref in starts:
        for gap in _DP_GAP_PENALTIES:
            sub_idx, ref_idx = start_sub, start_ref
            for _ in range(max(1, dp_iterations)):
                score, rotation, translation = search(sub_idx, ref_idx)
                best = max(best, score)
                offset = (subject @ rotation.T + translation)[:, None, :] - reference[None, :, :]
                dist_sq = np.einsum("ijk,ijk->ij", offset, offset)
                next_sub, next_ref = _needleman_wunsch(1.0 / (1.0 + dist_sq / d0_search_sq), gap)
                if len(next_sub) < 3 or (
                    len(next_sub) == len(sub_idx)
                    and np.array_equal(next_sub, sub_idx)
                    and np.array_equal(next_ref, ref_idx)
                ):
                    break
                sub_idx, ref_idx = next_sub, next_ref
            best = max(best, search(sub_idx, ref_idx)[0])
    return min(1.0, max(0.0, best))


def tm_score(
    subject_pdb: Any,
    reference_pdb: Any,
    *,
    subject_chain: Any = None,
    reference_chain: Any = None,
    symmetrize: str = "none",
    n_seeds: int = 10,
    dp_iterations: int = 8,
) -> dict[str, Any]:
    """TM-score between two protein chains, structural alignment included.

    THE DEFINITION, not an approximation of it (Zhang & Skolnick, Proteins 2004)::

        TM = max over superpositions of (1 / L_ref) * SUM_i 1 / (1 + (d_i/d0)^2)
        d0 = 1.24 * (L_ref - 15)^(1/3) - 1.8            (floored at 0.5 A)

    The sum runs over aligned residue pairs; ``d_i`` is their CA distance after
    superposition; ``L_ref`` is the FULL length of the normalising chain, so
    unaligned residues cost score. The residue correspondence is found here too
    (see :func:`_tm_directional`) — that search is a heuristic, as TM-align's own
    is, but the number it reports is the formula above, exactly.

    NORMALISATION DIRECTION — the thing to get right. TM-score is asymmetric:
    normalising by a 215-residue antibody heavy chain and by a 115-residue binder
    gives 0.42 and 0.73 for the SAME superposition (measured, 1N8Z:B vs 4ZQK:A),
    and only the second answers "how much of this binder is that fold". So both
    are always computed and both come back:

      ``tm_norm_reference``  normalised by ``reference_pdb``'s chain length
      ``tm_norm_subject``    normalised by ``subject_pdb``'s chain length

    ``symmetrize`` picks which lands in ``tm_score``, with the SAME four modes
    and meanings as ``tm_cluster_single_linkage``: ``max``, ``min``, ``mean``, or
    ``none`` (the reference-normalised direction as given). Default here is
    ``none`` — the bare published quantity for the pair as named. The mimic gate
    defaults to ``max``; :func:`target_mimic_screen` says why.

    Structures are PDB text or a path to it, FIRST MODEL only. mmCIF is not read
    — convert with ``cif_to_pdb_text`` first. Raises :class:`TmScoreError` rather
    than return a number it cannot stand behind.

    Cost is ~0.2-2 s per call depending on chain lengths (both directions, one
    sandbox core). ``n_seeds`` is the accuracy/latency knob: 10 reproduces
    reference TM-align to within 0.01 above TM 0.5; 4 is ~4x faster and missed
    true mimics in the 0.50-0.58 band on the validation set. Do not lower it for
    a gate.
    """
    mode = str(symmetrize or "none").strip().lower()
    if mode not in _SYMMETRIZE_MODES:
        raise ValueError(f"unknown symmetrize mode {symmetrize!r}")
    subject_id, subject = _ca_coordinates(subject_pdb, subject_chain)
    reference_id, reference = _ca_coordinates(reference_pdb, reference_chain)
    if len(subject) < 4 or len(reference) < 4:
        raise TmScoreError(
            f"chains are too short to align ({len(subject)} vs {len(reference)} residues)"
        )

    by_reference = _tm_directional(subject, reference, n_seeds, dp_iterations)
    by_subject = _tm_directional(reference, subject, n_seeds, dp_iterations)
    if mode == "max":
        value = max(by_reference, by_subject)
    elif mode == "min":
        value = min(by_reference, by_subject)
    elif mode == "mean":
        value = (by_reference + by_subject) / 2.0
    else:
        value = by_reference
    return {
        "tm_score": value,
        "tm_norm_reference": by_reference,
        "tm_norm_subject": by_subject,
        "symmetrize": mode,
        "subject_chain": subject_id,
        "reference_chain": reference_id,
        "subject_length": len(subject),
        "reference_length": len(reference),
        "d0_reference": _d0(len(reference)),
        "stamp": TARGET_MIMIC_GATE_STAMP,
    }


def _reference_spec(entry: Any, index: int) -> tuple[Any, Any, str]:
    """Normalise one ``reference_chains`` entry to ``(pdb, chain, label)``."""
    if isinstance(entry, Mapping):
        pdb = entry.get("pdb", entry.get("pdb_path", entry.get("path")))
        chain = entry.get("chain", entry.get("chain_id"))
        return pdb, chain, str(entry.get("label") or f"{pdb}:{chain}")
    if isinstance(entry, (str, bytes)):
        raise TypeError(
            f"reference_chains[{index}] is a bare path; name a chain, so a multi-chain "
            "reference cannot be scored as though it were one fold"
        )
    if isinstance(entry, Sequence) and len(entry) >= 2:
        label = str(entry[2]) if len(entry) > 2 else f"{entry[0]}:{entry[1]}"
        return entry[0], entry[1], label
    raise TypeError(f"reference_chains[{index}] is not (pdb, chain) or a mapping")


def target_mimic_screen(
    design_pdb: Any,
    reference_chains: Iterable[Any],
    *,
    design_chain: Any = None,
    threshold: float = TM_MIMIC_THRESHOLD,
    symmetrize: str = "max",
    n_seeds: int = 10,
    dp_iterations: int = 8,
) -> dict[str, Any]:
    """The target-mimic gate: REJECT at TM-score >= threshold to ANY named chain.

    Anthropic puts this inside the novelty gate ("so target-mimic protomers are
    caught here, not downstream") and then makes it absolute: the relaxation
    ladder may loosen broad database novelty as a last resort, but "binder-chain
    target-mimic and natural-sequence-copy bans stay absolute and are never
    relaxed". Put the returned dict straight onto the candidate row as
    ``target_mimic`` and ``select_with_diversity_caps`` enforces the same ban at
    panel selection, at every rung of that ladder.

    ``reference_chains`` is EVERY target chain and EVERY control chain — the
    campaign reference structure's chains and the positive/negative controls'.
    Entries are ``(pdb, chain)``, ``(pdb, chain, label)``, or a mapping with
    ``pdb``/``chain``/``label``. A bare path is refused: a multi-chain file
    scored as one "fold" is not a chain comparison.

    ``symmetrize="max"`` by DEFAULT, unlike :func:`tm_score`. A 115-residue
    design reproducing one domain of a 215-residue target chain scores 0.42
    normalised by the target and 0.73 normalised by the design, and only the
    second says "this design is that fold". Taking the max rejects on either —
    the direction ``tm_cluster_single_linkage`` also defaults to, and the
    conservative one for a ban.

    VERDICT — three values, and NOT_RUN is not a pass:
      ``REJECT``   some chain scored >= threshold. Definitive, and reported even
                   when other chains could not be screened.
      ``PASS``     every named chain scored, all below threshold.
      ``NOT_RUN``  no references given, or a chain could not be scored and no
                   other chain rejected. The row is NOT cleared: it carries
                   NOT_RUN plus ``not_run_reason`` into the sheet, and
                   ``select_with_diversity_caps`` refuses it unless the gate is
                   declared unavailable campaign-wide. A gate that silently
                   passes because it could not run is the exact failure this file
                   exists to remove.
    """
    limit = float(threshold)
    # Validated HERE, before the loop. A mistyped mode raised inside the loop
    # would be caught per reference and turn every design into a NOT_RUN — a
    # configuration typo silently disabling the gate is precisely the shape of
    # failure this function exists to prevent.
    mode = str(symmetrize or "max").strip().lower()
    if mode not in _SYMMETRIZE_MODES:
        raise ValueError(f"unknown symmetrize mode {symmetrize!r}")
    specs = [_reference_spec(entry, index) for index, entry in enumerate(reference_chains)]
    per_reference: list[dict[str, Any]] = []
    failures: list[str] = []
    tm_max: float | None = None
    closest: str | None = None

    for pdb, chain, label in specs:
        try:
            result = tm_score(
                design_pdb,
                pdb,
                subject_chain=design_chain,
                reference_chain=chain,
                symmetrize=mode,
                n_seeds=n_seeds,
                dp_iterations=dp_iterations,
            )
        except TmScoreError as exc:
            failures.append(f"{label}: {exc}")
            per_reference.append({"label": label, "tm_score": None, "error": str(exc)})
            continue
        value = float(result["tm_score"])
        per_reference.append(
            {
                "label": label,
                "tm_score": value,
                "tm_norm_reference": result["tm_norm_reference"],
                "tm_norm_subject": result["tm_norm_subject"],
                "reference_chain": result["reference_chain"],
                "reference_length": result["reference_length"],
                "mimic": value >= limit,
            }
        )
        if tm_max is None or value > tm_max:
            tm_max, closest = value, label

    if tm_max is not None and tm_max >= limit:
        verdict, reason = "REJECT", None
    elif not specs:
        verdict, reason = "NOT_RUN", "no target or control chains were supplied"
    elif failures:
        verdict, reason = "NOT_RUN", "; ".join(failures)
    elif tm_max is None:
        verdict, reason = "NOT_RUN", "no reference chain produced a score"
    else:
        verdict, reason = "PASS", None

    return {
        "verdict": verdict,
        "tm_max": tm_max,
        "closest_reference": closest,
        "threshold": limit,
        "symmetrize": mode,
        "design_chain": design_chain,
        "n_references": len(specs),
        "n_scored": sum(1 for row in per_reference if row.get("tm_score") is not None),
        "per_reference": per_reference,
        "not_run_reason": reason,
        "stamp": TARGET_MIMIC_GATE_STAMP,
    }
