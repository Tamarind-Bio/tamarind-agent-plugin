"""The RETURN LEG of the two pre-scoring screens: S1b monomer foldability, and
ESM-C sequence feasibility.

Both screens were named in the miniprotein prompts and consumed nowhere. For
``monomer_plddt`` the submit half is real, working code — ``buildScoringBatch``
with ``construct="monomer_binder"`` folds each binder with no target chain joined
on, and Anthropic prescribes that over roughly 4,000 designs — so the GPU spend
already happens and filters nothing. This module reads the result back out and
turns it into a verdict.

Layering, and why it is not one layer
------------------------------------
``ipsae_min_from_pair_columns`` is the worked example, and it lives in TWO places
at once: it is inlined into sandbox analysis code by ``code_analysis``, AND it is
imported app-side by ``scoring_batch.ipsae_ranking_coverage`` /
``select_argmax_ipsae_min_row``. This module mirrors the second half of that —
pure functions over metrics rows, imported by app-side callers — and reuses
``qa_analysis_helpers``' own column resolver and design-id join rather than
re-implementing either, so a table that joins one way for sc_DockQ cannot join a
different way here.

It is deliberately NOT in ``qa_analysis_helpers`` itself. That module is prepended
WHOLE into a sandbox program whenever the dependency slice cannot be proven, and
``tests/test_campaign_miniprotein_integration.py::
test_helper_source_still_leaves_room_for_analysis_code`` bounds that fallback at
20,000 characters of remaining headroom. The module sits at 99,648 CHARACTERS —
the figure the guard measures, through ``len(read_text())``. ``wc -c`` says
99,675 because the file is full of multi-byte dashes, and a reviewer reading the
byte count computed the headroom as 324; it is 351. Either way these functions
cannot go there without
lowering that bound — which is not a call to make while landing a feature that
wants the room. The cost of the split is real and worth stating: the QA model
cannot call these two BY NAME inside a runAnalysisCode program the way it can
call ``sc_dockq_from_batch_csv``. The app-side gate below does not depend on it.

Column spellings — READ OFF REAL ARCHIVED JOBS, not off tool cards
------------------------------------------------------------------
``1qk0l/metrics.csv``  -> ``seed,sample,plddt,ptm,iptm``
``b4wt2/metrics.csv``  -> ``entry_id,sample,plddt,ptm,iptm``
    Both are esmfold2 MONOMER runs. ``plddt`` is the mean per-residue pLDDT on
    the 0-1 scale (0.8067602515220642, 0.5576937794685364), ONE ROW PER (seed,
    sample) — five rows in each job — and ``iptm`` is exactly 0.0. Neither
    carries an ipSAE_* or pDockQ_* column; the live esmfold2 schema declares both
    families multimer-only.

``esmc-6b-example-aqofm/global_score.csv`` -> a lone ``score`` column holding
    4.2711710929870605, matching that job's own log line "esmc-scan done:
    global_score=4.271171".

TWO TOOLS WRITE THAT SAME FILE AND THAT SAME COLUMN WITH DIFFERENT QUANTITIES.
    ``esmc-6b`` with ``task="scan"``  -> "Mean pseudo negative log-likelihood
        (nats) ... computed as -mean(log P) ... This is an NLL, not a perplexity
        (perplexity would be exp of this value and never below 1)."
    ``esmc-scan``                     -> "Pseudo-perplexity of the input sequence
        under the ESM-C masked language model distribution."
    Same ``global_score.csv``, same ``score`` header, and the numbers overlap
    (an NLL is >= 0, a perplexity is >= 1), so NOTHING IN THE VALUE distinguishes
    them. ``esmc_ll = -score`` is right for the first and wrong for the second by
    a logarithm. v1 therefore FREEZES the first — it emits the quantity the
    column is named for, and its ``sequence`` field sets ``sequenceBatching`` so a
    whole pool goes in as one batch — and requires every shipped ``esmc_ll`` to
    name the tool it came from (``ESMC_LL_TOOL``).

``esmc-inference`` is not a candidate at all: it runs "an ESM-C model you
finetuned via ESMC Finetune", and its ``predicted`` column is "a regression
value, a single-label logit, or a masked-LM pseudo-perplexity; scale and
direction are model-dependent, so no cross-molecule scoring direction is
asserted".
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from ._rubric_constants import (
    ESMC_LL_TOOL,
    MONOMER_CHECK_NOT_RUN_CODE,
    MONOMER_GATE_STAGE_TOKEN,
    MONOMER_PLDDT_FLOOR_THRESHOLD,
    MONOMER_PLDDT_SEED_AGGREGATION,
)
from .qa_analysis_helpers import (
    _BATCH_COLUMN_SUFFIX,
    _DESIGN_ID_COLUMNS,
    _as_float,
    _member_design_token,
    _member_token_matches_design,
    _resolve_metric_column,
    _row_float,
    _sanitized_design_token,
)

# The raw metrics.csv spelling and its batch-aggregate twin both resolve through
# `_row_float`; `mean_plddt` is an alternative SPELLING of the same number, not a
# different metric.
MONOMER_PLDDT_COLUMNS: tuple[str, ...] = ("plddt", "mean_plddt")

# `global_score` is the log's name for the same value the CSV heads `score`.
ESMC_SCAN_SCORE_COLUMNS: tuple[str, ...] = ("score", "global_score")

# Any of these on a row proves it scored an INTERFACE. `iptm` is matched by name
# rather than by prefix because monomer runs emit it too — as exactly 0.0 — so
# only a POSITIVE one is evidence of a second chain.
_INTERCHAIN_COLUMN_PREFIXES: tuple[str, ...] = ("ipsae", "pdockq")
_INTERCHAIN_ZERO_ON_MONOMER_COLUMN = "iptm"


class ScreenGateInputError(ValueError):
    """The table handed in cannot answer the question that was asked of it."""


def cofold_evidence(row: Mapping[str, Any]) -> list[str]:
    """Columns on ``row`` proving it scores an interface, not a lone binder.

    Empty means "nothing here says a second chain was present", which is as much
    as a metrics table can say — absence of an interface column is not proof of a
    monomer fold, only the absence of proof against one. The construct assertion
    on the sheet row (``qa._screen_gate_row_offenders``) is what actually
    establishes it.
    """
    found: set[str] = set()
    for name in row:
        base = str(name).split(_BATCH_COLUMN_SUFFIX)[0].strip().lower()
        if base.startswith(_INTERCHAIN_COLUMN_PREFIXES):
            # A NUMBER, not merely the column. `ipsae_mask` is stamped on every
            # scored row and holds "PER_PROTOMER_MAX(not UNION)"; presence-only
            # matching read that as an interface score and refused a perfectly
            # good monomer table. An all-null pDockQ column is not evidence of a
            # second chain either — which is exactly why `iptm` was value-checked
            # in the first place.
            value = _as_float(row.get(name))
            if value is not None:
                found.add(f"{name}={value}")
        elif base == _INTERCHAIN_ZERO_ON_MONOMER_COLUMN:
            value = _as_float(row.get(name))
            if value is not None and value > 0.0:
                found.add(f"{name}={value}")
    return sorted(found)


def rows_for_design_id(
    rows: Iterable[Any],
    design_id: str | None,
    *,
    member_job_names: Iterable[str] = (),
    allow_token_pass: bool = True,
) -> list[dict[str, Any]]:
    """Every row belonging to one design — or the whole table when unkeyed.

    ``member_job_names`` are names the caller derived deterministically
    (``scoring_member_job_name``); each is accepted as an exact id cell, which is
    the one scope that survives a sanitize collision.

    ``allow_token_pass=False`` drops pass three, leaving exact-or-member-tail only.
    THE LOOSE PASS IS UNUSABLE FOR A SEQUENCE, and that is measured rather than
    cautious: for a NUMBER a loose match is a wrong measurement, but for a SEQUENCE
    it is a wrong MOLECULE — a real, plausible, self-consistent protein belonging to
    another design, indistinguishable from the fabrication the join exists to catch
    and written onto the pool by the fix itself. Sequence callers therefore pass
    ``False`` and take ``[]`` (an honest, recoverable "unjoinable") over a guess.

    ``design_id=None`` means "this table IS one design", which is the shape a
    per-job ``metrics.csv`` actually has: job ``1qk0l`` carries five rows and no
    design-id column at all, because the design identity is the JOB. A batch
    aggregate does carry ids, and then the caller names the one it wants.

    THE THREE PASSES RUN OVER THE WHOLE TABLE, exactly as
    ``_find_row_by_design_id`` runs them, and through THAT MODULE'S OWN cell
    helpers rather than a local retelling of them: every exact cell match first;
    then the member-job-name tail, because a ``{batch}-scores.csv`` carries
    ``{batch}-{sanitize_design_id(id)}`` and NEVER the bare id; then the
    boundary-anchored token match, which skips a cell whose member tail names a
    DIFFERENT design.

    An earlier version called ``_find_row_by_design_id`` per row instead, on the
    reasoning that reusing it verbatim could not drift. It drifted anyway, and
    silently: feeding it one row at a time collapses its two ordered passes into
    a per-row OR, so exact-beats-token was gone. The token pattern is
    ``(?<![A-Za-z0-9])id(?![A-Za-z0-9])`` and ``_`` is not in that class, so
    ``d_42`` boundary-matches inside ``d_42_2`` — a DIFFERENT design, and a
    routine one here: ``resolve_scoring_member_names`` appends ``_2`` on a
    sanitize collision and ``_{sha1[:8]}`` on truncation, and the sheet has a
    ``parent_design_id`` column. Both rows then matched, and because the caller
    takes the MAX, a binder that does not fold on its own (0.55, a REJECT)
    reported its neighbour's 0.93 and PASSED. That is the "gate reports itself as
    run while passing the pool" failure this module exists to prevent, produced
    by the module itself.

    ``_id_cells`` below therefore mirrors the shared join's cell extraction, and
    ``test_the_join_agrees_with_the_shared_one`` pins the two together on the
    cases that distinguish them.

    A SUFFIXED SIBLING NEVER ANSWERS FOR THE DESIGN THAT WAS ASKED FOR. That is
    what the middle pass buys: ``design_spec_074`` and ``design_spec_074_3`` are
    two different member TAILS, where to the token pass one is a substring of the
    other. Before that pass existed the exact pass matched nothing on a real
    aggregate — its id cell is the member job name, never the bare id — so the
    loose token pass decided every real read, matched BOTH rows, and the caller's
    max reported the sibling's number as this design's.

    RESIDUAL, stated rather than papered over: the token pass is still loose
    where no member tail is recoverable, in this module exactly as in the shared
    join — that is the same rule that lets a path-encoded id
    (``.../d_42_model_1.pdb``) join at all, and it and a genuine sibling are not
    separable from such a string. Under a TRUE sanitize collision two ids also
    share one tail. Prefer exact ids.

    NAMING A DESIGN AGAINST AN UNJOINABLE TABLE RAISES, and that is the whole
    reason this wrapper exists rather than a comprehension at each call site. A
    per-job ``metrics.csv`` carries no column in ``_DESIGN_ID_COLUMNS`` at all —
    ``1qk0l`` is keyed on ``seed`` and ``b4wt2`` on ``entry_id``, neither of which
    is a design id — so every id lookup against one returns nothing. Reported as
    an empty match that becomes ``None``, that reads as NOT_RUN: the gate would
    disclose "we could not check this design" when the measurement was sitting
    right there and only the join was wrong. Distinguishing "no row for this
    design" from "no id column to join on" is the entire discipline, so the
    second is an error and only the first is NOT_RUN.
    """
    materialized = [dict(row) for row in rows if isinstance(row, Mapping)]
    if design_id is None:
        return materialized
    wanted = str(design_id).strip()
    if not wanted:
        raise ScreenGateInputError(
            "design_id must be a non-empty id, or None for an unkeyed table"
        )
    if materialized and not _table_carries_a_design_id(materialized):
        raise ScreenGateInputError(
            f"asked for design {wanted!r} from a table with no design-id column "
            f"(looked for {', '.join(_DESIGN_ID_COLUMNS)}; this table has "
            f"{', '.join(sorted(materialized[0]))}). A per-job metrics.csv keyed "
            "on `seed` or `entry_id` is ONE design — pass design_id=None for it. "
            "Returning no match here would report the design as NOT_RUN when only "
            "the join was wrong."
        )
    lowered_wanted = wanted.lower()
    accepted = {lowered_wanted}
    accepted.update(
        str(name).strip().lower() for name in member_job_names or () if str(name).strip()
    )
    exact = [
        row
        for row in materialized
        if any(cell.lower() in accepted for cell in _id_cells(row))
    ]
    if exact:
        return exact

    # PASS TWO: the member-job-name tail. On a real scoring aggregate the id
    # cell is `{batch}-{sanitize_design_id(id)}` and never the bare id, so the
    # exact pass above matches NOTHING and, before this pass existed, the loose
    # token pass decided every real read. `_` is not in that pattern's boundary
    # class, so `design_spec_074` matched inside `{batch}-design_spec_074_2` —
    # a DIFFERENT design — and because this function's callers take the MAX over
    # what it returns, the sibling's higher pLDDT was reported as this design's.
    # That is the exact failure the docstring above says this module exists to
    # prevent, and it survived here while the bare-id case was fixed.
    sanitized = _sanitized_design_token(wanted).lower()
    digest = hashlib.sha1(
        wanted.encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:8]
    # RESOLVED BY EXACT TAIL, NOT REFUSED ON A SUFFIXED SIBLING, and that is the
    # one place this join deliberately parts company with `_find_row_by_design_id`.
    # That helper RAISES when a table shows both `d` and `d_2`, reading it as the
    # signature of a sanitize collision whose positional `_2` cannot be inverted —
    # and it can afford to, because its callers hold `design_id_by_job_name`, the
    # authoritative scope, and it tells them to pass it.
    #
    # THIS function takes no such scope, so the same raise would be a dead end.
    # It would also be WRONG far more often than right: `_token_is_collision_ambiguous`
    # cannot tell a collision discriminator from an id that simply ends in a
    # number, and the real pool is full of the latter —
    # `tests/test_campaign_screen_gate_join.py::_seq_rows` carries
    # `design_spec_047` and `design_spec_047_3` as two DISTINCT designs with two
    # distinct real binder sequences, and the measured aggregate had 12 such ids
    # out of 60. Refusing there would take the monomer gate out for a fifth of the
    # pool while the correct row sat in the table.
    #
    # The tail IS invertible: `scoring_member_job_name` builds
    # `{batch}-{sanitize_design_id(id)}` and the sanitizer maps `-` to `_`, so the
    # design token never contains `-` and the tail after the LAST `-` is exactly
    # that token. `design_spec_074` and `design_spec_074_3` are then two different
    # tails rather than one substring of the other — which is the entire
    # difference between this pass and the token pass below, and the whole fix.
    # Residual: under a TRUE sanitize collision two ids share one token and
    # nothing in the string separates them. Pass `member_job_names`, or prefer
    # exact ids.
    member = [
        row
        for row in materialized
        if any(
            _member_token_matches_design(
                (_member_design_token(cell) or "").lower(), sanitized, digest
            )
            for cell in _id_cells(row)
        )
    ]
    if member:
        return member

    if not allow_token_pass:
        return []

    # PASS THREE: boundary-anchored token, guarded exactly as the shared join
    # guards it — a cell whose member tail names a different design is SKIPPED
    # rather than matched loosely.
    token = re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(wanted)}(?![A-Za-z0-9])", re.IGNORECASE
    )

    def _token_hit(cell: str) -> bool:
        other = _member_design_token(cell)
        if other is not None and other.lower() not in (lowered_wanted, sanitized):
            return False
        return bool(token.search(cell))

    return [
        row for row in materialized if any(_token_hit(cell) for cell in _id_cells(row))
    ]


def _id_cells(row: Mapping[str, Any]) -> list[str]:
    """The row's id-like cell values, as ``_find_row_by_design_id`` reads them.

    Mirrors that helper's own extraction, including its ``continue`` on an
    ambiguous spelling: an id column spelled two ways is not worth abandoning a
    join over while other id columns can still resolve the row. Kept in step by
    ``test_the_join_agrees_with_the_shared_one``.
    """
    cells: list[str] = []
    for column in _DESIGN_ID_COLUMNS:
        try:
            actual = _resolve_metric_column(row.keys(), (column,))
        except ValueError:
            continue
        if actual is None:
            continue
        value = str(row.get(actual) or "").strip()
        if value:
            cells.append(value)
    return cells


def _table_carries_a_design_id(rows: list[dict[str, Any]]) -> bool:
    """True when some row exposes a column the shared id join can read.

    Asks the question by READING THE CELLS the join would read, which is the only
    phrasing that cannot disagree with it. An earlier version resolved column
    NAMES and counted an ambiguous spelling (``ValueError``) as present — but the
    join answers that case with ``continue``, skipping the column, so a table
    whose ONLY id-like column is ambiguously spelled (``name`` beside
    ``name - esmfold2``, exactly what joining a batch aggregate against a per-job
    metrics.csv produces) was called joinable and then joined nothing. Every
    design came back NOT_RUN with the measurements sitting right there — and
    ``monomer_foldability_verdicts`` then reports an empty ``rejected`` list, so
    a caller checking "the gate's rejects are absent downstream" passes
    VACUOUSLY. That is this module's own headline failure, reached through the
    joinability probe.
    """
    return any(_id_cells(row) for row in rows)


def monomer_plddt_from_fold_rows(
    rows: Iterable[Any],
    design_id: str | None = None,
    *,
    job_type: str | None = None,
) -> float | None:
    """S1b monomer-foldability pLDDT for one design, from a BINDER-ALONE fold.

    The question the gate asks is "does this binder fold on its own, absent the
    target" — a design that only looks folded when co-folded with its target is
    not a real binder. Build the fold with
    ``buildScoringBatch(construct="monomer_binder")`` and hand this function that
    job's ``metrics.csv`` rows, or the batch aggregate's with ``job_type`` naming
    the arm.

    Returns the mean-per-residue pLDDT on the 0-1 scale ESMFold2 emits, taken as
    the ``MONOMER_PLDDT_SEED_AGGREGATION`` over the design's (seed, sample) rows.
    Anthropic fixes the mean over residues — that IS the ``plddt`` cell — and says
    nothing about combining samples; the max is ours, chosen because it is the
    rule Anthropic states for the other per-seed metric ("then max over seeds"),
    so S1b and the ranking arms answer "which sample" the same way. It is not a
    parameter: the sheet writer must RECOMPUTE this gate and match the carried
    value to 1e-4, and a knob is how a computation and its recomputation disagree
    while both look right.

    REFUSES A CO-FOLDED TABLE, and that refusal is most of the value here.
    ``plddt`` is emitted by complex runs too, and there it is the confidence of
    binder AND target together — dominated by a target that folds beautifully on
    its own. Read as ``monomer_plddt`` it does not fail the threshold, it CLEARS
    it for every design, so the gate reports itself as run while passing the
    entire pool on precisely the artifact it exists to detect. An ipSAE_*/pDockQ_*
    column or a positive ``iptm`` therefore raises rather than returning a number.

    REFUSES AN OFF-SCALE VALUE for the same reason one layer down: a 0-100 table
    clears a 0.7 floor on every row. ESMFold2 emits 0-1 and the charter names the
    scale it froze, so anything outside [0, 1] raises instead of being rescaled on
    a guess.

    Returns ``None`` — never 0.0, never NaN — when the design has no row, or no
    row carries a parseable ``plddt``. ``None`` is NOT_RUN for that design: a
    real, expected state, which the caller must stamp and disclose rather than
    let read as a pass.
    """
    # OVER THE WHOLE TABLE, before any id filtering. Scoped to the selected rows
    # instead, whether a co-folded table was refused depended on WHICH DESIGNS
    # the caller asked about — and a screen naturally asks only about survivors,
    # so the contaminated rows are exactly the ones it would not look at. The
    # docstring promises a property of the table; this is what makes it one.
    materialized = [dict(row) for row in rows if isinstance(row, Mapping)]
    for row in materialized:
        evidence = cofold_evidence(row)
        if evidence:
            raise ScreenGateInputError(
                "monomer_plddt was asked for from a CO-FOLDED table: "
                f"{evidence}. That row's `plddt` is the confidence of binder AND "
                "target, which clears the floor for every design. Fold the binder "
                "alone — buildScoringBatch(construct='monomer_binder') — and read "
                "that job's metrics instead."
            )
    best: float | None = None
    for row in rows_for_design_id(materialized, design_id):
        value = _row_float(row, MONOMER_PLDDT_COLUMNS, job_type=job_type)
        if value is None:
            continue
        if not 0.0 <= value <= 1.0:
            raise ScreenGateInputError(
                f"monomer_plddt {value} is outside the 0-1 scale ESMFold2 emits. "
                "A 0-100 table clears a 0-1 floor on every row, so this is refused "
                "rather than rescaled — confirm the scale the plan froze."
            )
        best = value if best is None else max(best, value)
    return best


def esmc_ll_from_scan_rows(
    rows: Iterable[Any],
    design_id: str | None = None,
    *,
    job_type: str | None = None,
    tool: str,
) -> float | None:
    """ESM-C mean pseudo-LOG-LIKELIHOOD (nats) for one design. Never a gate.

    Anthropic asks only to "compute and record an ESMC log-likelihood (or
    pseudo-perplexity) on every design that receives a rank" — it states no
    threshold, and neither do we (``qa_rubrics.ESMC_LL_HAS_FROZEN_THRESHOLD``).
    An absolute pseudo-NLL cutoff over arbitrary designed miniproteins is length-
    and family-dependent, we hold no calibration for one, and a number invented
    here would be a magic number wearing a frozen value's clothes.

    THE SIGN IS FLIPPED HERE, once. ``esmc-6b`` ``task="scan"`` emits a mean
    pseudo-NEGATIVE-log-likelihood (positive, 4.2711710929870605 on the archived
    example); the column is named ``esmc_ll`` and holds a log-likelihood, so this
    returns ``-score`` and the result is <= 0.

    ``tool`` IS REQUIRED — no default. ``esmc-scan`` writes the same
    ``global_score.csv`` with the same ``score`` header and puts a PSEUDO-
    PERPLEXITY in it, which is exp() of this quantity: it overlaps numerically
    and is off by a logarithm rather than a scale factor, so no value tells the
    two apart. It had a default of the correct tool, which meant the check fired
    only for a caller who already knew the answer and every other call silently
    negated whatever it was handed. Keyword-only and required makes each call
    site state which producer it read, and a wrong one raise.

    That is still a DECLARATION, not proof — nothing here can verify what job
    actually ran. ``qa_rubrics.ESMC_LL_MIN_ADMISSIBLE`` is the backstop that
    reads the number instead, and it is partial by construction.

    Exactly one score row per design, or it raises: two rows means the design was
    scanned twice, Anthropic gives no rule for combining them, and this module
    does not guess. A ``score`` below zero also raises — the producer's output is
    >= 0 by construction, so a negative cell is already a log-likelihood (or is
    not this producer's), and flipping it again would rank the least protein-like
    sequence in the pool highest.

    Returns ``None`` — never 0.0 — when the design has no row or the cell is
    unparseable. That is NOT_RUN for the design, to be stamped, not skipped.
    """
    if str(tool).strip() != ESMC_LL_TOOL:
        raise ScreenGateInputError(
            f"esmc_ll must come from {ESMC_LL_TOOL!r}, not {tool!r}. `esmc-scan` "
            "writes the same global_score.csv `score` column with a pseudo-"
            "PERPLEXITY in it, which is exp() of this quantity and overlaps it "
            "numerically — no value can tell them apart after the fact."
        )
    scored = [
        (row, _row_float(row, ESMC_SCAN_SCORE_COLUMNS, job_type=job_type))
        for row in rows_for_design_id(rows, design_id)
    ]
    scored = [(row, value) for row, value in scored if value is not None]
    if not scored:
        return None
    if len(scored) > 1:
        raise ScreenGateInputError(
            f"esmc_ll: {len(scored)} scan rows match design_id={design_id!r}. One "
            "sequence gets one pseudo-NLL and there is no defined way to combine "
            "two, so name the design behind each row rather than pooling them."
        )
    score = scored[0][1]
    if score < 0.0:
        raise ScreenGateInputError(
            f"esmc_ll: the scan column holds {score}, but {ESMC_LL_TOOL} emits a "
            "mean pseudo-NEGATIVE-log-likelihood, which is >= 0. This table is "
            "already a log-likelihood (or is not this producer's) — flipping it "
            "again would rank the least protein-like sequence highest."
        )
    return 0.0 if score == 0.0 else -score


# Per-design verdict tokens. NOT_RUN is a first-class outcome beside PASS and
# REJECT, never folded into either: "we could not check this design" and "this
# design folds on its own" are the two states the whole discipline exists to keep
# apart, and a two-valued verdict has to collapse one into the other.
MONOMER_VERDICT_PASS = "PASS"
MONOMER_VERDICT_REJECT = "REJECT"
MONOMER_VERDICT_NOT_RUN = "NOT_RUN"


def monomer_foldability_verdicts(
    rows: Iterable[Any],
    design_ids: Iterable[Any],
    *,
    threshold: float = MONOMER_PLDDT_FLOOR_THRESHOLD,
    job_type: str | None = None,
) -> dict[str, Any]:
    """Run S1b over a monomer-fold batch: ``{design_id: verdict}`` plus the buckets.

    This is the gate itself, and it is the piece that was missing: the fold job
    already runs, so without this the campaign spends the GPU and filters nothing.
    Shaped after ``scoring_batch.ipsae_ranking_coverage`` — driven by the ids the
    caller asked about, so a design with NO row is reported rather than silently
    dropped out of the denominator.

    ``threshold`` defaults to the FLOOR Anthropic states (0.70 on the 0-1 scale);
    pass the charter's per-target value when the campaign froze a stricter one.
    A threshold below the floor raises: no admissible per-target value is looser
    than the default, so a lower one is a mis-scaled or mis-read charter, and
    applying it would pass designs no gate admits.

    Returns ``{"verdicts", "passed", "rejected", "not_run", "threshold",
    "measurements"}``. ``rejected`` is the list Anthropic's rule needs — "a gate
    counts as run only when its rejects are traceably absent downstream" — so the
    caller can assert those ids are gone from the pool it emits instead of
    asserting the gate ran.
    """
    try:
        floor = float(threshold)
    except (TypeError, ValueError) as exc:
        raise ScreenGateInputError(
            f"monomer pLDDT threshold {threshold!r} is not a number."
        ) from exc
    if isinstance(threshold, bool) or not math.isfinite(floor):
        raise ScreenGateInputError(
            f"monomer pLDDT threshold {threshold!r} is not a usable number. NaN "
            "is the dangerous one: every `value >= nan` is False, so the gate "
            "would REJECT the entire pool while reporting a threshold."
        )
    if not MONOMER_PLDDT_FLOOR_THRESHOLD <= floor <= 1.0:
        # BOUNDED AT BOTH ENDS, and the upper bound is the one that was missing.
        # The charter records this threshold with an explicit `scale` field
        # precisely because the same number is quoted as 70 and as 0.70 — and a
        # 70 arriving here is not caught by a floor check, it silently REJECTS
        # every design in the pool. Refusing an off-scale MEASUREMENT while
        # applying an off-scale THRESHOLD was the asymmetry.
        raise ScreenGateInputError(
            f"monomer pLDDT threshold {floor} is outside "
            f"[{MONOMER_PLDDT_FLOOR_THRESHOLD}, 1.0]. Below the floor it would "
            "admit designs no admissible gate passes — the validation gate may "
            "only freeze a STRICTER value. Above 1.0 it is the 0-100 spelling of "
            "the same number (the plan carries `scale` beside `value` for "
            "exactly this reason), and it rejects the whole pool."
        )
    materialized = [dict(row) for row in rows if isinstance(row, Mapping)]
    verdicts: dict[str, str] = {}
    measurements: dict[str, float] = {}
    for raw_id in design_ids:
        # `str(raw_id or "")` mapped the integer 0 to "" and dropped it from the
        # answer entirely — not even NOT_RUN — and `_index`, which IS in the
        # shared id-column list, is an integer index.
        design_id = "" if raw_id is None else str(raw_id).strip()
        if not design_id or design_id in verdicts:
            continue
        value = monomer_plddt_from_fold_rows(materialized, design_id, job_type=job_type)
        if value is None:
            verdicts[design_id] = MONOMER_VERDICT_NOT_RUN
            continue
        measurements[design_id] = value
        verdicts[design_id] = (
            MONOMER_VERDICT_PASS if value >= floor else MONOMER_VERDICT_REJECT
        )
    return {
        "verdicts": verdicts,
        "passed": [d for d, v in verdicts.items() if v == MONOMER_VERDICT_PASS],
        "rejected": [d for d, v in verdicts.items() if v == MONOMER_VERDICT_REJECT],
        "not_run": [d for d, v in verdicts.items() if v == MONOMER_VERDICT_NOT_RUN],
        "threshold": floor,
        "seed_aggregation": MONOMER_PLDDT_SEED_AGGREGATION,
        "measurements": measurements,
    }


# ── the pool half: an S1b reject that survived ─────────────────────────────
#
# Anthropic states the rule the sheet cannot enforce: "Record every rejected
# design_id and verify its absence from every downstream scoring pool; a gate
# counts as run only when its rejects are traceably absent downstream."
# A verdict map alone cannot answer that — it says what the gate DECIDED, not
# what the pool KEPT. These two are the difference.
POOL_MONOMER_BELOW_FLOOR_FIELD = (
    f"monomer_plddt below the {MONOMER_PLDDT_FLOOR_THRESHOLD} floor on a "
    "SURVIVING row (an S1b reject the pool kept)"
)
POOL_MONOMER_SCALE_FIELD = (
    "monomer_plddt outside the 0-1 scale on a surviving row (a 0-100 value "
    "survives every floor, so the gate reports itself as run and rejects nobody)"
)


def monomer_gate_pool_violations(
    rows: Any,
    *,
    threshold: float = MONOMER_PLDDT_FLOOR_THRESHOLD,
) -> dict[str, list[str]]:
    """Surviving-pool rows an S1b verdict should have removed. Offender ids by key.

    Empty — so nothing halts — whenever the pool carries no ``monomer_plddt`` at
    all, which is today's state and is a legitimate NOT_RUN. What it catches is
    the pool that DID run the gate and kept the designs it rejected, which is
    indistinguishable from never having run it except by looking.

    Uses the FLOOR rather than the charter's per-target value, for the reason
    ``MONOMER_PLDDT_FLOOR_THRESHOLD`` gives: the pool artifact does not carry the
    frozen threshold, and the floor is the one bound that holds under every
    admissible choice. A campaign that froze something stricter will have removed
    strictly more, so this never contradicts it.
    """
    floor = float(threshold)
    offenders: dict[str, list[str]] = {}
    for index, row in enumerate(rows or []):
        if not isinstance(row, Mapping):
            continue
        raw = row.get("monomer_plddt")
        if raw is None or str(raw).strip() == "":
            continue
        value = _as_float(raw)
        if value is None:
            continue
        design_id = str(row.get("design_id") or f"row_{index + 1}")
        if not 0.0 <= value <= 1.0:
            offenders.setdefault(POOL_MONOMER_SCALE_FIELD, []).append(design_id)
        elif value < floor:
            offenders.setdefault(POOL_MONOMER_BELOW_FLOOR_FIELD, []).append(design_id)
    return offenders


# ── the CLAIM half: an S1b pass that says it ran and cut nobody ────────────
#
# `monomer_gate_pool_violations` above reads the numbers the pool CARRIES, and is
# empty when it carries none. That fail-open is right for every stage that never
# ran S1b, and it is exactly wrong for the one stage that says it did.
#
# camp_3004310e9faf: the binder-alone foldability gate applied the 0.7 floor to
# pLDDT values on the 0-100 scale (the real values were 70-90), in subagent-
# authored analysis code that never called `monomer_plddt_from_fold_rows`. All 64
# designs cleared, no cut was made, and the pass reported SUCCESS — so nothing
# downstream knew. The refusal written for precisely this ("A 0-100 table clears
# a 0-1 floor on every row, so this is refused rather than rescaled") was never
# reached, because the comparison happened somewhere that function does not run
# and the pool it emitted carried no `monomer_plddt` for the pool-side mirror of
# that refusal to read.
#
# The rule is therefore about the CLAIM rather than the values: a pass that says
# it IS this gate and rejected nobody has to put the measurement on the rows,
# where the scale refusal can reach it. An unverifiable clean sweep is a NOT_RUN
# wearing a pass's clothes, and NOT_RUN is a disclosure, never a verdict.
POOL_MONOMER_UNVERIFIED_SURVIVOR_FIELD = (
    "survived an S1b monomer-foldability pass that rejected nobody while "
    "carrying no monomer_plddt and no disclosed "
    f"{MONOMER_CHECK_NOT_RUN_CODE} (nothing can tell a real clean sweep from a "
    "floor applied on the wrong scale, which clears every design)"
)


def is_monomer_gate_stage(stage: Any) -> bool:
    """True when this wave IS the S1b binder-alone foldability gate.

    Matched loosely on purpose: the stage label is a string a model writes, and
    ``s1b``, ``S1b_monomer`` and ``stage s1b_monomer`` all name the same wave.
    Nothing else in the documented stage vocabulary (``s1_gates``, ``s2_screen``,
    ``s3_intermediate``) contains ``s1b`` or starts with it, so the looseness
    costs no other stage its fail-open.
    """
    text = str(stage or "").strip().casefold()
    if not text:
        return False
    return MONOMER_GATE_STAGE_TOKEN.casefold() in text or text.startswith("s1b")


def monomer_gate_unverified_survivors(
    rows: Any,
    *,
    stage: Any = None,
    rejected: Any = (),
    not_run_design_ids: Iterable[Any] = (),
) -> dict[str, list[str]]:
    """Surviving rows an S1b clean sweep left unmeasured. Offender ids by key.

    Empty — so nothing halts — in each of these, every one a real state:

      * **the wave is not the S1b gate** (``is_monomer_gate_stage``). Every other
        stage's pool legitimately carries no ``monomer_plddt``, which is the
        NOT_RUN ``monomer_gate_pool_violations`` already fails open on, and
        demanding the measurement there would halt every campaign;
      * **the pass REJECTED somebody.** A floor applied on the wrong scale
        rejects nobody — that is the incident's whole signature — so a pass that
        demonstrably cut is not the failure this looks for. KNOWINGLY PARTIAL,
        and stated rather than papered over: one recorded reject buys the whole
        pool out of this check. The alternative is halting a pass whose gate
        visibly discriminated, and whatever values such a pool does carry are
        still read by ``monomer_gate_pool_violations``;
      * **the row carries a parseable ``monomer_plddt``.** That value is
        checkable, and this function does not re-judge it: the violations check
        owns the verdict, INCLUDING the 0-100 refusal, and a second opinion on
        one cell is how two guards come to disagree. A cell that does not parse
        (NaN, ``"high"``) is not a measurement and counts as absent — the same
        reading the violations check gives it, and the reason a pool of NaNs
        cannot buy itself a clean sweep;
      * **the row's design_id is disclosed NOT_RUN by code.** A design with no
        monomer fold is a real, expected state the rubric already tells the model
        to disclose; refusing it would be a demand for a fabricated number.

    Shape matches ``monomer_gate_pool_violations`` exactly (field -> offending
    ids), so it feeds ``qa._describe_offenders`` unchanged.
    """
    if not is_monomer_gate_stage(stage):
        return {}
    if any(entry for entry in rejected or []):
        return {}
    disclosed = {
        str(raw_id).strip().casefold()
        for raw_id in not_run_design_ids or ()
        if str(raw_id).strip()
    }
    unverified: list[str] = []
    for index, row in enumerate(rows or []):
        if not isinstance(row, Mapping):
            continue
        if _as_float(row.get("monomer_plddt")) is not None:
            continue
        design_id = str(row.get("design_id") or "").strip()
        if design_id and design_id.casefold() in disclosed:
            continue
        unverified.append(design_id or f"row_{index + 1}")
    if not unverified:
        return {}
    return {POOL_MONOMER_UNVERIFIED_SURVIVOR_FIELD: unverified}


# ── The binder sequence, read back off the job that folded it ──────────────
#
# WHY THIS EXISTS. `sequence` was the one load-bearing pool cell nobody joined.
# `monomer_plddt` is computed here, provenance is computed in `screen_gate_join`,
# the survivor SET is derived in `pool_derivation` — and the molecule itself was
# still carried across stages by a model re-typing it into its report.
#
# MEASURED, camp_efd83a415575, the S2->S3 triage pass (task_6e5cda98fc2a,
# 2026-08-22T00:05:39Z): the pass's own sandbox program computed the survivors
# correctly and wrote them to `survivors.csv`. Its only per-design `print` was
# `design_id structure_method binder_len z ipSAE_full fast ptx` — no sequence
# column — so the 60 real binder sequences were written to a file and never
# echoed into the model's context. What came back split exactly along that line:
#
#   design_ids          60/60, in identical order
#   stage_statistic     60/60, to 4 decimal places
#   sequence             0/60
#   sequence length      1/60
#
# Every number it could see, preserved. Every sequence it could not see,
# invented. One invented string is byte-identical to the REAL sequence of a
# DIFFERENT design in the same campaign (design_spec_030_3's, emitted under
# design_spec_004's id), so this is context pattern-completion mis-binding, not
# draws from nowhere — which is why it reads as plausible and why no shape check
# would have caught it. The S1 and S2 pools are clean (172/172 identical to what
# was folded); the break is exactly this hand-off.
#
# The invented sequences were then FOLDED: 60/60 appear in the S3 intermediate
# FASTA and 29 in the S4 final FASTA. Two scoring rounds of real GPU measured
# molecules nothing designed, and the campaign reported their scores as the
# designs' own.
#
# THE FIX IS THE PATTERN, NOT A NEW ONE. The value is right there in the fold
# job's own aggregate: `_sequence_raw` holds the folded construct as
# colon-joined chains, and the binder is the chain that is not the target.
BINDER_SEQUENCE_COLUMNS: tuple[str, ...] = ("_sequence_raw", "sequence_raw")

# `sequence` is DELIBERATELY ABSENT from that tuple. On a real archived scoring
# aggregate (camp_efd83a415575-score-screen-esmfold2_full-s01-efd83a, 2026-08-21)
# the `sequence` column does not hold residues at all — it holds a 167-character
# JSON pointer, `{"__tamarind_ref__": "molecule_sequence/v1", "complex_id": …}`.
# Accepting that spelling would join a reference string as a protein and every
# comparison below would report a conflict on every row.
_SEQUENCE_REF_MARKER = "__tamarind_ref__"

CHAIN_SEPARATOR = ":"


def _chains(value: Any) -> list[str]:
    """The folded construct split into chains, or [] when it is not residues."""
    text = "" if value is None else str(value).strip()
    if not text or _SEQUENCE_REF_MARKER in text:
        return []
    parts = [part.strip().upper() for part in text.split(CHAIN_SEPARATOR)]
    if not all(parts):
        return []
    for part in parts:
        if not part.isalpha():
            return []
    return parts


def target_chains_from_fold_rows(rows: Iterable[Any]) -> list[str]:
    """The chains a whole batch shares — the TARGET, derived from the table.

    Every member of one scoring shard is folded against the same target, so the
    target chains are the ones that recur on every row and the binder is what is
    left. Deriving it here rather than taking it as an argument is deliberate:
    the alternative is threading the campaign target through the triage pass, and
    a target passed in is a target that can be passed in WRONG — which is the
    same class of error this whole module exists to remove.

    Needs at least two DISTINCT constructs to say anything. One row, or 172 rows
    that are all the same construct, cannot distinguish "the shared chain is the
    target" from "these designs happen to be identical", so this answers [] and
    the caller refuses rather than guessing.
    """
    constructs = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        chains = _chains(_row_sequence_raw(row))
        if not chains:
            continue
        key = CHAIN_SEPARATOR.join(chains)
        if key in seen:
            continue
        seen.add(key)
        constructs.append(chains)
    if len(constructs) < 2:
        return []
    shared = [
        chain
        for chain in constructs[0]
        if all(chain in other for other in constructs[1:])
    ]
    return shared


def _row_sequence_raw(row: Mapping[str, Any]) -> Any:
    """The folded-construct cell, through the shared column resolver.

    `_resolve_metric_column` takes the HEADER NAMES and a tuple of alternative
    spellings and returns the header, so it handles the batch-aggregate
    `" - esmfold2"` suffix and refuses an ambiguous match — the same resolution
    every other metric on this table goes through. Indexing `row` by the
    candidate directly would work on today's real header and quietly stop
    working the day the aggregator labels this column by arm.
    """
    header = _resolve_metric_column(row.keys(), BINDER_SEQUENCE_COLUMNS)
    if not header:
        return None
    value = row.get(header)
    return None if value in (None, "") else value


def nn_ipsae_min_from_fold_rows(
    rows: Iterable[Any],
    target_sequences: list[str],
    *,
    job_type: str | None = None,
    required_seeds: int | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """L117's N:N ipSAE_min for one design, from its n_to_n shard's own rows.

    THIS IS COMPUTED, NOT TAKEN FROM THE MODEL. The column used to be whatever
    a report wrote on the row, guarded by an ever-growing chain of checks that
    could only ever ask "did a matching run exist" — never "is this the number
    that run produced". Reading the shard's aggregate answers the second
    question and makes the first irrelevant, which is the same move
    `stamp_lcp_scores` makes: recompute rather than adjudicate.

    ``target_sequences`` comes from `target_chains_from_fold_rows` over the
    WHOLE BATCH, and must: one design's rows are its seeds, every one folding
    the identical construct, so they cannot distinguish "this chain is the
    target" from "these rows are the same design". The batch can, because its
    members differ in binder and share the target. Deriving it from the table
    rather than taking a campaign target as an argument is that module's own
    documented rule — a target passed in is a target that can be passed in
    wrong.

    Chain LETTERS come from position in the colon-joined construct, which is
    the order the folder assigns them.

    THE AGGREGATION, and the one choice this makes:

      * per binder copy — ``max over target protomers X of min(ipSAE_XC,
        ipSAE_CX)``, exactly `ipsae_min_from_pair_columns`, so a copy is scored
        by the same rule as the 1:N column;
      * across the N copies — **MIN**, because N:N asks whether N binders can
        occupy N sites AT ONCE and the weakest copy is what decides that. It is
        also what this metric family does everywhere else (min over alignment
        directions, min over arms for `pose_dockq`);
      * across seeds — MAX, which is Anthropic's rule verbatim.

    …AND THE DEPTH OF THAT MAX IS MEASURED, NEVER COUNTED OFF THE ROWS.
    ``seeds_scored`` used to be ``len(per_seed)``, which is one entry per ROW —
    so ``5 seeds x 1 sample`` and ``1 seed x 5 samples`` both reported five
    seeds, and the second is not this metric at all: ``ipSAE_min`` is the MAX
    OVER SEEDS, so at one seed the max ranges over a single observation and the
    robustness the metric is named for is gone. Rows and seeds are different
    axes; ``rows_scored`` is now the row count and ``seeds_scored`` the DISTINCT
    seed count, read per row by `scoring_batch.realized_seed_depth` (which owns
    the spelling rules — a batch aggregate's bare ``seed`` column is the job's
    submitted SETTING and is constant on every row, and protenix carries no seed
    column at all). The same conflation — a row count standing in for a seed
    count — is what let camp_seed4a91c3e7's audit read its own five-seed FINAL
    panel as one seed with five diffusion samples; there it was a dataframe
    reading the constant bare column, here it was a `len()`, and neither could
    be contradicted because neither side measured the depth.

    ``required_seeds`` is how many DISTINCT seeds the tier that produced these
    rows declares (``scoring_batch.declared_seed_count``). When the realized
    depth is short of it, ``assignment`` carries ``seed_shortfall`` and the
    caller must surface it: the value is still returned — it is a real
    measurement of a shallower instrument, and dropping it would replace a
    disclosed reduction with a silent blank — but it may never travel
    unlabelled. ``None`` leaves the comparison off for a caller that genuinely
    cannot say which tier the rows came from; that is the absence of evidence,
    not evidence of full depth, and ``seeds_scored`` is reported either way.

    THE DEVIATION, disclosed rather than hidden: Anthropic (L121) defines
    ipSAE_min by a UNION MASK — one call with every binder residue on one side
    and every target residue on the other. That value is provably not
    reconstructible from the per-pair scalars our arms emit, because merging
    protomers changes ``n0res`` and therefore ``d0`` and therefore every term.
    The 1:N column already ships this same approximation under
    ``IPSAE_MASK_STAMP``; this is the N:N member of it and carries the same
    stamp. Computing the exact number needs an ipSAE run with a custom mask over
    the prediction's PAE, which is real work and is not what this does.

    THE ONE ASSUMPTION, and it is not yet verified by measurement: chain
    LETTERS follow POSITION in the colon-joined construct. `ipsae.py` takes its
    ``Chn1``/``Chn2`` from the mmCIF's own chain ids, not from the input
    string, so this holds only if the folder labels chains in input order.
    `refold_target_chain_letter` encodes exactly that convention and a real
    archived 2-chain aggregate agrees with it, but NO n_to_n shard has ever
    run, so the 6-chain case is inference. If it is wrong the target and binder
    roles invert, and the two aggregations are not the same number — this does
    NOT fail closed. `chain_assignment` is returned for that reason: the first
    real n_to_n run can be checked at a glance instead of trusted.

    ``None`` — never 0.0 — when the rows cannot answer: too few distinct
    constructs to tell target from binder, no binder chain, or any copy missing
    a direction. An incomplete N:N score must never look like a weak one.
    """
    from .qa_analysis_helpers import ipsae_min_from_pair_columns
    from campaign.cda.tools.scoring_batch import (
        realized_seed_depth,
        seed_depth_shortfall,
    )

    ordered = [row for row in (rows or []) if isinstance(row, Mapping)]
    if not target_sequences:
        return None, {}
    remaining_targets = list(target_sequences)

    per_seed: list[tuple[float, int]] = []
    # The rows the max ACTUALLY ranged over — not every row handed in. A row the
    # loop skipped (no chains, no target/binder split) contributed nothing to
    # the argmax, so counting its seed would overstate the depth of the very
    # number this measures.
    scored_rows: list[dict[str, Any]] = []
    assignment: dict[str, Any] = {}
    for index, row in enumerate(ordered):
        chains = _chains(_row_sequence_raw(row))
        if not chains:
            continue
        # Position IS the chain letter: the folder labels a colon-joined
        # construct A, B, C… in order.
        pool = list(remaining_targets)
        target_letters: list[str] = []
        binder_letters: list[str] = []
        # `position`, NOT `index` — the outer loop's `index` is the ROW, and
        # shadowing it here made every row report the last chain's position as
        # its argmax. Caught by a hand-check of a three-seed fixture that came
        # back with row 3 of 3.
        for position, sequence in enumerate(chains):
            letter = chr(ord("A") + position)
            if sequence in pool:
                # Consumed per occurrence, so a homo-oligomer's N identical
                # protomers claim N chains and the copies that follow are read
                # as binders rather than as more target.
                pool.remove(sequence)
                target_letters.append(letter)
            else:
                binder_letters.append(letter)
        if not binder_letters or not target_letters:
            continue
        if not assignment:
            assignment = {
                "target_chains": list(target_letters),
                "binder_chains": list(binder_letters),
                "construct_chains": len(chains),
            }
        per_copy: list[float] = []
        for letter in binder_letters:
            try:
                value = ipsae_min_from_pair_columns(
                    row, letter, target_letters, job_type=job_type
                )
            except (ValueError, TypeError):
                return None, {}
            if value is None:
                # FAIL CLOSED FOR THE WHOLE DESIGN, and this now does what it
                # says. It used to clear `per_copy` and `break`, which skipped
                # only THAT SEED — a later complete seed was still appended and
                # `max(per_seed)` returned it, so a design missing copy D on
                # seed 1 shipped seed 2's number as authoritative. The comment
                # claimed the opposite of the behaviour. Found by adversarial
                # review.
                #
                # Why the whole design: `ipSAE_min` is a MAX over seeds, so
                # dropping an incomplete seed silently redefines the argmax over
                # a subset. If the missing seed was the real maximum, the value
                # shipped is not this metric at all — and it is not a weaker
                # reading of it either, since a min over the copies that
                # happened to report is systematically higher than the min over
                # all of them.
                return None, assignment
            per_copy.append(float(value))
        if per_copy:
            per_seed.append((min(per_copy), index))
            scored_rows.append(dict(row))
    if not per_seed:
        return None, assignment
    # THE ARGMAX ROW TRAVELS WITH THE VALUE. `ipSAE_min` is a max over seeds and
    # every geometric term is defined AT THAT SEED — Anthropic is explicit for
    # sc_DockQ (L236: computed on "the SAME seed whose ipSAE_min became that
    # arm's score"), and the N:N relabeling is the same kind of quantity.
    # Returning the scalar alone let the sheet pair seed 4's score with seed 0's
    # RMSD, which is two measurements of different models under one row.
    best_value, best_index = max(per_seed, key=lambda entry: entry[0])
    assignment["argmax_row_index"] = best_index
    # TWO NUMBERS, because they answer different questions and used to be one.
    # `rows_scored` says how many observations the max ranged over;
    # `seeds_scored` says how many SEEDS those observations covered. They are
    # equal only at samplesPerSeed == 1, and it is the second one the tier is
    # defined in terms of.
    distinct_seeds, readable_rows, _total = realized_seed_depth(
        scored_rows, job_type=job_type
    )
    assignment["rows_scored"] = len(per_seed)
    assignment["seeds_scored"] = distinct_seeds
    assignment["rows_with_a_readable_seed"] = readable_rows
    # DISCLOSED, not dropped. The caller surfaces this beside the value; a
    # shallow instrument is a real measurement that must not be read as the tier
    # it was labelled with. An UNREADABLE seed lands here too, and deliberately:
    # silence cannot distinguish five distinct seeds from one seed run five
    # times, so it is weaker evidence than a duplicate.
    shortfall = seed_depth_shortfall(
        scored_rows, required_seeds=required_seeds, job_type=job_type
    )
    if shortfall:
        assignment["seed_shortfall"] = shortfall
    return best_value, assignment


def binder_sequence_from_fold_rows(
    rows: Iterable[Any],
    design_id: str | None = None,
    *,
    target_chains: Iterable[str] | None = None,
    member_job_names: Iterable[str] = (),
) -> str | None:
    """One design's BINDER residues, off the job that folded it.

    Returns the single non-target chain of the folded construct, or ``None``
    when this table cannot answer for this design. Raises
    :class:`ScreenGateInputError` when the table cannot answer for ANY design —
    the same discipline `rows_for_design_id` documents, and for the same reason:
    "no row for this design" is a NOT_RUN, "no column to join on" is a bug, and
    reporting the second as the first is how a join failure disguises itself as
    a measurement that was simply unavailable.

    ``target_chains`` defaults to what `target_chains_from_fold_rows` derives
    from this same table. Pass it explicitly only when the table cannot derive
    it (a single-member shard) and the caller knows the target another way.

    REFUSES ANYTHING BUT EXACTLY ONE LEFTOVER CHAIN. A binder is one chain by
    construction — the pose arm's ipSAE_min mask says so, and
    `_build_dockq_members` refuses a packed multi-chain binder for the same
    reason. Two leftover chains means the target was mis-derived, and returning
    either one would put a real-looking sequence on the row. Zero means the
    construct IS the target (a `construct='target_only'` row), which is not a
    design and has no binder to report.
    """
    materialized = [dict(row) for row in rows if isinstance(row, Mapping)]
    if not materialized:
        return None
    if not any(_row_sequence_raw(row) is not None for row in materialized):
        raise ScreenGateInputError(
            "this table carries no folded-construct column, so no design's "
            "sequence can be joined off it (looked for "
            f"{', '.join(BINDER_SEQUENCE_COLUMNS)}; this table has "
            f"{', '.join(sorted(str(c) for c in materialized[0]))})"
        )
    targets = [str(chain).strip().upper() for chain in (target_chains or ())]
    if not targets:
        targets = target_chains_from_fold_rows(materialized)
    if not targets:
        raise ScreenGateInputError(
            "the target chain(s) could not be derived from this table — it "
            "holds fewer than two distinct folded constructs, so the shared "
            "chain cannot be told apart from designs that happen to match. "
            "Pass target_chains explicitly."
        )
    for row in rows_for_design_id(
        materialized,
        design_id,
        member_job_names=member_job_names,
        # EXACT OR NOTHING for a sequence — see `rows_for_design_id`. Measured on
        # camp_efd83a415575-score-screen-esmfold2_full-s01-efd83a: with the token
        # pass on, 12 of the 60 ids the S3 pool carried resolved to ANOTHER
        # design's sequence — every bare id with a suffixed sibling
        # (design_spec_074 alongside _2/_4, design_spec_047 alongside _2/_3/_4).
        allow_token_pass=False,
    ):
        chains = _chains(_row_sequence_raw(row))
        if not chains:
            continue
        leftover = list(chains)
        for target in targets:
            if target in leftover:
                leftover.remove(target)
        if len(leftover) == 1:
            return leftover[0]
    return None


