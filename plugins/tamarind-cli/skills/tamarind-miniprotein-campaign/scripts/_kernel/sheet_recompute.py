"""The sheet writer's own recompute of the gates it can re-derive (protocol L90).

    "The sheet writer recomputes every gate from the row's sequence and
     predicted structure at write time (novelty, liability, monomer-foldability,
     structural-plausibility, pose_dockq, final_score) and admits the row only
     when the recomputed result matches the carried value to within 1e-4; a
     mismatch halts the writer with the row id."

``qa.recompute_sheet_gate_terms`` does that for ``final_score``, and its
docstring is the contract every function here copies. The other four gates the
sentence names were left to the MODEL's ``parsed["gate_recompute"]`` claim --
four tokens a model can emit without having recomputed anything. These are the
arithmetic behind three of them, plus structural-plausibility.

WHY THIS IS A SEPARATE MODULE AND NOT MORE OF ``qa.py``: every function here
reaches into a gate module (``novelty_gate``, ``qa_analysis_helpers``,
``structure_plausibility``, ``screen_gate_metrics``) that ``qa.py`` deliberately
does not depend on wholesale, and ``qa.py`` imports THIS module rather than the
other way round. That direction is load-bearing -- see ``_is_null_sheet_value``
below for what it costs and why the cost is paid.

THE SHARED CONTRACT, stated once here and not re-argued in four docstrings:

  FAILS OPEN ON ABSENCE, CLOSED ON CONTRADICTION. A row missing an INPUT is
  ``not_recomputable`` under a named reason -- never a mismatch. A mismatch is
  claimed only when the row's own data DETERMINES the answer. A missing column
  is not a wrong column, and halting a campaign on arithmetic this module got
  wrong is strictly worse than not running the check.

  ``rows_checked`` counts the rows a comparison was actually possible on --
  never the rows handed in. ``mismatches`` and ``not_recomputable`` are DISJOINT
  at the row level, exactly as they are in ``recompute_sheet_gate_terms``: a row
  is either checked (and then possibly a mismatch) or accounted for as skipped,
  never both, so no reader has to work out which of two entries is the live one.

  AN INPUT IS NOT A CLAIM. The distinction the "absence" half turns on is
  between the data the recompute CONSUMES (the row's sequence, the fetched
  pLDDT, the fetched structure) and the cell it is CHECKING. Absence of an input
  makes the check impossible. Absence of the checked cell only makes the row
  silent -- and where the recompute reaches a verdict that says "this row must
  not be on the sheet at all", silence does not answer it. That is why the two
  verdict gates below (novelty, structural-plausibility) treat a determined
  REJECT as a mismatch whatever the cell holds, while the two numeric gates
  (liability, monomer) treat an absent cell as absence. Both halves are the same
  rule read carefully, not two rules.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from ._rubric_constants import MONOMER_ROW_MEASUREMENT_TERM
from .novelty_gate import (
    NOVELTY_REQUIRED_SUBJECTS_FINAL,
    novelty_verdicts,
)
from .prescoring_rejects import (
    PRESCORING_GATE_LIABILITY,
    PRESCORING_GATE_MONOMER_FOLDABILITY,
    PRESCORING_GATE_NOVELTY,
    PRESCORING_GATE_STRUCTURAL_PLAUSIBILITY,
    VERDICT_NOT_RUN,
    VERDICT_PASS,
    VERDICT_REJECT,
    VERDICTS,
)
from .qa_analysis_helpers import composition_liability_flags
from .screen_gate_metrics import (
    MONOMER_VERDICT_PASS,
    MONOMER_VERDICT_REJECT,
    ScreenGateInputError,
)
from .structure_plausibility import (
    StructurePlausibilityInputError,
    structural_plausibility_verdict,
)

__all__ = [
    "LIABILITY_CYS_PARITY_COLUMN",
    "LIABILITY_MAX_HOMOPOLYMER_RUN_COLUMN",
    "LIABILITY_MAX_HYDROPHOBIC_PATCH_COLUMN",
    "LIABILITY_MIN_WINDOW_ENTROPY_COLUMN",
    "NOVELTY_VERDICT_COLUMN",
    "PLAUSIBILITY_TERM_COLUMN_PREFIX",
    "PLAUSIBILITY_VERDICT_COLUMN",
    "SHEET_RECOMPUTE_TOLERANCE",
    "liability_recompute",
    "monomer_recompute",
    "novelty_recompute",
    "plausibility_recompute",
]


# The sheet's own reproduction tolerance, the one protocol L90 states and the
# one `qa._SHEET_RECOMPUTE_TOLERANCE` already holds. Spelled again rather than
# imported for the import-direction reason the module docstring gives;
# `test_the_copied_sheet_cell_rules_agree_with_qa` pins the two equal.
SHEET_RECOMPUTE_TOLERANCE = 1e-4


# ── the sheet-cell reading rules, COPIED from qa.py ────────────────────────
#
# `_NULL_SHEET_VALUES`, `_is_null_sheet_value`, `_as_sheet_float`,
# `_sheet_id_value` and `_sheet_row_id` are verbatim copies of
# `campaign/cda/subagents/qa.py`'s functions of the same names. THE ORIGINALS
# ARE THE DEFINITION; these are a copy, and the copy exists only because
# importing them would be a cycle: `qa._execute_design_sheet` imports THIS
# module, so a module-level `from ...qa import _as_sheet_float` here makes the
# two modules import each other and the one that loads first raises ImportError
# on a half-initialized partner.
#
# A second rule for what a blank cell means is exactly the defect these
# functions exist to prevent, so the copy is pinned to the original by
# `tests/test_campaign_sheet_recompute.py::test_the_copied_sheet_cell_rules_agree_with_qa`,
# which imports both and runs the same table of cells through each. That test
# is the whole justification for copying rather than re-deriving: it fails the
# moment the two spellings disagree about a single cell.
_NULL_SHEET_VALUES = frozenset({"", "nan", "null", "none", "na", "n/a", "-"})


def _is_null_sheet_value(value: Any) -> bool:
    """True when a shipped sheet cell holds no real value. Copy of ``qa``'s."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        return value.strip().lower() in _NULL_SHEET_VALUES
    return False


def _as_sheet_float(value: Any) -> float | None:
    """A shipped cell as a float, or ``None``. Copy of ``qa``'s.

    A bool is NOT a number here even though Python says it is, and strings ARE
    parsed but only when they parse cleanly -- "TBD" is not zero.
    """
    if isinstance(value, bool) or _is_null_sheet_value(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(parsed) or math.isinf(parsed) else parsed


def _sheet_id_value(value: Any) -> str:
    """An identifier cell as a comparable token, treating 0 as a real id."""
    if _is_null_sheet_value(value):
        return ""
    return str(value).strip()


def _sheet_row_id(row: Mapping[str, Any], index: int) -> str:
    """The id a human can act on when a row is rejected. Copy of ``qa``'s."""
    for key in ("design_id", "name", "id"):
        value = _sheet_id_value(row.get(key))
        if value:
            return value
    return f"row_{index + 1}"


def _carried_verdict_token(raw: Any) -> str:
    """A carried gate cell as one of the three verdicts; anything else NOT_RUN.

    Copy of ``qa._carried_verdict_token``, kept for the same reason as the cell
    readers above and pinned to it by the same test. Its rule is the one that
    matters here: an unrecognized token is a gate that did not report, and
    reading it as anything but NOT_RUN is how "the model wrote something in the
    cell" becomes "the gate passed".
    """
    token = "" if _is_null_sheet_value(raw) else str(raw).strip().upper()
    return token if token in VERDICTS else VERDICT_NOT_RUN


# ── the pinned column names (see docs/cda-fork/SHEET-RECOMPUTE-CONTRACT.md) ─
#
# NAME DRIFT AGAINST THE HELPERS IS DELIBERATE AND IS RECORDED HERE, because
# two of these four do NOT name a top-level key of
# `composition_liability_flags`' returned dict:
#
#   * `liability_max_homopolymer_run` <- `flags["homopolymer"]["longest_run"]`,
#     NOT `flags["homopolymer"]["max_run"]`. `max_run` is the THRESHOLD the
#     check ran with (a constant, 4), and `longest_run` is the measurement. A
#     column called "max homopolymer run" filled from `max_run` would be the
#     same number on every row of every campaign and would match a recompute of
#     itself forever -- a check that cannot fail.
#   * `liability_cys_parity` <- `flags["cys_parity"]["parity"]`, the "odd" /
#     "even" token. `cys_parity_flag` returns a DICT, not a token, so the
#     column is never compared against its return value; and the sub-dict is
#     read out of `composition_liability_flags`' own result rather than by
#     calling `cys_parity_flag` a second time, so there is exactly one cleaned
#     sequence behind all four terms. The dict's `flag` key is the BOOLEAN
#     (True == odd), which is not what the column carries.
LIABILITY_MIN_WINDOW_ENTROPY_COLUMN = "liability_min_window_entropy_bits"
LIABILITY_MAX_HYDROPHOBIC_PATCH_COLUMN = "liability_max_hydrophobic_patch_fraction"
LIABILITY_MAX_HOMOPOLYMER_RUN_COLUMN = "liability_max_homopolymer_run"
LIABILITY_CYS_PARITY_COLUMN = "liability_cys_parity"

NOVELTY_VERDICT_COLUMN = "novelty_verdict"

PLAUSIBILITY_VERDICT_COLUMN = "structural_plausibility_verdict"
# `structure_plausibility.structural_plausibility_offenders` reads the pool
# column under the SHORTER spelling `structural_plausibility`. Both are read, in
# this order, so whichever spelling the schema lands the verdict half still
# runs; a sheet carrying only the legacy spelling would otherwise be checked on
# its evidence terms alone, which is the half that determines least.
PLAUSIBILITY_LEGACY_VERDICT_COLUMN = "structural_plausibility"
PLAUSIBILITY_TERM_COLUMN_PREFIX = "plausibility_"

SEQUENCE_COLUMN = "sequence"
DESIGN_ID_COLUMN = "design_id"


# ── the named `not_recomputable` reasons ───────────────────────────────────
#
# Constants rather than inline strings because they are dict KEYS in the
# returned record: the integrator groups by them and the tests assert on them,
# and a reason spelled two ways is a reason reported under one spelling and
# looked for under the other.
ROW_NOT_A_MAPPING = "the sheet row is not a mapping"

LIABILITY_NO_SEQUENCE = (
    "the row carries no readable sequence, so no liability term can be "
    "recomputed from it"
)
LIABILITY_NO_TERM_COLUMNS = (
    "no liability term column is filled on the row (the terms are recorded, and "
    "a row that records none of them contradicts nothing)"
)

NOVELTY_NO_SEQUENCE = (
    "the row carries no readable sequence, so no novelty arm could be re-run"
)
NOVELTY_NOT_DETERMINED = (
    "the re-screen tripped no arm, and a clean screen here covers strictly "
    "fewer subjects than the FINAL tier requires (UniRef90 is never staged in "
    "this process), so it determines nothing about the carried verdict"
)

MONOMER_NO_DESIGN_ID = (
    "the row carries no design_id to look its monomer fold measurement up by"
)
MONOMER_NOT_FETCHED = "no monomer fold measurement was fetched for this design"
MONOMER_FETCHED_NOT_A_NUMBER = (
    "the fetched monomer measurement is not a usable number"
)
MONOMER_NO_CARRIED_VALUE = (
    "no monomer_plddt on the row to compare (the column is recorded, never "
    "demanded, so an absent cell is a disclosed NOT_RUN)"
)
MONOMER_CARRIED_UNPARSEABLE = (
    "a filled monomer_plddt that is not a number -- reported by "
    "`_screen_gate_row_offenders` under its own field, and naming it twice "
    "would send the writer two different repairs for one cell"
)

PLAUSIBILITY_NO_DESIGN_ID = (
    "the row carries no design_id to look its predicted structure up by"
)
PLAUSIBILITY_NO_STRUCTURE = "no predicted structure was fetched for this design"
PLAUSIBILITY_NO_CHAIN = (
    "no binder chain was resolved for this design, and an unnamed chain on a "
    "complex measures whichever chain came first"
)
PLAUSIBILITY_CHAIN_UNUSABLE = (
    "the fetched structure could not be reduced to the named binder chain"
)
PLAUSIBILITY_NOT_DETERMINED = (
    "the re-run reaches NOT_RUN -- a sub-check could not run here -- and a "
    "partial assessment neither confirms nor contradicts the carried verdict"
)
PLAUSIBILITY_NOTHING_TO_COMPARE = (
    "the row carries neither a structural-plausibility verdict nor any filled "
    f"`{PLAUSIBILITY_TERM_COLUMN_PREFIX}` evidence term"
)


# ── comparison primitives ──────────────────────────────────────────────────
#
# Three-valued, and the third value is the point. `_is_null_sheet_value` says
# "TBD" and `True` are not null while `_as_sheet_float` says they are not
# numbers, and a cell that falls between them is the NOT_RUN/PASS confusion
# `qa.SCREEN_GATE_ROW_UNPARSEABLE_FIELD` was added to close. So the seam is
# closed here too, explicitly, in the only direction that is sound: a cell that
# is NULL is ABSENT (fail open), and a cell that is FILLED but unreadable is a
# CONTRADICTION of a determined number (fail closed). A blank cell and a cell
# holding "TBD" are different facts and get different answers.
_ABSENT = "absent"
_MATCH = "match"
_MISMATCH = "mismatch"


def _compare_float(cell: Any, expected: Any, tolerance: float) -> str:
    """One numeric cell against the number the row's own data determines."""
    if _is_null_sheet_value(cell):
        return _ABSENT
    if expected is None:
        # The recompute did not produce this term at all (an arm that measured
        # nothing, e.g. `peptide_c_n_min_a` on a CA-only trace). Nothing was
        # determined, so nothing can be contradicted.
        return _ABSENT
    carried = _as_sheet_float(cell)
    if carried is None:
        return _MISMATCH
    reference = _as_sheet_float(expected)
    if reference is None:
        return _ABSENT
    return _MATCH if abs(carried - reference) <= tolerance else _MISMATCH


def _compare_token(cell: Any, expected: Any) -> str:
    """One token cell (a parity, a chain id) against the determined token."""
    if _is_null_sheet_value(cell) or _is_null_sheet_value(expected):
        return _ABSENT
    return (
        _MATCH
        if str(cell).strip().upper() == str(expected).strip().upper()
        else _MISMATCH
    )


def _first_filled(row: Mapping[str, Any], *columns: str) -> Any:
    """The first of ``columns`` the row FILLS, not the first it merely has.

    ``row.get(a, row.get(b))`` is the wrong shape for a sheet: a column that is
    present-and-blank is the normal state of a required column
    (``_candidate_csv_rows`` keeps required columns even when every row leaves
    them empty), so the default would never be reached and the alternative
    spelling would never be read.
    """
    for column in columns:
        value = row.get(column)
        if not _is_null_sheet_value(value):
            return value
    return None


class _Record:
    """The record ``recompute_sheet_gate_terms`` returns, built row by row."""

    def __init__(self, gate: str, tolerance: Any) -> None:
        self._gate = gate
        self._tolerance = float(tolerance)
        self._checked = 0
        self._mismatches: list[str] = []
        self._not_recomputable: dict[str, list[str]] = {}

    @property
    def tolerance(self) -> float:
        return self._tolerance

    def skip(self, row_id: str, reason: str) -> None:
        self._not_recomputable.setdefault(reason, []).append(row_id)

    def compared(self, row_id: str, *, agreed: bool) -> None:
        self._checked += 1
        if not agreed:
            self._mismatches.append(row_id)

    def done(self) -> dict[str, Any]:
        return {
            "rows_checked": self._checked,
            "tolerance": self._tolerance,
            "mismatches": self._mismatches,
            "not_recomputable": self._not_recomputable,
            "recomputed": [self._gate],
        }


def _rows_with_ids(rows: Any) -> list[tuple[str, dict[str, Any] | None]]:
    """``(row_id, row)`` for every entry, with a non-mapping entry as ``None``.

    Every entry handed in is accounted for in the returned record -- a row this
    module cannot even read is reported as unreadable rather than dropped, which
    is the same reason ``monomer_foldability_verdicts`` is driven by the ids the
    caller asked about instead of by the rows it found.
    """
    out: list[tuple[str, dict[str, Any] | None]] = []
    for index, row in enumerate(rows or []):
        if not isinstance(row, Mapping):
            out.append((f"row_{index + 1}", None))
            continue
        out.append((_sheet_row_id(row, index), dict(row)))
    return out


# ── (1) liability (protocol L82) ───────────────────────────────────────────


IDENTIFIED_ROWS_GATE = "identified_rows"


def identified_rows_recompute(rows: Any) -> dict[str, Any]:
    """L86 at the FINAL sheet: every shipped row owes an id.

    A row with no ``design_id`` cannot be matched against any reject record, so
    it is a HOLE IN THE VERIFICATION rather than a violation of it — nothing
    upstream ever checked it, and nothing downstream can. On a sheet that is
    decisive: `design_id` is the key every gate verdict, every reject and every
    provenance term is joined on, so an unidentified row ships carrying claims
    that were never tested against anything.

    THIS USED TO LIVE IN THE WRONG PLACE, which is why it never ran.
    ``prescoring_gate_pool_violations`` takes a ``require_identified_rows``
    flag, and the plan was to arm it at the sheet — but the sheet writer does
    not call that function at all. It is reached only from
    ``_execute_wave_triage``, where the check is ALSO vacuous, because
    ``missing_pool_row_fields`` raises on a missing ``design_id`` before the
    prescreen runs. So the flag had no caller that could turn it on and no tier
    where it would have found anything. Moved here, to the one pass that both
    ships rows and can see them.

    Reported as MISMATCHES, not as ``not_recomputable``, and that is the whole
    point of the check: an absent id is not "we could not tell", it is the
    finding. Every other comparator in this module fails open on absence
    because absence there means an input was missing; here the absence IS the
    defect.
    """
    mismatches = [
        row_id
        for index, row in enumerate(rows or [])
        if not (
            isinstance(row, Mapping)
            and _sheet_id_value(row.get(DESIGN_ID_COLUMN))
        )
        for row_id in (_sheet_row_id(row, index) if isinstance(row, Mapping) else str(index),)
    ]
    return {
        "rows_checked": len(list(rows or [])),
        "tolerance": 0.0,
        "mismatches": mismatches,
        "not_recomputable": {},
        "recomputed": [IDENTIFIED_ROWS_GATE],
    }


def liability_recompute(
    rows: Any,
    *,
    tolerance: float = SHEET_RECOMPUTE_TOLERANCE,
) -> dict[str, Any]:
    """Re-derive the four liability terms from each row's own sequence (L90/L82).

    ``composition_liability_flags`` already returns its raw numbers rather than
    only its booleans, with the comment "so the sheet writer can recompute and
    match to 1e-4" -- and until the columns existed there was nothing to match
    them against. This is the other half of that sentence.

    EVERY TERM IS INDEPENDENTLY DETERMINED BY THE SEQUENCE, and that is the one
    place this diverges from ``recompute_sheet_gate_terms``. There, partial
    column coverage made the ARITHMETIC undeterminable -- a mean over an unknown
    set of terms -- so a partially covered row had to be skipped whole. Here
    each of the four columns is a separate function of the sequence alone, so a
    row carrying two of them is checked on those two and is silent about the
    other two. Skipping such a row entirely would discard a sound check; calling
    the absent columns wrong would invent one.

    A row is ``not_recomputable`` only when NO term could be compared: either
    its sequence is unreadable (the input is missing) or none of the four
    columns is filled (there is no claim to check).
    """
    record = _Record(PRESCORING_GATE_LIABILITY, tolerance)
    for row_id, row in _rows_with_ids(rows):
        if row is None:
            record.skip(row_id, ROW_NOT_A_MAPPING)
            continue
        sequence = row.get(SEQUENCE_COLUMN)
        flags = composition_liability_flags(sequence)
        if flags.get("error"):
            # `composition_liability_flags` fails CLOSED for the gate's own
            # purposes (flagged=True on an unreadable sequence) but emits none
            # of the numeric keys, so there is nothing here to compare. That is
            # absence of an INPUT, and the unreadable sequence itself is the
            # `sequence` mandatory-column failure, reported there.
            record.skip(row_id, LIABILITY_NO_SEQUENCE)
            continue
        homopolymer = flags.get("homopolymer")
        expected_numeric = {
            LIABILITY_MIN_WINDOW_ENTROPY_COLUMN: flags.get("min_window_entropy_bits"),
            LIABILITY_MAX_HYDROPHOBIC_PATCH_COLUMN: flags.get(
                "max_hydrophobic_patch_fraction"
            ),
            LIABILITY_MAX_HOMOPOLYMER_RUN_COLUMN: (
                homopolymer.get("longest_run")
                if isinstance(homopolymer, Mapping)
                else None
            ),
        }
        outcomes = [
            _compare_float(row.get(column), expected, record.tolerance)
            for column, expected in expected_numeric.items()
        ]
        parity = flags.get("cys_parity")
        outcomes.append(
            _compare_token(
                row.get(LIABILITY_CYS_PARITY_COLUMN),
                parity.get("parity") if isinstance(parity, Mapping) else None,
            )
        )
        if all(outcome == _ABSENT for outcome in outcomes):
            record.skip(row_id, LIABILITY_NO_TERM_COLUMNS)
            continue
        record.compared(row_id, agreed=_MISMATCH not in outcomes)
    return record.done()


# ── (2) novelty (protocol L81, at the FINAL tier of L79) ───────────────────


def novelty_recompute(
    rows: Any,
    *,
    corpus: Any,
    target_chains: Iterable[Any] = (),
    control_chains: Iterable[Any] = (),
    tolerance: float = SHEET_RECOMPUTE_TOLERANCE,
) -> dict[str, Any]:
    """Re-screen every row's sequence against the subjects this process holds.

    THE FINAL-TIER PROBLEM, AND WHAT IS DONE ABOUT IT. At the sheet the tier is
    FINAL, and ``NOVELTY_REQUIRED_SUBJECTS_FINAL`` includes UniRef90 -- which is
    never staged in this process and which this function's signature has no
    parameter to receive. So a naive final-tier re-run returns NOT_RUN for every
    row, "matches" nothing, and reports a clean recompute record that means
    exactly nothing. That is worse than not running: it is a green light with no
    measurement behind it.

    So the re-screen is used ONE-DIRECTIONALLY, and the direction is the sound
    one:

      * A REJECT IS DETERMINATE. ``novelty_verdict`` returns REJECT the moment
        any arm trips on any subject it was actually given, independently of
        what else was unavailable -- "a proven copy is a copy whether or not
        UniRef90 was staged". Ubiquitin alone (``check_ubiquitin`` is on by
        default and needs no staging at all) makes this a live check on every
        campaign. A row whose sequence re-screens to REJECT must not be on the
        FINAL sheet, and it is reported.

      * A CLEAN SCREEN DETERMINES NOTHING. Clean against a SUBSET of the FINAL
        subject set is not clean against the set: the writer may have held
        UniRef90 hits this process does not. So a clean re-screen never
        contradicts a carried REJECT, never confirms a carried PASS, and is
        recorded as ``not_recomputable`` under ``NOVELTY_NOT_DETERMINED``. In a
        campaign with no staged corpus that will be most rows, and saying so is
        the honest report.

    A DETERMINED REJECT IS A MISMATCH WHATEVER THE CELL HOLDS SHORT OF REJECT
    ITSELF -- a carried PASS, a carried NOT_RUN, and a blank cell alike. This is
    the "an input is not a claim" half of the module contract: the input this
    check consumes is the row's SEQUENCE, and it is present. The verdict cell is
    the claim being checked, and a row declining to state a verdict does not
    make a proven ubiquitin copy admissible. (Contrast
    ``recompute_sheet_gate_terms``, where a null ``final_score`` leaves
    genuinely nothing to compare a mean against.) A row that carries REJECT is
    NOT reported: the recompute and the carried value agree, which is all L90
    asks of this function, and a REJECT that reached the sheet at all is the
    pool checks' finding under their own name, not a reproduction failure.

    ``tolerance`` is accepted and echoed so the record is the same object the
    other three return, but a verdict is a TOKEN: no float comparison happens
    here and the tolerance does not participate in any decision.
    """
    record = _Record(PRESCORING_GATE_NOVELTY, tolerance)
    entries = _rows_with_ids(rows)
    # Keyed by ROW POSITION, never by design_id. `novelty_verdicts` skips an id
    # it has already seen (`if not design_id or design_id in verdicts`), so two
    # rows sharing a design_id -- or carrying none -- would collapse into one
    # screen and the second row would silently vanish from the denominator. A
    # positional key is unique by construction and cannot be blank.
    sequences: dict[str, Any] = {}
    for position, (row_id, row) in enumerate(entries):
        if row is None:
            record.skip(row_id, ROW_NOT_A_MAPPING)
            continue
        if not str(row.get(SEQUENCE_COLUMN) or "").strip():
            record.skip(row_id, NOVELTY_NO_SEQUENCE)
            continue
        sequences[str(position)] = row.get(SEQUENCE_COLUMN)
    if not sequences:
        return record.done()
    outcome = novelty_verdicts(
        sequences,
        corpus=corpus,
        target_chains=target_chains,
        control_chains=control_chains,
        required_subjects=NOVELTY_REQUIRED_SUBJECTS_FINAL,
    )
    verdicts = outcome.get("verdicts") or {}
    for position, (row_id, row) in enumerate(entries):
        key = str(position)
        if key not in sequences or row is None:
            continue
        if verdicts.get(key) != VERDICT_REJECT:
            # Covers both shapes of "no verdict reached": the required subjects
            # this process cannot stage, and a sequence the aligner refused
            # (`novelty_verdicts` turns a LocalAlignmentError into that design's
            # NOT_RUN rather than the pool's crash). Neither determines anything.
            record.skip(row_id, NOVELTY_NOT_DETERMINED)
            continue
        carried = _carried_verdict_token(row.get(NOVELTY_VERDICT_COLUMN))
        record.compared(row_id, agreed=carried == VERDICT_REJECT)
    return record.done()


# ── (3) monomer foldability (protocol L83, at L246's frozen floor) ─────────


def _monomer_verdict(value: float, floor: float) -> str:
    """S1b's own thresholding, spelled as ``monomer_foldability_verdicts`` does."""
    return MONOMER_VERDICT_PASS if value >= floor else MONOMER_VERDICT_REJECT


def monomer_recompute(
    rows: Any,
    plddt_by_design_id: Mapping[Any, Any],
    *,
    floor: float,
    tolerance: float = SHEET_RECOMPUTE_TOLERANCE,
) -> dict[str, Any]:
    """Each row's carried ``monomer_plddt`` against the value that was fetched.

    ``plddt_by_design_id`` holds values the CALLER already fetched. The fetch is
    an await against the fold jobs and belongs to the integrator; a pure
    function that did its own I/O could not be tested at this cost and would put
    an S3 read inside a writer's validation loop.

    ``floor`` IS A PARAMETER, NOT A CONSTANT, and that is protocol L246: the
    monomer threshold is frozen PER TARGET at the validation gate.
    ``MONOMER_PLDDT_FLOOR_THRESHOLD`` (0.70) is only the floor UNDER that value
    -- a campaign may freeze something stricter -- so the row-level guard in
    ``qa._screen_gate_row_offenders``, which reads the row's own cell against
    the global floor, cannot see a design at 0.80 under a frozen 0.85. This can.

    A row is a mismatch when ANY of three things is true, and the third is the
    one a plain numeric comparison cannot see:

      1. the carried number does not reproduce the fetched one to ``tolerance``;
      2. the two numbers agree to ``tolerance`` but land on OPPOSITE SIDES of
         the frozen floor -- 0.69999 carried against 0.70001 fetched agrees to
         2e-5 and is the difference between REJECT and PASS. A tolerance is a
         reproduction bound, never a licence to straddle a threshold;
      3. the FETCHED value does not clear the frozen floor at all. The row's
         presence on the FINAL sheet is its claim to have passed S1b, and a
         recomputed REJECT contradicts that claim whether or not the row also
         copied the number down correctly. There is no monomer VERDICT column,
         so unlike novelty and plausibility there is no carried verdict that
         could agree with the recompute and absolve the row; the number alone
         cannot. At ``floor == MONOMER_PLDDT_FLOOR_THRESHOLD`` this overlaps
         ``qa.MONOMER_ROW_BELOW_FLOOR_FIELD``, and the overlap is accepted
         rather than conditioned away: the two read DIFFERENT numbers (that one
         the row's own cell, this one the fetched ground truth, so only this one
         sees a blank or stale cell) and they name the SAME repair -- drop the
         row, this design does not fold on its own. The rule against two guards
         under two names is about two different repairs for one cell, which
         this is not.

    A BAD ``floor`` RAISES rather than degrading, exactly as
    ``monomer_foldability_verdicts`` raises: NaN is the dangerous one, because
    every ``value >= nan`` is False and the gate would REJECT the entire pool
    while reporting a threshold. That is a caller wiring error affecting every
    row, not a per-row hole, and swallowing it into ``not_recomputable`` would
    hide it behind 30 quiet skips.
    """
    try:
        limit = float(floor)
    except (TypeError, ValueError) as exc:
        raise ScreenGateInputError(
            f"monomer pLDDT floor {floor!r} is not a number."
        ) from exc
    if isinstance(floor, bool) or not math.isfinite(limit):
        raise ScreenGateInputError(
            f"monomer pLDDT floor {floor!r} is not a usable number. NaN is the "
            "dangerous one: every `value >= nan` is False, so every row would "
            "be reported as a mismatch while a threshold was reported."
        )
    # Normalized once, so an integer or whitespace-padded design id on either
    # side of the join still meets its partner. `_sheet_id_value` keeps the
    # integer 0 as a real id rather than reading it as absent.
    fetched_by_id = {
        _sheet_id_value(key): value
        for key, value in (plddt_by_design_id or {}).items()
        if _sheet_id_value(key)
    }
    record = _Record(PRESCORING_GATE_MONOMER_FOLDABILITY, tolerance)
    for row_id, row in _rows_with_ids(rows):
        if row is None:
            record.skip(row_id, ROW_NOT_A_MAPPING)
            continue
        design_id = _sheet_id_value(row.get(DESIGN_ID_COLUMN))
        if not design_id:
            record.skip(row_id, MONOMER_NO_DESIGN_ID)
            continue
        if design_id not in fetched_by_id:
            record.skip(row_id, MONOMER_NOT_FETCHED)
            continue
        fetched = _as_sheet_float(fetched_by_id[design_id])
        if fetched is None:
            record.skip(row_id, MONOMER_FETCHED_NOT_A_NUMBER)
            continue
        # (3) first, because it is the only one that survives a blank cell: the
        # fetched value has to clear the FROZEN floor for the row to belong on
        # the sheet at all.
        agreed = _monomer_verdict(fetched, limit) == MONOMER_VERDICT_PASS
        cell = row.get(MONOMER_ROW_MEASUREMENT_TERM)
        carried = _as_sheet_float(cell)
        if carried is None:
            # No carried number, so (1) and (2) cannot be asked. If (3) already
            # condemns the row that stands on its own; otherwise there is
            # genuinely nothing here to compare.
            if agreed:
                record.skip(
                    row_id,
                    MONOMER_NO_CARRIED_VALUE
                    if _is_null_sheet_value(cell)
                    else MONOMER_CARRIED_UNPARSEABLE,
                )
                continue
        else:
            agreed = (
                agreed
                # (1) the carried number reproduces the fetched one…
                and abs(carried - fetched) <= record.tolerance
                # …and (2) the two land on the SAME side of the frozen floor,
                # which a sub-tolerance difference across it does not.
                and _monomer_verdict(carried, limit) == _monomer_verdict(fetched, limit)
            )
        record.compared(row_id, agreed=agreed)
    return record.done()


# ── (4) structural plausibility (protocol L84) ─────────────────────────────


def _plausibility_expected_by_column(
    measurements: Mapping[str, Any],
) -> dict[str, Any]:
    """Sheet column -> the value this re-run determined for it.

    ``structural_plausibility_verdict`` flattens its measurements to DOTTED
    scalar keys (`backbone_geometry.ca_ca_min_a`) precisely so a row-versus-row
    comparison can walk them. THREE sheet spellings of the same term are
    accepted, because a CSV header carrying a dot is awkward and the schema is
    free to shorten:

      * dotted, as emitted -- `plausibility_backbone_geometry.ca_ca_min_a`
      * underscored        -- `plausibility_backbone_geometry_ca_ca_min_a`
      * SHORT, the check name dropped -- `plausibility_ca_ca_min_a`, which is
        the spelling the schema actually landed (`plausibility_rg_ratio`,
        `plausibility_clashscore`, `plausibility_buried_fraction`, …).

    THE SHORT SPELLING IS OFFERED ONLY WHERE IT IS UNAMBIGUOUS. All three
    sub-checks emit `chain` and `residues`, so a short column for a leaf name
    two checks disagreed about would be compared against whichever happened to
    be written last -- a comparison whose answer depends on dict order. Such a
    leaf is left with its qualified spellings only: the term goes unchecked,
    which is the fail-open half of the contract, rather than checked against a
    coin flip.

    NOT EVERY FLATTENED KEY IS A MEASUREMENT.
    ``steric_clashes.clashscore_normalization`` is a CONSTANT -- it is a key of
    ``STRUCTURAL_PLAUSIBILITY_THRESHOLDS``, echoed into ``measurements`` as a
    description of how the score is normalized -- so a sheet column carrying it
    would compare a constant to itself and could never fail: the same trap
    ``liability_max_homopolymer_run`` sits beside. Nothing is filtered out here,
    because the comparison is driven by the columns the schema actually lands
    and a term nobody carries is never read; the note is for whoever is tempted
    to mint one column per flattened key. ``chain`` is NOT in that category --
    it echoes the binder chain the integrator resolved, so a sheet naming a
    different one is a real finding.
    """
    columns: dict[str, Any] = {}
    by_leaf: dict[str, list[Any]] = {}
    for key, value in measurements.items():
        text = str(key)
        columns[f"{PLAUSIBILITY_TERM_COLUMN_PREFIX}{text}"] = value
        columns[f"{PLAUSIBILITY_TERM_COLUMN_PREFIX}{text.replace('.', '_')}"] = value
        by_leaf.setdefault(text.split(".", 1)[-1], []).append(value)
    for leaf, values in by_leaf.items():
        short = f"{PLAUSIBILITY_TERM_COLUMN_PREFIX}{leaf}"
        if short in columns or any(value != values[0] for value in values):
            continue
        columns[short] = values[0]
    return columns


def plausibility_recompute(
    rows: Any,
    structures_by_design_id: Mapping[Any, Any],
    *,
    chain_by_design_id: Mapping[Any, Any],
    thresholds: Mapping[str, Any] | None = None,
    tolerance: float = SHEET_RECOMPUTE_TOLERANCE,
) -> dict[str, Any]:
    """Re-run L84 on each row's fetched structure and compare what it carries.

    Takes ALREADY-FETCHED structures and an ALREADY-RESOLVED binder chain per
    design, for the reason ``monomer_recompute`` takes fetched pLDDTs: the S3
    read and the chain resolution are awaits that belong to the integrator.

    THE BINDER CHAIN IS REQUIRED, NOT OPTIONAL. A design's
    ``designed_structure_path`` is its COMPLEX, and on a multi-chain file an
    unnamed chain is the wrong molecule silently measured -- a target that folds
    beautifully on its own, scored as though it were the binder. So a design
    with no resolved chain is ``not_recomputable``, never guessed at.

    THE MULTI-CHAIN RAISE IS CAUGHT HERE, and the divergence from
    ``structural_plausibility_verdicts`` is deliberate -- DO NOT "FIX" IT BACK.
    That function lets ``StructurePlausibilityInputError`` propagate on the
    reasoning that a caller handing complexes to a monomer gate is a wiring
    error affecting the whole pool, which must not be absorbed into 20,000 quiet
    NOT_RUNs. At the sheet that reasoning does not carry: the chain is resolved
    PER DESIGN, so one design whose chain could not be resolved is exactly the
    per-design hole the pool case was not, and letting it escape would abort the
    recompute for the other 29 rows -- turning a check on 30 rows into a check
    on none. It is caught per design and named, which keeps the fact visible
    without spending the other rows on it.

    WHAT IS DETERMINATE. Unlike novelty, this re-run holds every input it needs,
    so a PASS and a REJECT are both determinate and both compared. A NOT_RUN is
    not: it means a sub-check could not run here, which neither confirms nor
    contradicts what the writer got. As in ``novelty_recompute``, a determined
    REJECT is a mismatch whatever the verdict cell holds SHORT OF REJECT itself
    -- a row this gate condemns must not be on the sheet, and a blank cell does
    not answer that -- while a row that carries REJECT agrees with the recompute
    and is left to ``structural_plausibility_offenders``, which reports a
    surviving REJECT under its own name and its own repair. The evidence terms
    are compared independently of the verdict, on the same per-term basis
    ``liability_recompute`` uses.
    """
    record = _Record(PRESCORING_GATE_STRUCTURAL_PLAUSIBILITY, tolerance)
    structures = {
        _sheet_id_value(key): value
        for key, value in (structures_by_design_id or {}).items()
        if _sheet_id_value(key)
    }
    chains = {
        _sheet_id_value(key): value
        for key, value in (chain_by_design_id or {}).items()
        if _sheet_id_value(key)
    }
    for row_id, row in _rows_with_ids(rows):
        if row is None:
            record.skip(row_id, ROW_NOT_A_MAPPING)
            continue
        design_id = _sheet_id_value(row.get(DESIGN_ID_COLUMN))
        if not design_id:
            record.skip(row_id, PLAUSIBILITY_NO_DESIGN_ID)
            continue
        structure = structures.get(design_id)
        if structure is None or (
            isinstance(structure, str) and not structure.strip()
        ):
            record.skip(row_id, PLAUSIBILITY_NO_STRUCTURE)
            continue
        chain = chains.get(design_id)
        if _is_null_sheet_value(chain):
            record.skip(row_id, PLAUSIBILITY_NO_CHAIN)
            continue
        try:
            outcome = structural_plausibility_verdict(
                structure, chain, thresholds=thresholds
            )
        except StructurePlausibilityInputError:
            record.skip(row_id, PLAUSIBILITY_CHAIN_UNUSABLE)
            continue
        verdict = str(outcome.get("verdict") or "")
        if verdict not in (VERDICT_PASS, VERDICT_REJECT):
            record.skip(row_id, PLAUSIBILITY_NOT_DETERMINED)
            continue
        carried = _carried_verdict_token(
            _first_filled(
                row, PLAUSIBILITY_VERDICT_COLUMN, PLAUSIBILITY_LEGACY_VERDICT_COLUMN
            )
        )
        outcomes: list[str] = []
        if carried == verdict:
            outcomes.append(_MATCH)
        elif verdict == VERDICT_REJECT:
            # Determined REJECT against anything that is not REJECT -- a carried
            # PASS, or a blank/unreadable cell, which `_carried_verdict_token`
            # reads as NOT_RUN. The row must not be on the sheet, and declining
            # to state a verdict does not answer that.
            outcomes.append(_MISMATCH)
        elif carried == VERDICT_NOT_RUN:
            # Determined PASS against a row that says it never ran the gate.
            # That is the row being SILENT, not the row asserting a different
            # answer, so nothing is contradicted and it reads as absence. The
            # asymmetry with the branch above is the whole "an input is not a
            # claim" rule: only one of the two verdicts says the row must go.
            outcomes.append(_ABSENT)
        else:
            # Determined PASS against a carried REJECT: two determinate verdicts
            # that disagree. Which one is right is not this function's call --
            # that they differ is.
            outcomes.append(_MISMATCH)
        expected_by_column = _plausibility_expected_by_column(
            outcome.get("measurements") or {}
        )
        for column, expected in expected_by_column.items():
            if column not in row:
                continue
            outcomes.append(
                _compare_token(row.get(column), expected)
                if isinstance(expected, str)
                else _compare_float(row.get(column), expected, record.tolerance)
            )
        if all(seen == _ABSENT for seen in outcomes):
            record.skip(row_id, PLAUSIBILITY_NOTHING_TO_COMPARE)
            continue
        record.compared(row_id, agreed=_MISMATCH not in outcomes)
    return record.done()
