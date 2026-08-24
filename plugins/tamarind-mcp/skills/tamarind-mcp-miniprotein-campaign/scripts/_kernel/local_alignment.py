"""Smith-Waterman local alignment, BLOSUM62, affine gaps. Pure numpy + stdlib.

WHY THIS FILE EXISTS AT ALL. Protocol L81 makes the novelty gate turn on local
alignment twice over — ">=30% gapped local identity over >=40 aligned residues",
and "Ubiquitin ... often emerges with short terminal extensions, so detect by
local alignment rather than exact match" — and before this file the repository
contained NO sequence aligner of any kind. ``qa_tm_helpers._needleman_wunsch``
is a STRUCTURAL dynamic program over a TM-score matrix, not a sequence one;
there was nothing else. So the gate the protocol names three times could not run,
and "detect by local alignment rather than exact match" had no local alignment to
detect with.

WHY NOT A LIBRARY. ``biotite.sequence.align`` and ``Bio.Align.PairwiseAligner``
both do this well, and neither is installed where this has to run.
``Dockerfile.campaign`` builds with ``uv sync --frozen --no-dev --extra campaign``;
``biopython`` sits in the ``dev`` dependency-group and ``biotite`` is not in
``pyproject.toml`` at all (it is a SANDBOX dependency, reachable only from code
``code_analysis`` inlines into E2B). A ``from Bio import Align`` at module scope
here crashes the campaign agent in production; a soft import degrades the gate to
NOT_RUN on every design, in production, forever — which is precisely the "gate
reports itself as run while filtering nothing" failure the pre-scoring filters
exist to prevent. Adding biopython to the runtime dependency set is a change to
``pyproject.toml``, a file this change does not own. So the aligner is written
here, in ~200 lines, against numpy (present in production as a pandas transitive)
and the stdlib. ``tests/test_campaign_local_alignment.py`` pins it against
Biopython's optimal scores, which is the whole reason biopython being dev-only is
survivable: it is the ORACLE, not the implementation.

EXACT, NOT HEURISTIC. This is the full Gotoh affine-gap Smith-Waterman with
traceback — no seeding, no banding, no X-drop. It returns the optimal local
alignment for the scoring system given. Everything is integer (BLOSUM62 is an
integer matrix and the gap penalties are integers), so the traceback's equality
tests against the stored table are exact rather than epsilon-tolerant, and the
alignment reported is genuinely the one the score came from.

COST, measured rather than asserted: see ``tests/test_campaign_local_alignment.py
::test_the_aligner_is_fast_enough_for_a_pool_scale_scan``. The inner loop is
vectorised BY ROW, not by cell — the affine horizontal recurrence
``E[j] = max(H[j-1] - open - extend, E[j-1] - extend)`` unrolls to a PREFIX
MAXIMUM exactly the way ``qa_tm_helpers._needleman_wunsch`` unrolls the linear
one, so a row is a handful of numpy calls instead of an O(m) Python loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any


class LocalAlignmentError(ValueError):
    """The sequences handed in cannot be aligned as protein."""


# ── the scoring system, frozen and named ───────────────────────────────────
#
# BLOSUM62 with gap-existence 11 / gap-extension 1 is the NCBI BLASTP default and
# what an MMseqs2 protein search uses. Protocol L81 specifies the novelty gate as
# "MMseqs2 vs UniRef90 ... plus the known-binder corpus" and states the
# thresholds but not the scoring system; matching BLASTP's default is the choice
# that makes a locally-computed identity mean the same thing as the one the
# staged MMseqs2 index would report, rather than a number that happens to use the
# same word.
#
# A gap of length L costs OPEN + EXTEND*L, so the FIRST gap column costs 12. That
# is NCBI's convention and Biopython's `PairwiseAligner(scoring="blastp")`
# encodes the same thing as open=-12/extend=-1; the two spellings are pinned
# equal by `test_matches_biopython_blastp_scoring`.
SW_GAP_OPEN_PENALTY = 11
SW_GAP_EXTEND_PENALTY = 1

# BLOSUM62, transcribed from `Bio.Align.substitution_matrices.load("BLOSUM62")`
# and pinned cell-for-cell against it by `test_blosum62_matches_biopython`. Kept
# as a table of rows rather than a dict literal because 576 entries as
# `("A","R"): -1` pairs is unreadable and unauditable, and this form can be
# diffed against the published matrix by eye.
BLOSUM62_ALPHABET = "ARNDCQEGHILKMFPSTWYVBZX*"
_BLOSUM62_ROWS = (
    "  4 -1 -2 -2  0 -1 -1  0 -2 -1 -1 -1 -1 -2 -1  1  0 -3 -2  0 -2 -1  0 -4",
    " -1  5  0 -2 -3  1  0 -2  0 -3 -2  2 -1 -3 -2 -1 -1 -3 -2 -3 -1  0 -1 -4",
    " -2  0  6  1 -3  0  0  0  1 -3 -3  0 -2 -3 -2  1  0 -4 -2 -3  3  0 -1 -4",
    " -2 -2  1  6 -3  0  2 -1 -1 -3 -4 -1 -3 -3 -1  0 -1 -4 -3 -3  4  1 -1 -4",
    "  0 -3 -3 -3  9 -3 -4 -3 -3 -1 -1 -3 -1 -2 -3 -1 -1 -2 -2 -1 -3 -3 -2 -4",
    " -1  1  0  0 -3  5  2 -2  0 -3 -2  1  0 -3 -1  0 -1 -2 -1 -2  0  3 -1 -4",
    " -1  0  0  2 -4  2  5 -2  0 -3 -3  1 -2 -3 -1  0 -1 -3 -2 -2  1  4 -1 -4",
    "  0 -2  0 -1 -3 -2 -2  6 -2 -4 -4 -2 -3 -3 -2  0 -2 -2 -3 -3 -1 -2 -1 -4",
    " -2  0  1 -1 -3  0  0 -2  8 -3 -3 -1 -2 -1 -2 -1 -2 -2  2 -3  0  0 -1 -4",
    " -1 -3 -3 -3 -1 -3 -3 -4 -3  4  2 -3  1  0 -3 -2 -1 -3 -1  3 -3 -3 -1 -4",
    " -1 -2 -3 -4 -1 -2 -3 -4 -3  2  4 -2  2  0 -3 -2 -1 -2 -1  1 -4 -3 -1 -4",
    " -1  2  0 -1 -3  1  1 -2 -1 -3 -2  5 -1 -3 -1  0 -1 -3 -2 -2  0  1 -1 -4",
    " -1 -1 -2 -3 -1  0 -2 -3 -2  1  2 -1  5  0 -2 -1 -1 -1 -1  1 -3 -1 -1 -4",
    " -2 -3 -3 -3 -2 -3 -3 -3 -1  0  0 -3  0  6 -4 -2 -2  1  3 -1 -3 -3 -1 -4",
    " -1 -2 -2 -1 -3 -1 -1 -2 -2 -3 -3 -1 -2 -4  7 -1 -1 -4 -3 -2 -2 -1 -2 -4",
    "  1 -1  1  0 -1  0  0  0 -1 -2 -2  0 -1 -2 -1  4  1 -3 -2 -2  0  0  0 -4",
    "  0 -1  0 -1 -1 -1 -1 -2 -2 -1 -1 -1 -1 -2 -1  1  5 -2 -2  0 -1 -1  0 -4",
    " -3 -3 -4 -4 -2 -2 -3 -2 -2 -3 -2 -3 -1  1 -4 -3 -2 11  2 -3 -4 -3 -2 -4",
    " -2 -2 -2 -3 -2 -1 -2 -3  2 -1 -1 -2 -1  3 -3 -2 -2  2  7 -1 -3 -2 -1 -4",
    "  0 -3 -3 -3 -1 -2 -2 -3 -3  3  1 -2  1 -1 -2 -2  0 -3 -1  4 -3 -2 -1 -4",
    " -2 -1  3  4 -3  0  1 -1  0 -3 -4  0 -3 -3 -2  0 -1 -4 -3 -3  4  1 -1 -4",
    " -1  0  0  1 -3  3  4 -2  0 -3 -3  1 -1 -3 -1  0 -1 -3 -2 -2  1  4 -1 -4",
    "  0 -1 -1 -1 -2 -1 -1 -1 -1 -1 -1 -1 -1 -1 -2  0  0 -2 -1 -1 -1 -1 -1 -4",
    " -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4  1",
)

# Residues outside BLOSUM62's own alphabet map to X (the "any residue" column),
# NOT dropped. U (selenocysteine) and O (pyrrolysine) are real translations that
# appear in UniProt entries, and deleting a residue from a sequence shifts every
# position after it — which silently changes the alignment the gate reads. X
# scores -1 against everything, so an unknown residue neither helps nor rescues a
# hit.
_UNKNOWN_RESIDUE = "X"


@lru_cache(maxsize=1)
def _substitution_table() -> Any:
    """``(matrix, index)``: the 24x24 int score table and letter -> row map."""
    import numpy as np

    matrix = np.array(
        [[int(cell) for cell in row.split()] for row in _BLOSUM62_ROWS],
        dtype=np.int32,
    )
    if matrix.shape != (len(BLOSUM62_ALPHABET), len(BLOSUM62_ALPHABET)):
        raise LocalAlignmentError(
            f"BLOSUM62 table is {matrix.shape}, expected "
            f"({len(BLOSUM62_ALPHABET)}, {len(BLOSUM62_ALPHABET)})"
        )
    index = {letter: position for position, letter in enumerate(BLOSUM62_ALPHABET)}
    return matrix, index


def blosum62(left: str, right: str) -> int:
    """One substitution score, for tests and for reading the table by hand."""
    matrix, index = _substitution_table()
    unknown = index[_UNKNOWN_RESIDUE]
    return int(
        matrix[
            index.get(str(left).upper(), unknown),
            index.get(str(right).upper(), unknown),
        ]
    )


def clean_protein_sequence(sequence: Any) -> str:
    """Uppercase single-letter residues only.

    Deliberately the same rule as ``qa_analysis_helpers._clean_sequence`` —
    letters kept, everything else dropped — so a sequence that the liability gate
    reads one way cannot be read a different length here. Pinned by
    ``test_the_sequence_cleaner_agrees_with_the_liability_gates``.
    """
    return "".join(ch for ch in str(sequence or "").upper() if ch.isalpha())


def _encode(sequence: str) -> Any:
    import numpy as np

    _, index = _substitution_table()
    unknown = index[_UNKNOWN_RESIDUE]
    return np.array([index.get(ch, unknown) for ch in sequence], dtype=np.intp)


@dataclass(frozen=True)
class LocalAlignment:
    """One optimal local alignment and every number a gate reads off it.

    THE TWO DENOMINATORS ARE BOTH HERE, on purpose. Protocol L81's local-identity
    clause is ">=30% gapped local identity over >=40 aligned residues", and
    "gapped ... identity" and "aligned residues" can each be read against the
    alignment's COLUMNS (gap columns included) or against its residue PAIRS (gap
    columns excluded). This carries both and the gate names which it uses:

      ``gapped_identity``  = identities / aligned_columns  (gaps in the
                             denominator — the reading the word "gapped" asks
                             for, and the one that makes identity LOWER, so it
                             rejects less)
      ``pair_identity``    = identities / aligned_pairs    (the ungapped reading)

    ``novelty_gate`` uses COLUMNS for both halves of the clause, so the identity
    and the length are measured over the same span. The two pull in opposite
    directions — columns >= pairs makes the >=40 easier to reach (rejects more)
    and the identity harder to reach (rejects less) — and reading one half in
    columns and the other in pairs is how a clause quietly becomes stricter than
    the protocol on both counts at once.
    """

    score: int
    identities: int
    aligned_columns: int
    aligned_pairs: int
    query_start: int  # 1-based, inclusive
    query_end: int
    subject_start: int
    subject_end: int
    query_aligned: str
    subject_aligned: str
    query_length: int
    subject_length: int

    @property
    def gapped_identity(self) -> float:
        return self.identities / self.aligned_columns if self.aligned_columns else 0.0

    @property
    def pair_identity(self) -> float:
        return self.identities / self.aligned_pairs if self.aligned_pairs else 0.0

    @property
    def query_coverage(self) -> float:
        """Fraction of the QUERY spanned by the alignment.

        Span, not matched positions: ``(end - start + 1) / length``, which is how
        BLAST and MMseqs2 report query coverage. Protocol L81's ">50% coverage"
        is not told which sequence it is over; the query is the DESIGN, and the
        question the gate asks is "how much of my design is this natural
        protein", so the design is the denominator. ``subject_coverage`` is
        reported beside it so a reader can check the other reading rather than
        having to re-run anything.
        """
        span = self.query_end - self.query_start + 1
        return span / self.query_length if self.query_length else 0.0

    @property
    def subject_coverage(self) -> float:
        span = self.subject_end - self.subject_start + 1
        return span / self.subject_length if self.subject_length else 0.0

    def as_record(self) -> dict[str, Any]:
        """The numbers, for a reject record the sheet writer can recompute."""
        return {
            "score": self.score,
            "identities": self.identities,
            "aligned_columns": self.aligned_columns,
            "aligned_pairs": self.aligned_pairs,
            "gapped_identity": round(self.gapped_identity, 6),
            "pair_identity": round(self.pair_identity, 6),
            "query_coverage": round(self.query_coverage, 6),
            "subject_coverage": round(self.subject_coverage, 6),
            "query_start": self.query_start,
            "query_end": self.query_end,
            "subject_start": self.subject_start,
            "subject_end": self.subject_end,
        }


def smith_waterman(
    query: Any,
    subject: Any,
    *,
    gap_open: int = SW_GAP_OPEN_PENALTY,
    gap_extend: int = SW_GAP_EXTEND_PENALTY,
) -> LocalAlignment | None:
    """The optimal BLOSUM62 affine-gap local alignment, or ``None``.

    ``None`` means NO positive-scoring local alignment exists — the two sequences
    share nothing a substitution matrix rewards. It is a real answer ("maximally
    novel against this subject"), not a failure, and callers must not read it as
    NOT_RUN: nothing went wrong.

    RAISES on an empty sequence rather than returning ``None``, because those two
    are the states that must never merge. An empty design sequence produces no
    alignment for the same reason a wholly unrelated one does, and treating it as
    "no hit" would clear the novelty gate for every row whose ``sequence`` column
    was blank — a gate passing the pool on exactly the rows it cannot read.

    The recurrences are Gotoh's, with a gap of length L costing
    ``gap_open + gap_extend*L``::

        E[i][j] = max(H[i][j-1] - open - extend, E[i][j-1] - extend)
        F[i][j] = max(H[i-1][j] - open - extend, F[i-1][j] - extend)
        H[i][j] = max(0, H[i-1][j-1] + s(i,j), E[i][j], F[i][j])

    E is the one with a within-row dependency, and it is why this is vectorised
    rather than looped. Substituting the definition of H into E shows the maximum
    is ALWAYS attained at a cell whose H did not itself come through E — routing
    through E twice pays ``open`` twice for one gap and is strictly worse — so::

        E[i][j] = -open - extend*j + max_{k<j}( Hprovisional[i][k] + extend*k )

    a prefix maximum over the row's provisional H (the max of 0, the diagonal and
    F, all computable from the previous row alone). ``numpy.maximum.accumulate``
    does it in one call. This is the same unrolling
    ``qa_tm_helpers._needleman_wunsch`` uses for the linear-gap case, extended to
    affine.
    """
    import numpy as np

    q = clean_protein_sequence(query)
    s = clean_protein_sequence(subject)
    if not q or not s:
        raise LocalAlignmentError(
            "smith_waterman needs two non-empty protein sequences; got lengths "
            f"{len(q)} and {len(s)}. An unreadable sequence must be disclosed as "
            "NOT_RUN by the gate, never aligned as though it simply had no hit."
        )
    open_penalty = int(gap_open)
    extend_penalty = int(gap_extend)
    if open_penalty < 0 or extend_penalty <= 0:
        raise LocalAlignmentError(
            f"gap penalties are POSITIVE costs (open={gap_open!r}, "
            f"extend={gap_extend!r}); a non-positive extension makes an "
            "arbitrarily long gap free and the alignment unbounded"
        )

    matrix, _ = _substitution_table()
    q_codes = _encode(q)
    s_codes = _encode(s)
    n, m = len(q), len(s)

    # int32 throughout: BLOSUM62 and the gap penalties are integers, so every
    # table entry is exact and the traceback's `==` against the stored value is a
    # real equality rather than a float comparison that has to guess a tolerance.
    neg_inf = np.int32(-(2**30))
    h = np.zeros((n + 1, m + 1), dtype=np.int32)
    e = np.full((n + 1, m + 1), neg_inf, dtype=np.int32)
    f = np.full((n + 1, m + 1), neg_inf, dtype=np.int32)

    first_gap = np.int32(open_penalty + extend_penalty)
    extend = np.int32(extend_penalty)
    ramp = np.arange(m + 1, dtype=np.int32) * extend

    for row in range(1, n + 1):
        scores = matrix[q_codes[row - 1], s_codes]  # 1..m
        f[row, 1:] = np.maximum(h[row - 1, 1:] - first_gap, f[row - 1, 1:] - extend)
        provisional = np.zeros(m + 1, dtype=np.int32)
        provisional[1:] = np.maximum(
            np.maximum(h[row - 1, :-1] + scores, f[row, 1:]), 0
        )
        # E[j] = -open - extend*j + max_{k<j}(provisional[k] + extend*k). The
        # shift by one is what makes it k<j rather than k<=j: a horizontal gap
        # entering column j must come from column j-1 or earlier.
        prefix = np.maximum.accumulate(provisional + ramp)
        e[row, 1:] = prefix[:-1] - first_gap - ramp[1:] + extend
        h[row] = np.maximum(provisional, e[row])
        h[row, 0] = 0

    best = int(h.max())
    if best <= 0:
        return None
    flat = int(h.argmax())
    row, col = divmod(flat, m + 1)

    q_chars: list[str] = []
    s_chars: list[str] = []
    identities = 0
    aligned_pairs = 0
    end_row, end_col = row, col
    state = "H"
    while row > 0 and col > 0:
        if state == "H":
            if h[row, col] == 0:
                break
            diagonal = h[row - 1, col - 1] + matrix[q_codes[row - 1], s_codes[col - 1]]
            if h[row, col] == diagonal:
                q_chars.append(q[row - 1])
                s_chars.append(s[col - 1])
                aligned_pairs += 1
                if q[row - 1] == s[col - 1]:
                    identities += 1
                row -= 1
                col -= 1
                continue
            # E BEFORE F, and it is not arbitrary: when both reach the same score
            # the alignment is genuinely ambiguous, and a fixed order is what
            # makes the reported alignment deterministic. The SCORE is unique
            # either way, and every threshold in the novelty gate reads counts
            # off the path, so a wobbling tie-break would make the gate's own
            # answer depend on numpy's argmax ordering.
            state = "E" if h[row, col] == e[row, col] else "F"
            continue
        if state == "E":
            q_chars.append("-")
            s_chars.append(s[col - 1])
            if e[row, col] == h[row, col - 1] - first_gap:
                state = "H"
            col -= 1
            continue
        q_chars.append(q[row - 1])
        s_chars.append("-")
        if f[row, col] == h[row - 1, col] - first_gap:
            state = "H"
        row -= 1

    start_row, start_col = row, col
    q_aligned = "".join(reversed(q_chars))
    s_aligned = "".join(reversed(s_chars))
    return LocalAlignment(
        score=best,
        identities=identities,
        aligned_columns=len(q_aligned),
        aligned_pairs=aligned_pairs,
        query_start=start_row + 1,
        query_end=end_row,
        subject_start=start_col + 1,
        subject_end=end_col,
        query_aligned=q_aligned,
        subject_aligned=s_aligned,
        query_length=n,
        subject_length=m,
    )
