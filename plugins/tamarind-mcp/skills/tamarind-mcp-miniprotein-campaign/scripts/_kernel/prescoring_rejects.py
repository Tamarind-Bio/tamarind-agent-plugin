"""The traceability half of the pre-scoring filters — protocol L86.

    "Record every rejected design_id and verify its absence from every
     downstream scoring pool; a gate counts as run only when its rejects are
     traceably absent downstream."

That sentence is the reason this module exists as a SHARED thing rather than one
more field on each gate. It is not a property of a gate at all: a gate can only
say what it DECIDED, and L86 asks what the pool KEPT. Only something holding both
the verdict and the surviving rows can answer it, and until now exactly one gate
of the four had such a thing —
``screen_gate_metrics.monomer_gate_pool_violations``, for monomer-foldability.
``rejected_design`` was zero hits repo-wide.

Why the record is not just a list of ids
----------------------------------------
A bare id list makes the pool check work and makes every other consumer guess.
The sheet writer has to RECOMPUTE each gate and match the carried value to 1e-4
(protocol L90), so a reject that does not carry the numbers behind it cannot be
recomputed — the writer would have to re-derive them from an input the reject
does not name. So a reject carries the gate that produced it, a human reason,
and the measurement dict the verdict came from.

The shape, for the caller wiring this into ``qa.py``
---------------------------------------------------
``prescoring_gate_pool_violations(rows, rejects)`` returns
``dict[str, list[str]]`` — the SAME shape ``monomer_gate_pool_violations``
already returns and the same shape ``qa._describe_offenders`` already consumes,
so the wiring at ``qa.py:~3712`` is one more block in the pattern already there
and needs no new formatting code:

    violations = prescoring_gate_pool_violations(surviving, rejects)
    if violations:
        raise RuntimeError(... _describe_offenders(violations, total_rows=len(surviving)) ...)

FAILS OPEN BY CONSTRUCTION, and that is deliberate. With no rejects recorded the
function returns ``{}`` and nothing halts, because "this gate did not run" is a
legitimate NOT_RUN state and a campaign that has not reached a gate yet must not
be blocked by it. What it catches is the strictly worse state: a gate that DID
run, recorded rejects, and whose rejects are sitting in the surviving pool —
which is indistinguishable from never having run the gate except by looking.
``prescoring_gate_coverage`` is the companion that reports the NOT_RUN honestly
rather than letting an empty violation set read as "all four gates clean".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# ── the four pre-scoring gates, protocol L81-L84 ───────────────────────────
#
# Tokens, not free text, for the same reason `structure_method` is a token:
# these are grep targets and dict keys, and a gate spelled two ways is a gate
# whose rejects can be reported under one spelling and checked under the other.
PRESCORING_GATE_NOVELTY = "novelty"  # L81
PRESCORING_GATE_LIABILITY = "liability"  # L82
PRESCORING_GATE_MONOMER_FOLDABILITY = "monomer_foldability"  # L83
PRESCORING_GATE_STRUCTURAL_PLAUSIBILITY = "structural_plausibility"  # L84
# L88 is a separate sentence from the numbered four, and a separate idea: a
# redundancy cluster member is not "rejected" for being bad, it is collapsed for
# being a duplicate of something else in the pool. It is carried here because it
# is ALSO a pre-scoring pass whose removals must be traceably absent downstream,
# and a second mechanism for the same sentence is how two mechanisms disagree.
PRESCORING_GATE_REDUNDANCY = "redundancy"  # L88

PRESCORING_GATES: tuple[str, ...] = (
    PRESCORING_GATE_NOVELTY,
    PRESCORING_GATE_LIABILITY,
    PRESCORING_GATE_MONOMER_FOLDABILITY,
    PRESCORING_GATE_STRUCTURAL_PLAUSIBILITY,
    PRESCORING_GATE_REDUNDANCY,
)

# The four the protocol numbers at L81-L84 and says EVERY candidate must be
# assessed for before being scored. Redundancy is excluded on purpose: L88 makes
# it a pool-level pass, not a per-candidate assessment, so "was this design
# assessed" is not a question it answers.
PRESCORING_MANDATORY_GATES: tuple[str, ...] = (
    PRESCORING_GATE_NOVELTY,
    PRESCORING_GATE_LIABILITY,
    PRESCORING_GATE_MONOMER_FOLDABILITY,
    PRESCORING_GATE_STRUCTURAL_PLAUSIBILITY,
)

# ── the verdict vocabulary ─────────────────────────────────────────────────
#
# Deliberately the SAME three strings `screen_gate_metrics.MONOMER_VERDICT_*` and
# `qa_tm_helpers.target_mimic_screen` already emit. They are re-declared here
# rather than imported so a new gate module can depend on this module alone — but
# `tests/test_campaign_prescoring_gates.py::test_verdict_vocabulary_is_one_vocabulary`
# pins them equal to the originals, so the duplication cannot drift into two
# vocabularies.
VERDICT_PASS = "PASS"
VERDICT_REJECT = "REJECT"
VERDICT_NOT_RUN = "NOT_RUN"
VERDICTS: tuple[str, ...] = (VERDICT_PASS, VERDICT_REJECT, VERDICT_NOT_RUN)


class PrescoringRejectError(ValueError):
    """A reject record that cannot be traced is not a reject record."""


@dataclass(frozen=True)
class PrescoringReject:
    """One design, one gate, and the numbers the REJECT was read off.

    ``measurements`` is the part that earns its keep. Protocol L90 makes the
    sheet writer recompute every gate and match to 1e-4; a reject carrying only
    an id forces the writer to re-derive the inputs from something the record
    does not name, and "re-derive it and hope" is how a recomputation disagrees
    with the computation while both look right. So the record carries the same
    dict the gate's own ``measurements`` map holds for that design.

    Frozen because a reject is evidence. A caller that can edit the reason after
    the fact can make a pool check pass by editing the record instead of the
    pool.
    """

    design_id: str
    gate: str
    reason: str
    measurements: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        design_id = str(self.design_id).strip()
        if not design_id:
            # An unnamed reject is exactly the failure L86 describes: the gate
            # reports a rejection and nothing downstream can check for it.
            raise PrescoringRejectError(
                "a reject must name its design_id — an anonymous reject cannot be "
                "verified absent from any pool, which is the whole of L86"
            )
        if self.gate not in PRESCORING_GATES:
            raise PrescoringRejectError(
                f"unknown pre-scoring gate {self.gate!r}; expected one of "
                f"{', '.join(PRESCORING_GATES)}"
            )
        if not str(self.reason).strip():
            raise PrescoringRejectError(
                f"reject of {design_id!r} by {self.gate} carries no reason. The "
                "campaign has to be able to tell a reviewer WHY a design was "
                "destroyed, and 'the gate said so' is not that."
            )
        object.__setattr__(self, "design_id", design_id)
        object.__setattr__(self, "measurements", dict(self.measurements or {}))

    def as_record(self) -> dict[str, Any]:
        """The JSON-able form that travels on a pool artifact."""
        return {
            "design_id": self.design_id,
            "gate": self.gate,
            "reason": self.reason,
            "measurements": dict(self.measurements),
        }


def rejects_from_verdicts(
    verdicts: Mapping[str, Any],
    gate: str,
    *,
    reasons: Mapping[str, Any] | None = None,
    measurements: Mapping[str, Any] | None = None,
    default_reason: str | None = None,
) -> list[PrescoringReject]:
    """Turn one gate's ``{design_id: verdict}`` map into reject records.

    Every gate in this family returns the ``monomer_foldability_verdicts`` shape
    — ``{"verdicts", "passed", "rejected", "not_run", "measurements", ...}`` — so
    this is the one place that shape becomes records, rather than five places
    that each nearly do.

    NOT_RUN produces NOTHING, and that is the point of separating the two: a
    design the gate could not assess has not been rejected, and recording it as
    one would destroy work on the strength of a missing measurement. It is
    ``prescoring_gate_coverage`` that keeps NOT_RUN visible.
    """
    if gate not in PRESCORING_GATES:
        raise PrescoringRejectError(
            f"unknown pre-scoring gate {gate!r}; expected one of "
            f"{', '.join(PRESCORING_GATES)}"
        )
    reason_map = dict(reasons or {})
    measurement_map = dict(measurements or {})
    out: list[PrescoringReject] = []
    for design_id, verdict in verdicts.items():
        if str(verdict) != VERDICT_REJECT:
            continue
        reason = str(reason_map.get(design_id) or default_reason or "").strip()
        if not reason:
            raise PrescoringRejectError(
                f"{gate} rejected {design_id!r} with no reason. Pass `reasons` "
                "keyed by design_id, or a `default_reason` naming the threshold."
            )
        raw = measurement_map.get(design_id)
        out.append(
            PrescoringReject(
                design_id=str(design_id),
                gate=gate,
                reason=reason,
                measurements=raw if isinstance(raw, Mapping) else {"value": raw},
            )
        )
    return out


# ── the pool half ──────────────────────────────────────────────────────────

# One field string per gate, phrased the way `qa._describe_offenders` renders it
# ("<field>: id, id (+N more)"). Built from the gate token so a gate added to
# `PRESCORING_GATES` cannot be forgotten here.
def _survived_field(gate: str) -> str:
    return (
        f"{gate} REJECTs the pool kept (protocol L86: a gate counts as run only "
        "when its rejects are traceably absent downstream)"
    )


POOL_REJECT_SURVIVED_FIELDS: dict[str, str] = {
    gate: _survived_field(gate) for gate in PRESCORING_GATES
}

POOL_REJECT_UNIDENTIFIED_FIELD = (
    "surviving rows with no design_id, so no gate's rejects can be verified "
    "absent from them (protocol L86)"
)


def _row_design_ids(rows: Any) -> tuple[dict[str, list[str]], list[str]]:
    """``({normalized id: [row labels]}, [rows with no id])``.

    Case-folded, because a pool that re-cases an id has not removed the design.
    The reject side is normalized the same way at the comparison, and
    ``test_a_recased_id_is_still_the_same_design`` pins the pair.
    """
    seen: dict[str, list[str]] = {}
    unidentified: list[str] = []
    for index, row in enumerate(rows or []):
        if not isinstance(row, Mapping):
            continue
        raw = row.get("design_id")
        design_id = "" if raw is None else str(raw).strip()
        label = design_id or f"row_{index + 1}"
        if not design_id:
            unidentified.append(label)
            continue
        seen.setdefault(design_id.casefold(), []).append(label)
    return seen, unidentified


def prescoring_gate_pool_violations(
    rows: Any,
    rejects: Iterable[Any],
    *,
    require_identified_rows: bool = False,
) -> dict[str, list[str]]:
    """Rejected designs that are still in the surviving pool. Offenders by field.

    THE L86 CHECK. Returns ``{}`` — so nothing halts — when no rejects were
    recorded, which is today's state for every gate but monomer-foldability and
    is a legitimate NOT_RUN. Pair it with :func:`prescoring_gate_coverage` so
    that NOT_RUN is disclosed rather than read as a clean pass.

    ``require_identified_rows`` is OFF by default and is the one knob here.
    A surviving row with no ``design_id`` cannot be checked against any reject —
    it is a hole in the verification, not a violation of it — and a wave whose
    rows are keyed some other way would otherwise be halted by a check that
    found nothing wrong. Turn it on at the FINAL sheet, where every row owes an
    id anyway.

    Shape matches ``screen_gate_metrics.monomer_gate_pool_violations`` exactly
    (``dict[str, list[str]]``, field -> offending ids) so both feed
    ``qa._describe_offenders`` unchanged.
    """
    by_id, unidentified = _row_design_ids(rows)
    offenders: dict[str, list[str]] = {}
    for reject in rejects or []:
        record = reject if isinstance(reject, PrescoringReject) else _coerce(reject)
        if record is None:
            continue
        hits = by_id.get(record.design_id.casefold())
        if not hits:
            continue
        field_name = POOL_REJECT_SURVIVED_FIELDS.get(
            record.gate, _survived_field(record.gate)
        )
        bucket = offenders.setdefault(field_name, [])
        for label in hits:
            # Two gates can reject the same design and both are real findings,
            # but one gate must not name the same row twice just because the
            # pool carries it twice.
            if label not in bucket:
                bucket.append(label)
    if require_identified_rows and unidentified:
        offenders[POOL_REJECT_UNIDENTIFIED_FIELD] = unidentified
    return offenders


def _coerce(raw: Any) -> PrescoringReject | None:
    """A dict off a JSON artifact, back into a record. ``None`` when it is not one.

    Skips rather than raises on a shapeless entry: this runs over a pool artifact
    the model wrote, and halting a wave because one list element was a bare
    string would be a false halt. A bare string with no gate is not a traceable
    reject and the coverage report is where that shows up.
    """
    if not isinstance(raw, Mapping):
        return None
    design_id = str(raw.get("design_id") or "").strip()
    gate = str(raw.get("gate") or "").strip()
    if not design_id or gate not in PRESCORING_GATES:
        return None
    measurements = raw.get("measurements")
    return PrescoringReject(
        design_id=design_id,
        gate=gate,
        reason=str(raw.get("reason") or "unstated").strip() or "unstated",
        measurements=measurements if isinstance(measurements, Mapping) else {},
    )


def prescoring_gate_coverage(
    design_ids: Iterable[Any],
    verdicts_by_gate: Mapping[str, Mapping[str, Any]],
    *,
    gates: Iterable[str] = PRESCORING_MANDATORY_GATES,
) -> dict[str, Any]:
    """Which of the mandatory gates actually reached each design.

    The companion to the violation check, and the reason an empty violation set
    cannot be read as "the pre-scoring filters ran". Protocol L79: "Every
    candidate must, BEFORE being scored, be assessed for" all four. A design that
    no gate ever saw is not a passing design; it is an unassessed one, and the
    difference is invisible in a list of rejects.

    Returns ``{"assessed", "unassessed", "not_run_by_gate", "gates"}``.
    ``unassessed`` is the headline: designs missing a verdict from at least one
    mandatory gate, with the gates named.
    """
    wanted = [gate for gate in gates]
    unknown = [gate for gate in wanted if gate not in PRESCORING_GATES]
    if unknown:
        raise PrescoringRejectError(
            f"unknown pre-scoring gate(s) {', '.join(unknown)}; expected from "
            f"{', '.join(PRESCORING_GATES)}"
        )
    ids: list[str] = []
    for raw_id in design_ids:
        # Mirrors `monomer_foldability_verdicts`' own id normalization, including
        # its refusal to let `str(raw or "")` swallow the integer 0.
        design_id = "" if raw_id is None else str(raw_id).strip()
        if design_id and design_id not in ids:
            ids.append(design_id)

    assessed: list[str] = []
    unassessed: dict[str, list[str]] = {}
    not_run_by_gate: dict[str, list[str]] = {gate: [] for gate in wanted}
    for design_id in ids:
        missing: list[str] = []
        for gate in wanted:
            verdict = str((verdicts_by_gate.get(gate) or {}).get(design_id) or "")
            if verdict == VERDICT_NOT_RUN:
                not_run_by_gate[gate].append(design_id)
                missing.append(gate)
            elif verdict not in (VERDICT_PASS, VERDICT_REJECT):
                # No verdict at all, or a verdict outside the vocabulary. Both
                # are "this gate did not reach this design"; neither is a pass.
                missing.append(gate)
        if missing:
            unassessed[design_id] = missing
        else:
            assessed.append(design_id)
    return {
        "gates": tuple(wanted),
        "assessed": assessed,
        "unassessed": unassessed,
        "not_run_by_gate": {g: v for g, v in not_run_by_gate.items() if v},
    }
