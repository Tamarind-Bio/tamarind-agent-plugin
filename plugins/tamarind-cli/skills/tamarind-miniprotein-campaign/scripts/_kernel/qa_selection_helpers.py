"""The design-sheet panel builder: Anthropic's selection caps and the mimic ban.

Split out of ``qa_analysis_helpers`` because the sandbox pays for the module it
touches. ``run_analysis_code_json`` prepends helper source into the executed
program, and a panel-selection analysis has no use for contact geometry, ipSAE
reconstruction, cif->pdb conversion or fold classification — nor they for the
caps. The two are inlined, sliced and triggered independently
(``code_analysis._HELPER_MODULES``), so neither drags the other along.

The cost of the split is that the modules cannot import each other: they are
concatenated into one sandbox program, not installed. So the three primitives
this one needs from its old home — ``IPSAE_MASK_STAMP``, ``_as_float`` and
``_clean_sequence`` — are duplicated below rather than imported, exactly as
``qa_tm_helpers`` duplicates the 0.5 TM threshold, and pinned against their
originals by ``test_split_helper_modules_agree_on_the_values_they_duplicate``.

DUPLICATION HAZARD, stated once here rather than beside each copy — a comment
next to a constant rides into every sandbox program that selects, and this
module's inlined size is exactly what the headroom guard bounds:

* The stamp is PRIVATE **and RENAMED** (``_IPSAE_MASK_STAMP``). Both halves do
  work, and different work. Private keeps it out of the trigger scan, which
  keys on a module's PUBLIC names — a public copy would make every analysis
  that merely prints the stamp inline this whole module behind it. Renamed is
  what stops it SHADOWING: the blocks are concatenated with this module after
  ``qa_analysis_helpers``, so an identically-spelled copy wins for the entire
  program. Privateness alone would not have stopped that.
* ``_as_float`` and ``_clean_sequence`` get only the first half. They keep
  their names, so a program inlining both modules really does carry two
  ``def _as_float``, and the copy below really does win — for
  ``qa_analysis_helpers``' own functions too. That is safe only because the
  sources are byte-identical, which is what the pinning test enforces. Do not
  read the split as "private helpers cannot collide"; they can.

Pure functions over dicts/lists, so the sheet writer can re-run the selection
verbatim at write time and a unit test can run it outside the sandbox.

SELECTION PROTOCOL
------------------
Build the design-sheet panel under Anthropic's selection caps.

``candidates`` must arrive PRE-SORTED best-first on the sheet's rank key
(``(n_seeds>=5 on all arms) DESC, pose_PASS DESC, rank_zscore DESC``). This
function never re-ranks; it only accepts, rejects and (for the method floor)
swaps.

Caps are applied IN SELECTION ORDER (``SELECTION_CAP_ORDER``):

  1. exact-sequence duplicate -> reject
  2. Levenshtein distance >= 5 from every already-selected sequence
  3. ``root_backbone_id`` <= 5% of the panel (rounded up)
  4. TM-0.90 cluster <= 10% of the panel (rounded up)
  5. ``structure_method`` <= 50% of the panel AND >= 3 distinct methods
  6. ``seq_method`` <= 2/3 of the panel

PERCENTAGES ARE OF THE FINAL PANEL SIZE, NOT THE RUNNING COUNT. Anthropic
anchors this themselves -- "cap any single structure_method at 50% (max 15
of 30)" is a fixed integer derived from 30, not a moving 50% of however many
rows are placed so far. The running-count reading also breaks the rest of
the spec: 5% of a running count is below 1 for the first twenty rows, so
every root_backbone would be capped at 1 early on, and the ">= 3 distinct
structure_methods" floor is a statement about the FINISHED panel that cannot
be evaluated against a partial one. So every cap is an integer computed once
from ``panel_size`` before selection begins. Caps (c) and (d) round UP
(Anthropic says "rounded up"); caps (e) and (f) round DOWN to match their
stated anchors ("max 15 of 30", "two-thirds").

ORDER IS LOAD-BEARING FOR ATTRIBUTION. Each rejection is credited to the
FIRST cap in ``cap_order`` that blocks, and that credit is what the sheet
discloses and what a reader uses to decide what to fix upstream. Note the
accepted SET is order-invariant for a fixed cap configuration (the caps are
a conjunction of monotone predicates over the same running panel) -- so a
permuted ``cap_order`` changes the disclosed reason, not the panel.

RELAXATION LADDER (``RELAXATION_LADDER``, cumulative, least-damaging first):

  0 none | 1 root_backbone 5%->10% | 2 TM cluster 10%->20% |
  3 Levenshtein 5->3 | 4 structure_method -> 50% (L185's hard ceiling) |
  5 seq_method 2/3->100% (Anthropic: relax (f) only as a last resort) |
  6 short_panel (ship fewer rows and disclose the count)

The first rung that both fills the panel and meets the method floor wins.
Exact-sequence duplicates and the >= 3 distinct structure_methods floor are
NEVER relaxed; when the floor cannot be met the result carries
``campaign_failure=True`` (plan 2.2: that is a campaign failure, not a
degradation). A cap is never silently exceeded -- the rung is always
reported.

TWO HARD BOUNDS sit above the ladder (L185: relax "but never past
per-root_backbone_id 25%, per-method 50%, or fewer than 3 distinct
structure_methods"). The third is already absolute (``campaign_failure``); the
first two are ``RELAXED_*_MAX_FRACTION``, applied to the RELAXED value only so
a wider frozen nominal is not tightened by a rung meant to loosen. Rung 4
asked 2/3 -- 20 of 30, 66.7% -- straight through the 50% its own sentence
sets; it stops at 50% now, a no-op at the default nominal.

ONE STEP PER CALL: ``max_relaxation_rung`` defaults to 1. L92/L185 make
upstream repair the required FIRST response and relaxation "one step at a
time", so a bare call walks at most one step and reports where it stopped
(``relaxation_rung`` vs ``max_relaxation_rung``).

THE TARGET-MIMIC BAN IS NOT ONE OF THESE CAPS. Each candidate carries
``target_mimic`` (see :func:`target_mimic_verdict`); a REJECT is refused in
``_prepare_candidates`` BEFORE the first rung runs and credited to
``CAP_TARGET_MIMIC``. That placement is the mechanism: rungs only widen the
integers in ``_effective_caps``, and the diversity repair only reconsiders
rows with ``invalid`` unset, so no relaxation can reach a banned row. A
NOT_RUN verdict is refused for the same reason a missing provenance key is.
``require_target_mimic=False`` is the ONE escape and it is CAMPAIGN-wide, not
per-row: ``CAP_TARGET_MIMIC`` lands in ``gates_not_run``,
``target_mimic_stamp`` carries the disclosure, ``target_mimic_not_run`` names
every uncovered row -- and a recorded REJECT still rejects.

``require_tm_cluster=False`` is the disclosed degraded mode for an
unavailable structural-clustering tool: cap (d) is recorded in
``caps_not_run`` and rows without a cluster id are admitted instead of
rejected. Never leave it False silently -- an un-enforced cap must be
stamped NOT_RUN on every row.

Returns the selected candidates PLUS a full trace: ``rejections`` (one entry
per rejected candidate naming the cap and the numbers behind it),
``unconsidered`` (never reached because the panel filled first), and
``trace_complete`` -- True only when selected / rejected / unconsidered
partition every input candidate exactly once.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = [
    "select_with_diversity_caps",
    "target_mimic_verdict",
]

# ---------------------------------------------------------------------------
# Duplicated from qa_analysis_helpers — see the module docstring. Kept
# character-for-character identical to the originals; a test pins them.
# ---------------------------------------------------------------------------

# Stamped on every scored row: v1 reconstructs ipSAE_min per target protomer and
# takes the max, because union-mask ipSAE cannot be rebuilt from pair scalars.
# PRIVATE and RENAMED on purpose; the module docstring says why both matter.
_IPSAE_MASK_STAMP = "PER_PROTOMER_MAX(not UNION)"


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


def _clean_sequence(sequence: Any) -> str:
    """Uppercase single-letter residues only (whitespace / digits dropped)."""
    return "".join(ch for ch in str(sequence or "").upper() if ch.isalpha())


# ---------------------------------------------------------------------------
# Selection caps (the design-sheet panel builder)
# ---------------------------------------------------------------------------

CAP_MISSING_FIELD = "missing_provenance_field"
CAP_EXACT_DUPLICATE = "exact_duplicate_sequence"
CAP_LEVENSHTEIN = "levenshtein_min_distance"
CAP_ROOT_BACKBONE = "root_backbone_cap"
CAP_TM_CLUSTER = "tm_cluster_cap"
CAP_STRUCTURE_METHOD = "structure_method_cap"
CAP_SEQ_METHOD = "seq_method_cap"
CAP_DIVERSITY_REPAIR = "structure_method_diversity_repair"

# A BAN, not a cap: absent from SELECTION_CAP_ORDER and RELAXATION_LADDER on
# purpose, and enforced in _prepare_candidates BEFORE the rung loop, so no rung,
# cap_order permutation or diversity repair can reach a banned row. Anthropic:
# "binder-chain target-mimic and natural-sequence-copy bans stay absolute and
# are never relaxed." The threshold is 0.5 on both sides -- the two helper
# modules are inlined independently and cannot import each other, so it is
# written twice and pinned by test_the_threshold_is_the_same_number_in_both_modules.
CAP_TARGET_MIMIC = "target_mimic_ban"
TARGET_MIMIC_TM_THRESHOLD = 0.5
TARGET_MIMIC_VERDICTS = ("PASS", "REJECT", "NOT_RUN")
TARGET_MIMIC_NOT_RUN_STAMP = (
    "TARGET_MIMIC=NOT_RUN — the target-mimic gate was declared unavailable for "
    "this campaign. Rows below carry NO evidence that they are not target-fold "
    "mimics; this is a disclosed instrument reduction, not a pass."
)

# Anthropic's selection ORDER, verbatim. Load-bearing for attribution: the cap
# credited with a rejection is the FIRST one in this tuple that blocks, and that
# is what the sheet discloses and what the relaxation ladder is reasoned about.
SELECTION_CAP_ORDER: tuple[str, ...] = (
    CAP_EXACT_DUPLICATE,
    CAP_LEVENSHTEIN,
    CAP_ROOT_BACKBONE,
    CAP_TM_CLUSTER,
    CAP_STRUCTURE_METHOD,
    CAP_SEQ_METHOD,
)

# Cumulative: rung N applies its own relaxation and every earlier rung's.
# Ordered least-to-most damaging to the science. Two things are NEVER relaxed:
# exact-sequence duplicates, and the >=3 distinct structure_methods floor
# (plan 2.2 -- failing that is a campaign failure, not a degradation).
RELAXATION_LADDER: tuple[tuple[str, str], ...] = (
    ("none", "all caps at nominal"),
    ("relax_root_backbone", "root_backbone cap 5% -> 10% of panel"),
    ("relax_tm_cluster", "TM-0.90 cluster cap 10% -> 20% of panel"),
    ("relax_levenshtein", "minimum Levenshtein distance 5 -> 3"),
    ("relax_structure_method", "structure_method cap -> 50% of panel (L185 ceiling)"),
    ("relax_seq_method", "seq_method cap 2/3 -> 100% of panel (last resort)"),
    ("short_panel", "ship fewer than panel_size rows and disclose the count"),
)

# 0 IS A REAL ID: `or ""` bucketed every falsy root together, escaping the
# 5% cap. Mirrors qa._sheet_id_value.
_NULLISH = {"", "nan", "none", "null", "n/a", "na"}


def _id_token(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return "" if str(value).strip().lower() in _NULLISH else str(value).strip()



# L185's ceilings on what a RUNG may hand out -- module docstring, TWO HARD
# BOUNDS. Here rather than at the call site so no caller can reach past them.
RELAXED_ROOT_BACKBONE_MAX_FRACTION = 0.25
RELAXED_STRUCTURE_METHOD_MAX_FRACTION = 0.50
# Module docstring: ONE STEP PER CALL.
DEFAULT_MAX_RELAXATION_RUNG = 1

_REQUIRED_CANDIDATE_FIELDS = (
    "design_id",
    "sequence",
    "root_backbone_id",
    "structure_method",
    "seq_method",
)


def _bounded_levenshtein(left: str, right: str, max_distance: int) -> int:
    """Levenshtein distance, capped at ``max_distance + 1``.

    Banded (Ukkonen) DP: only cells within ``max_distance`` of the diagonal are
    evaluated, so a 120-residue pair costs ~O(n * (2k+1)) instead of O(n^2).
    """
    if left == right:
        return 0
    if max_distance <= 0:
        return 1
    if abs(len(left) - len(right)) > max_distance:
        return max_distance + 1
    if len(left) > len(right):
        left, right = right, left
    n, m = len(left), len(right)
    ceiling = max_distance + 1
    previous = [i if i <= max_distance else ceiling for i in range(n + 1)]
    for j in range(1, m + 1):
        current = [ceiling] * (n + 1)
        current[0] = j if j <= max_distance else ceiling
        lo = max(1, j - max_distance)
        hi = min(n, j + max_distance)
        for i in range(lo, hi + 1):
            cost = 0 if left[i - 1] == right[j - 1] else 1
            value = min(previous[i] + 1, current[i - 1] + 1, previous[i - 1] + cost)
            current[i] = value if value <= max_distance else ceiling
        if all(value > max_distance for value in current):
            return ceiling
        previous = current
    return previous[n]


def target_mimic_verdict(value: Any, threshold: float = TARGET_MIMIC_TM_THRESHOLD) -> str:
    """``target_mimic`` -> PASS / REJECT / NOT_RUN, with no fourth answer.

    Accepts the dict ``qa_tm_helpers.target_mimic_screen`` returns, a bare max
    TM-score, or the verdict word in any case. EVERYTHING else -- None, "", NaN,
    an unrecognised string -- is NOT_RUN, never PASS: an unreadable value means
    nobody can say the gate ran, and "a gate that exists but was not run is a
    protocol violation".
    """
    if isinstance(value, Mapping):
        value = value.get("verdict", value.get("tm_max"))
    if isinstance(value, str):
        text = value.strip().upper()
        return text if text in TARGET_MIMIC_VERDICTS else "NOT_RUN"
    if isinstance(value, bool):
        return "NOT_RUN"
    number = _as_float(value)
    if number is None:
        return "NOT_RUN"
    return "REJECT" if number >= float(threshold) else "PASS"


def _prepare_candidates(
    candidates: Iterable[Any],
    *,
    require_tm_cluster: bool,
    require_target_mimic: bool = True,
    target_mimic_threshold: float = TARGET_MIMIC_TM_THRESHOLD,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        row = candidate if isinstance(candidate, Mapping) else {}
        design_id = str(row.get("design_id") or "").strip()
        trace_id = design_id or f"<index:{index}>"
        sequence = _clean_sequence(row.get("sequence"))
        tm_cluster = row.get("tm_cluster", row.get("tm_cluster_id"))
        mimic = target_mimic_verdict(
            row.get("target_mimic", row.get("target_mimic_tm_max")),
            target_mimic_threshold,
        )
        entry: dict[str, Any] = {
            "rank_index": index,
            "design_id": trace_id,
            "sequence": sequence,
            "root_backbone_id": _id_token(row.get("root_backbone_id")),
            "tm_cluster": "" if tm_cluster is None else str(tm_cluster).strip(),
            "structure_method": str(row.get("structure_method") or "").strip(),
            "seq_method": str(row.get("seq_method") or "").strip(),
            "target_mimic": mimic,
            "candidate": candidate,
            "invalid": None,
            "invalid_cap": None,
        }
        missing = [
            field
            for field in _REQUIRED_CANDIDATE_FIELDS
            if not (design_id if field == "design_id" else entry.get(field))
        ]
        if require_tm_cluster and not entry["tm_cluster"]:
            missing.append("tm_cluster")
        # Three pre-cap refusals, in credit order. REJECT outranks a malformed
        # row (credited otherwise, a caught mimic vanishes from rejection_counts
        # as a mimic, and that count is the only downstream evidence the gate
        # caught anything) and stands even in the degraded mode. Missing
        # provenance outranks a merely un-run gate, because that is what a bare
        # row is actually wrong about. An un-run gate on a well-formed row fails
        # closed like a missing field: nobody can say the check happened.
        if mimic == "REJECT":
            entry["invalid"] = (
                f"target-mimic ban: TM-score >= {float(target_mimic_threshold)} to a "
                "target or control chain"
            )
            entry["invalid_cap"] = CAP_TARGET_MIMIC
        elif missing:
            entry["invalid"] = f"missing {', '.join(sorted(missing))}"
            entry["invalid_cap"] = CAP_MISSING_FIELD
        elif mimic == "NOT_RUN" and require_target_mimic:
            entry["invalid"] = (
                "target-mimic gate NOT_RUN on this row; it is mandatory and is never "
                "satisfied by absence. Run target_mimic_screen, or declare the gate "
                "unavailable campaign-wide with require_target_mimic=False and stamp "
                "every row NOT_RUN"
            )
            entry["invalid_cap"] = CAP_TARGET_MIMIC
        if design_id:
            if design_id in seen_ids:
                # Two rows carrying one id means the upstream join is broken; a
                # trace cannot be a partition and provenance cannot be followed.
                raise ValueError(f"duplicate design_id {design_id!r} in candidates")
            seen_ids.add(design_id)
        prepared.append(entry)
    return prepared


def _effective_caps(
    panel_size: int,
    rung: int,
    *,
    min_levenshtein_distance: int,
    root_backbone_cap_fraction: float,
    tm_cluster_cap_fraction: float,
    structure_method_cap_fraction: float,
    seq_method_cap_fraction: float,
) -> dict[str, int]:
    """Integer caps for one rung, computed from the FINAL panel size.

    See ``select_with_diversity_caps`` for why the denominator is the final
    panel size and not the running count.
    """

    def ceil_cap(fraction: float) -> int:
        return max(1, math.ceil(fraction * panel_size - 1e-9))

    def floor_cap(fraction: float) -> int:
        return max(1, math.floor(fraction * panel_size + 1e-9))

    def bounded(*, nominal: float, relaxed: float, ceiling: float, applies: bool) -> float:
        # `min` is L185's bound; `max` stops it INVERTING the rung, tightening a
        # wider frozen nominal. Untouched at rung 0 -- see the module docstring.
        if not applies:
            return nominal
        return max(nominal, min(relaxed, ceiling))

    return {
        "levenshtein": 3 if rung >= 3 else int(min_levenshtein_distance),
        "root_backbone": ceil_cap(
            bounded(
                nominal=root_backbone_cap_fraction,
                relaxed=root_backbone_cap_fraction * 2,
                ceiling=RELAXED_ROOT_BACKBONE_MAX_FRACTION,
                applies=rung >= 1,
            )
        ),
        # NOT bounded: L185 names ceilings for per-root_backbone_id and
        # per-method only. A third one here would refuse panels it admits.
        "tm_cluster": ceil_cap(
            tm_cluster_cap_fraction * 2 if rung >= 2 else tm_cluster_cap_fraction
        ),
        "structure_method": floor_cap(
            bounded(
                nominal=structure_method_cap_fraction,
                relaxed=2.0 / 3.0,
                ceiling=RELAXED_STRUCTURE_METHOD_MAX_FRACTION,
                applies=rung >= 4,
            )
        ),
        "seq_method": panel_size if rung >= 5 else floor_cap(seq_method_cap_fraction),
    }


def _first_blocking_cap(
    entry: dict[str, Any],
    panel: list[dict[str, Any]],
    counters: dict[str, Counter],
    caps: Mapping[str, int],
    cap_order: Sequence[str],
    *,
    require_tm_cluster: bool,
) -> tuple[str | None, str]:
    sequences = {member["sequence"]: member["design_id"] for member in panel}
    for cap in cap_order:
        if cap == CAP_EXACT_DUPLICATE:
            twin = sequences.get(entry["sequence"])
            if twin is not None:
                return cap, f"exact sequence duplicate of {twin}"
        elif cap == CAP_LEVENSHTEIN:
            limit = int(caps["levenshtein"])
            if limit > 0:
                for member in panel:
                    distance = _bounded_levenshtein(
                        entry["sequence"], member["sequence"], limit - 1
                    )
                    if distance < limit:
                        return cap, (f"Levenshtein {distance} < {limit} vs {member['design_id']}")
        elif cap == CAP_ROOT_BACKBONE:
            count = counters["root_backbone"][entry["root_backbone_id"]]
            if count + 1 > caps["root_backbone"]:
                return cap, (
                    f"root_backbone_id {entry['root_backbone_id']} already at "
                    f"{count}/{caps['root_backbone']}"
                )
        elif cap == CAP_TM_CLUSTER:
            if not require_tm_cluster and not entry["tm_cluster"]:
                continue
            count = counters["tm_cluster"][entry["tm_cluster"]]
            if count + 1 > caps["tm_cluster"]:
                return cap, (
                    f"TM-0.90 cluster {entry['tm_cluster']} already at {count}/{caps['tm_cluster']}"
                )
        elif cap == CAP_STRUCTURE_METHOD:
            count = counters["structure_method"][entry["structure_method"]]
            if count + 1 > caps["structure_method"]:
                return cap, (
                    f"structure_method {entry['structure_method']} already at "
                    f"{count}/{caps['structure_method']}"
                )
        elif cap == CAP_SEQ_METHOD:
            count = counters["seq_method"][entry["seq_method"]]
            if count + 1 > caps["seq_method"]:
                return cap, (
                    f"seq_method {entry['seq_method']} already at {count}/{caps['seq_method']}"
                )
        else:
            raise ValueError(f"unknown cap {cap!r} in cap_order")
    return None, ""


def _counters_for(panel: Sequence[Mapping[str, Any]]) -> dict[str, Counter]:
    return {
        "root_backbone": Counter(member["root_backbone_id"] for member in panel),
        "tm_cluster": Counter(member["tm_cluster"] for member in panel),
        "structure_method": Counter(member["structure_method"] for member in panel),
        "seq_method": Counter(member["seq_method"] for member in panel),
    }


def _run_selection_pass(
    prepared: Sequence[dict[str, Any]],
    *,
    panel_size: int,
    caps: Mapping[str, int],
    cap_order: Sequence[str],
    min_structure_methods: int,
    require_tm_cluster: bool,
) -> dict[str, Any]:
    panel: list[dict[str, Any]] = []
    counters = _counters_for(panel)
    # Keyed by rank_index (never by design_id) so the trace is a partition even
    # for placeholder ids.
    rejections: dict[int, dict[str, Any]] = {}
    unconsidered: list[int] = []

    def admit(entry: dict[str, Any]) -> None:
        panel.append(entry)
        counters["root_backbone"][entry["root_backbone_id"]] += 1
        counters["tm_cluster"][entry["tm_cluster"]] += 1
        counters["structure_method"][entry["structure_method"]] += 1
        counters["seq_method"][entry["seq_method"]] += 1

    for entry in prepared:
        if entry["invalid"]:
            rejections[entry["rank_index"]] = {
                "design_id": entry["design_id"],
                "rank_index": entry["rank_index"],
                "cap": entry["invalid_cap"] or CAP_MISSING_FIELD,
                "detail": entry["invalid"],
            }
            continue
        if len(panel) >= panel_size:
            unconsidered.append(entry["rank_index"])
            continue
        cap, detail = _first_blocking_cap(
            entry, panel, counters, caps, cap_order, require_tm_cluster=require_tm_cluster
        )
        if cap is not None:
            rejections[entry["rank_index"]] = {
                "design_id": entry["design_id"],
                "rank_index": entry["rank_index"],
                "cap": cap,
                "detail": detail,
            }
            continue
        admit(entry)

    # --- >=3 distinct structure_methods repair ------------------------------
    # A cap can only reject; it can never CREATE the diversity this floor
    # requires. So after the greedy pass, swap the lowest-ranked member of an
    # over-represented method for the best-ranked candidate carrying an absent
    # method, whenever that swap satisfies every cap.
    repairs: list[dict[str, Any]] = []
    for _ in range(max(0, min_structure_methods) * 4 + 4):
        present = {member["structure_method"] for member in panel}
        if len(present) >= min_structure_methods:
            break
        placed = {member["rank_index"] for member in panel}
        newcomers = [
            entry
            for entry in prepared
            if not entry["invalid"]
            and entry["rank_index"] not in placed
            and entry["structure_method"] not in present
        ]
        if not newcomers:
            break
        swapped = False
        for newcomer in newcomers:
            if len(panel) < panel_size:
                cap, _detail = _first_blocking_cap(
                    newcomer,
                    panel,
                    counters,
                    caps,
                    cap_order,
                    require_tm_cluster=require_tm_cluster,
                )
                if cap is None:
                    rejections.pop(newcomer["rank_index"], None)
                    if newcomer["rank_index"] in unconsidered:
                        unconsidered.remove(newcomer["rank_index"])
                    admit(newcomer)
                    repairs.append(
                        {
                            "added": newcomer["design_id"],
                            "displaced": None,
                            "reason": "backfilled an absent structure_method",
                        }
                    )
                    swapped = True
                    break
                continue
            method_counts = Counter(member["structure_method"] for member in panel)
            victims = sorted(
                (member for member in panel if method_counts[member["structure_method"]] >= 2),
                key=lambda member: (
                    -method_counts[member["structure_method"]],
                    -member["rank_index"],
                ),
            )
            for victim in victims:
                trial = [member for member in panel if member["rank_index"] != victim["rank_index"]]
                trial_counters = _counters_for(trial)
                cap, _detail = _first_blocking_cap(
                    newcomer,
                    trial,
                    trial_counters,
                    caps,
                    cap_order,
                    require_tm_cluster=require_tm_cluster,
                )
                if cap is not None:
                    continue
                panel[:] = trial
                counters.clear()
                counters.update(trial_counters)
                rejections[victim["rank_index"]] = {
                    "design_id": victim["design_id"],
                    "rank_index": victim["rank_index"],
                    "cap": CAP_DIVERSITY_REPAIR,
                    "detail": (
                        f"displaced by {newcomer['design_id']} to reach "
                        f"{min_structure_methods} distinct structure_methods"
                    ),
                }
                rejections.pop(newcomer["rank_index"], None)
                if newcomer["rank_index"] in unconsidered:
                    unconsidered.remove(newcomer["rank_index"])
                admit(newcomer)
                repairs.append(
                    {
                        "added": newcomer["design_id"],
                        "displaced": victim["design_id"],
                        "reason": "backfilled an absent structure_method",
                    }
                )
                swapped = True
                break
            if swapped:
                break
        if not swapped:
            break

    panel.sort(key=lambda member: member["rank_index"])
    selected_ids = [member["design_id"] for member in panel]
    placed = {member["rank_index"] for member in panel}
    # Anything neither selected nor rejected was never reached (the panel filled
    # first). Recomputed here so the repair's swaps cannot leave a hole.
    unconsidered_ids = [
        entry["design_id"]
        for entry in prepared
        if entry["rank_index"] not in placed and entry["rank_index"] not in rejections
    ]
    ordered_rejections = [
        rejections[entry["rank_index"]]
        for entry in prepared
        if entry["rank_index"] in rejections and entry["rank_index"] not in placed
    ]

    structure_counts = Counter(member["structure_method"] for member in panel)
    return {
        "panel": panel,
        "selected_ids": selected_ids,
        "rejections": ordered_rejections,
        "unconsidered": unconsidered_ids,
        "repairs": repairs,
        "distinct_structure_methods": len(structure_counts),
        "structure_method_counts": dict(structure_counts),
        "seq_method_counts": dict(Counter(member["seq_method"] for member in panel)),
        "root_backbone_counts": dict(Counter(member["root_backbone_id"] for member in panel)),
        "tm_cluster_counts": dict(Counter(member["tm_cluster"] for member in panel)),
    }


def select_with_diversity_caps(
    candidates: Iterable[Any],
    panel_size: int = 30,
    *,
    min_levenshtein_distance: int = 5,
    root_backbone_cap_fraction: float = 0.05,
    tm_cluster_cap_fraction: float = 0.10,
    structure_method_cap_fraction: float = 0.50,
    seq_method_cap_fraction: float = 2.0 / 3.0,
    min_structure_methods: int = 3,
    cap_order: Sequence[str] | None = None,
    max_relaxation_rung: int = DEFAULT_MAX_RELAXATION_RUNG,
    require_tm_cluster: bool = True,
    require_target_mimic: bool = True,
    target_mimic_threshold: float = TARGET_MIMIC_TM_THRESHOLD,
) -> dict[str, Any]:
    """Build the design-sheet panel under Anthropic's selection caps.

    The protocol this implements — cap order, what the percentages are OF,
    why order is load-bearing for attribution, the relaxation ladder, the
    target-mimic ban, the degraded modes, and the returned trace — is the
    module docstring of ``campaign/subagents/qa_selection_helpers.py``,
    unchanged and in full. It lives there rather than here because a module
    docstring is not inlined into the sandbox program (``helper_inlining``
    emits imports and top-level units only), and ~4.3k characters of protocol
    narrative rode into every E2B payload, S3 code artifact and review panel
    that called this function.

    AT THE CALL SITE: ``max_relaxation_rung`` defaults to 1, so a bare call
    relaxes AT MOST ONE step. A short panel therefore means "this rung could not
    fill it", not "the ladder is exhausted".
    """
    size = int(panel_size)
    if size < 1:
        raise ValueError("panel_size must be >= 1")
    order = tuple(cap_order) if cap_order is not None else SELECTION_CAP_ORDER
    unknown = [cap for cap in order if cap not in SELECTION_CAP_ORDER]
    if unknown:
        raise ValueError(f"unknown caps in cap_order: {unknown}")
    method_floor = max(0, min(int(min_structure_methods), size))
    prepared = _prepare_candidates(
        candidates,
        require_tm_cluster=require_tm_cluster,
        require_target_mimic=require_target_mimic,
        target_mimic_threshold=target_mimic_threshold,
    )
    top_rung = max(0, min(int(max_relaxation_rung), len(RELAXATION_LADDER) - 1))

    result: dict[str, Any] | None = None
    used_rung = 0
    # Rungs 0..5 relax caps; the last rung is a LABEL for "shipped short", not a
    # cap configuration, so it is never used as a selection pass.
    last_cap_rung = min(top_rung, len(RELAXATION_LADDER) - 2)
    for rung in range(last_cap_rung + 1):
        caps = _effective_caps(
            size,
            rung,
            min_levenshtein_distance=min_levenshtein_distance,
            root_backbone_cap_fraction=root_backbone_cap_fraction,
            tm_cluster_cap_fraction=tm_cluster_cap_fraction,
            structure_method_cap_fraction=structure_method_cap_fraction,
            seq_method_cap_fraction=seq_method_cap_fraction,
        )
        attempt = _run_selection_pass(
            prepared,
            panel_size=size,
            caps=caps,
            cap_order=order,
            min_structure_methods=method_floor,
            require_tm_cluster=require_tm_cluster,
        )
        attempt["caps"] = dict(caps)
        result = attempt
        used_rung = rung
        if len(attempt["selected_ids"]) >= size and (
            attempt["distinct_structure_methods"] >= method_floor
        ):
            break

    assert result is not None
    if len(result["selected_ids"]) < size and top_rung >= len(RELAXATION_LADDER) - 1:
        # Every cap relaxation the caller allowed is exhausted and the panel is
        # still short: the remaining rung is the disclosure, not a relaxation.
        used_rung = len(RELAXATION_LADDER) - 1
    selected = [member["candidate"] for member in result["panel"]]
    total = len(prepared)
    accounted = (
        len(result["selected_ids"]) + len(result["rejections"]) + len(result["unconsidered"])
    )
    label, description = RELAXATION_LADDER[used_rung]
    return {
        "panel_size_requested": size,
        "n_selected": len(selected),
        "selected": selected,
        "selected_ids": list(result["selected_ids"]),
        "caps": result["caps"],
        "cap_order": list(order),
        "caps_not_run": [] if require_tm_cluster else [CAP_TM_CLUSTER],
        "target_mimic_threshold": float(target_mimic_threshold),
        "target_mimic_required": bool(require_target_mimic),
        # Keyed on the VERDICT, not on the cap that refused the row. Both a
        # caught mimic and an un-run gate are refused under CAP_TARGET_MIMIC, so
        # keying on the cap would report every unscreened row as a caught mimic
        # -- a campaign where the gate never ran once would show the highest
        # catch count of all, which is exactly backwards.
        "target_mimic_rejected": [
            entry["design_id"] for entry in prepared if entry["target_mimic"] == "REJECT"
        ],
        "target_mimic_not_run": [
            entry["design_id"] for entry in prepared if entry["target_mimic"] == "NOT_RUN"
        ],
        "gates_not_run": [] if require_target_mimic else [CAP_TARGET_MIMIC],
        "target_mimic_stamp": None if require_target_mimic else TARGET_MIMIC_NOT_RUN_STAMP,
        "relaxation_rung": used_rung,
        # The ceiling this call could walk to, beside where it stopped. Without
        # it "rung 1 could not fill it, ask again" and "every rung is spent" are
        # the same `short_panel: True` and demand opposite next moves.
        "max_relaxation_rung": top_rung,
        "relaxation_label": label,
        "relaxation_description": description,
        "relaxations_applied": [RELAXATION_LADDER[step][0] for step in range(1, used_rung + 1)],
        "min_structure_methods": method_floor,
        "distinct_structure_methods": result["distinct_structure_methods"],
        "structure_method_counts": result["structure_method_counts"],
        "seq_method_counts": result["seq_method_counts"],
        "root_backbone_counts": result["root_backbone_counts"],
        "tm_cluster_counts": result["tm_cluster_counts"],
        "campaign_failure": result["distinct_structure_methods"] < method_floor,
        "short_panel": len(selected) < size,
        "repairs": result["repairs"],
        "rejections": result["rejections"],
        "rejection_counts": dict(Counter(entry["cap"] for entry in result["rejections"])),
        "unconsidered": result["unconsidered"],
        "n_candidates": total,
        "trace_complete": accounted == total,
        "ipsae_mask": _IPSAE_MASK_STAMP,
    }
