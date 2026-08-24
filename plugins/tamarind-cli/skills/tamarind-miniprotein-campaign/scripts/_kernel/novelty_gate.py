"""Pre-scoring novelty — protocol L81, and the Ubiquitin rejection of L79.

The protocol clause this implements, verbatim (L81)::

    1. novelty: MMseqs2 vs UniRef90 (once staged; not a dispatch gate per above)
       plus the known-binder corpus plus every chain of the target's own campaign
       reference structure and positive-control complex; REJECT at >60% identity
       over >50% coverage to UniRef90 or the binder corpus, OR at >=30% gapped
       local identity over >=40 aligned residues OR TM-score >=0.5 to any target
       or control chain (so target-mimic protomers are caught here, not
       downstream). Ubiquitin (UniProt P0CG47/P0CG48) often emerges with short
       terminal extensions, so detect by local alignment rather than exact match.

WHAT WAS ALREADY HERE, AND WHAT WAS NOT
---------------------------------------
The TM arm ships: ``qa_tm_helpers.target_mimic_screen`` computes TM-score against
every named target and control chain at ``TM_MIMIC_THRESHOLD = 0.5`` and returns
the same PASS/REJECT/NOT_RUN vocabulary this module uses. It is consumed here
rather than re-implemented, and this module never recomputes a TM-score.

The SEQUENCE arms did not ship, in any form. ``P0CG47``/``P0CG48`` were zero hits
repo-wide, there was no corpus file, loader or data directory, and there was no
sequence aligner anywhere in the repository — so "detect by local alignment
rather than exact match" had nothing to detect with. ``local_alignment`` is that
missing capability; this module is the gate on top of it.

WHAT IS STILL MISSING, AND IT IS DATA, NOT CODE
-----------------------------------------------
Two subject sets cannot be shipped in this repository:

  * The known-binder corpus, protocol's folder "02 ProteinBase". It is part of
    the campaign corpus bundle handed in at runtime (protocol L5-L37 lists the
    ProteinBase collections it is drawn from); it is not in this repository and
    is not obtainable from the machine this was written on. So the LOADER and
    the CHECK are here and are real, pointed at a configurable path, and
    :func:`load_known_binder_corpus` returns ``available=False`` with the reason
    when the path is unset or empty. That is a disclosed NOT_RUN. No corpus is
    invented — a fabricated "known binder" list would make the gate report itself
    as run while screening against sequences nobody chose.

  * UniRef90. Protocol L79 stages it as an MMseqs2 index; MMseqs2 is not a
    Python package and 200M sequences is not a thing this process holds. The gate
    therefore consumes MMseqs2's OUTPUT — :func:`evaluate_precomputed_hits` — and
    reports NOT_RUN when none was supplied. Protocol L79 explicitly permits that
    at dispatch time ("Production scoring is not gated on UniRef90 staging") and
    explicitly forbids it at the FINAL sheet, which is why the required-subject
    set is two named tiers rather than one rule.

Ubiquitin is the one subject that IS shipped, because it is two accessions and a
76-residue sequence, and it is the check protocol L79 singles out by name.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .local_alignment import (
    LocalAlignment,
    LocalAlignmentError,
    clean_protein_sequence,
    smith_waterman,
)
from .prescoring_rejects import (
    PRESCORING_GATE_NOVELTY,
    VERDICT_NOT_RUN,
    VERDICT_PASS,
    VERDICT_REJECT,
    PrescoringReject,
)


class NoveltyGateError(ValueError):
    """The inputs cannot answer the novelty question that was asked."""


# ── the thresholds, all four straight off protocol L81 ─────────────────────
#
# THE STRICTNESS ASYMMETRY IS THE PROTOCOL'S, NOT A TYPO. L81 writes ">60%
# identity over >50% coverage" and ">=30% ... over >=40 aligned residues": the
# first arm is STRICT and the second is INCLUSIVE. A design at exactly 60%/50%
# PASSES; a design at exactly 30% over exactly 40 columns REJECTS. Spelling both
# as `>=` (the natural thing to type) makes the gate stricter than the protocol
# on the first arm, and `>` on the second makes it looser on the second — either
# way the gate stops being the one that was frozen and disclosed.
NOVELTY_GLOBAL_IDENTITY_REJECT_ABOVE = 0.60  # L81, strict >
NOVELTY_GLOBAL_COVERAGE_REJECT_ABOVE = 0.50  # L81, strict >
NOVELTY_LOCAL_IDENTITY_REJECT_AT = 0.30  # L81, inclusive >=
NOVELTY_LOCAL_ALIGNED_COLUMNS_REJECT_AT = 40  # L81, inclusive >=

# The TM arm's value, restated here ONLY so the frozen-threshold disclosure is
# one dict. The computation belongs to `qa_tm_helpers.target_mimic_screen` and
# this module never performs it; `test_the_tm_threshold_is_the_one_that_ships`
# pins this equal to `qa_tm_helpers.TM_MIMIC_THRESHOLD` so the disclosure cannot
# drift from the code that enforces it.
NOVELTY_TM_SCORE_REJECT_AT = 0.50  # L81, inclusive >=

# ── subject sets ───────────────────────────────────────────────────────────
SUBJECT_UNIREF90 = "uniref90"
SUBJECT_KNOWN_BINDER_CORPUS = "known_binder_corpus"
SUBJECT_TARGET_CHAIN = "target_chain"
SUBJECT_CONTROL_CHAIN = "control_chain"
SUBJECT_UBIQUITIN = "ubiquitin"

SUBJECT_KINDS: tuple[str, ...] = (
    SUBJECT_UNIREF90,
    SUBJECT_KNOWN_BINDER_CORPUS,
    SUBJECT_TARGET_CHAIN,
    SUBJECT_CONTROL_CHAIN,
    SUBJECT_UBIQUITIN,
)

# WHICH ARM APPLIES TO WHICH SUBJECT SET — a reading of L81, stated rather than
# buried, because the sentence does not scope its second arm and the two possible
# scopings differ by the whole pool.
#
# The 60%/50% arm is scoped by the protocol itself: "to UniRef90 or the binder
# corpus". The >=30%-over->=40-columns arm is not scoped, and applying it to
# UniRef90 would reject essentially every design ever generated: 30% identity
# over 40 residues is the classical twilight-zone floor, and against ~200 million
# sequences a 60-residue de novo miniprotein finds such a hit by chance. A gate
# that rejects the entire pool is not a stricter gate, it is a broken one.
#
# MEASURED, not asserted: against the ONE 152-residue ubiquitin subject, 500
# random sequences of designed-miniprotein composition and length 50-120 trip the
# local arm 0 times. Every one of the 500 HAS a positive-scoring alignment (mean
# ~11 aligned columns, best identity 1.0) — it is the 40-COLUMN half of the arm
# that does the work, and loosening only that half to 10 columns trips ~47% of
# the same sequences. Reproduced, both halves, by
# `test_the_local_arm_chance_rate_against_one_subject_is_small`. Well under 1%
# per subject is a tolerable cost against one positive control and a handful of
# curated binders; against 2x10^8 UniRef90 subjects, a per-subject rate that low
# is still a near-certainty for every design in the pool.
#
# So the low-identity arm runs against the CURATED subject sets only — the known
# binders, the target's own chains and controls, and the ubiquitin positive
# control. That is also where the protocol's own sentence points: the arm sits
# beside "so target-mimic protomers are caught here", which is a handful of
# named chains, and the very next sentence makes ubiquitin the worked example.
GLOBAL_ARM_SUBJECT_KINDS: frozenset[str] = frozenset(
    {SUBJECT_UNIREF90, SUBJECT_KNOWN_BINDER_CORPUS, SUBJECT_UBIQUITIN}
)
LOCAL_ARM_SUBJECT_KINDS: frozenset[str] = frozenset(
    {
        SUBJECT_KNOWN_BINDER_CORPUS,
        SUBJECT_TARGET_CHAIN,
        SUBJECT_CONTROL_CHAIN,
        SUBJECT_UBIQUITIN,
    }
)

# The two tiers protocol L79 draws, as named sets rather than a boolean.
#   "Production scoring is not gated on UniRef90 staging. The full-UniRef90
#    novelty check and the Ubiquitin positive-control rejection are required
#    before any row reaches the FINAL ranked sheet, not before first production
#    dispatch"
# Only UniRef90 gets the dispatch-time exemption; the corpus is staged "in the
# first hour" with no such sentence, so it is required at both tiers.
NOVELTY_REQUIRED_SUBJECTS_DISPATCH: tuple[str, ...] = (
    SUBJECT_UBIQUITIN,
    SUBJECT_KNOWN_BINDER_CORPUS,
)
#
# NO PRODUCTION CALL SITE PASSES THE FINAL TIER as of this commit. The only
# production caller is `qa.py::prescoring_gate_pool_report`, which passes
# DISPATCH — correctly, it runs before dispatch. The final-ranked-sheet writer
# (protocol L90) is the caller this tier is FOR, and it does not exist yet. The
# constant is left as the correct reading of L79 rather than deleted, because
# deleting it would delete the only written statement of what the FINAL bar is;
# it is named here as a known gap so a reader does not mistake "no reader" for
# "not needed".
NOVELTY_REQUIRED_SUBJECTS_FINAL: tuple[str, ...] = (
    SUBJECT_UBIQUITIN,
    SUBJECT_KNOWN_BINDER_CORPUS,
    SUBJECT_UNIREF90,
)

# DISCLOSURE OF ARMS THAT DID NOT RUN — separate from `required`, deliberately.
#
# Every arm below takes its comparison data as an argument and skips when the
# caller supplies none. Before this key existed, a skip was disclosed ONLY when
# the subject happened to sit in `required_subjects`, so on the production
# (DISPATCH) path the target- and control-chain arms skipped in total silence:
# no `missing` entry, no `screened` key, nothing on the artifact. A design that
# was a verbatim slice of the campaign's own target came back NOT_RUN with no
# record that the target-mimic arm had never been pointed at the target.
#
# WHY A SEPARATE KEY RATHER THAN ADDING THE CHAIN SUBJECTS TO `required`:
# `required` has one meaning and it is a strong one — "a subject whose absence
# makes this design NOT_RUN". Putting the chain subjects in the DISPATCH tier
# would downgrade EVERY design in every pool to NOT_RUN until some caller starts
# passing chains, which stalls the campaign rather than screening it; and
# `control_chain` has no sensible required-ness at all, since a campaign may
# legitimately have no controls. Putting them in the FINAL tier instead would
# arm exactly that stall for the future sheet writer, silently, at the worst
# moment. So `required` keeps its meaning, and RECORDING a skip is decoupled
# from ENFORCING one: `arms_not_run` is always populated, for every skippable
# arm, whatever `required_subjects` says. Visibility without a stall.
#
# The reason strings are the SAME strings appended to `missing`, so the two can
# never drift apart — when an arm is both skipped and required, one string is
# written to both places.
ARM_TM_SCORE = "tm_score"
NOVELTY_SKIPPABLE_ARMS: tuple[str, ...] = (
    SUBJECT_UBIQUITIN,
    SUBJECT_KNOWN_BINDER_CORPUS,
    SUBJECT_TARGET_CHAIN,
    SUBJECT_CONTROL_CHAIN,
    SUBJECT_UNIREF90,
    ARM_TM_SCORE,
)

# WHAT THE FINAL TIER ASKS FOR THAT DISPATCH DOES NOT — derived, never re-listed.
#
# The two tiers are already sets, so "which instrument does FINAL need that
# dispatch is exempt from" has exactly one answer and it is a set difference.
# Spelling it as a third literal tuple would let the three drift, and the drift
# would be silent: a fourth subject added to FINAL tomorrow belongs here the
# moment it is added, and a derivation is the only way it arrives for free.
#
# Its consumer is the sheet writer, which has to tell two different facts apart —
# "this design failed novelty" and "nobody could run this arm for any design" —
# and needs to NAME the missing arm to disclose the second one.
NOVELTY_FINAL_ONLY_SUBJECTS: tuple[str, ...] = tuple(
    sorted(
        frozenset(NOVELTY_REQUIRED_SUBJECTS_FINAL)
        - frozenset(NOVELTY_REQUIRED_SUBJECTS_DISPATCH)
    )
)

# ── which tier produced a verdict, as a token that travels ON THE ROW ───────
#
# A bare "PASS" cannot say which of the two tiers above cleared it, and the
# difference between them is the entire UniRef90 arm. That matters exactly once:
# at the FINAL sheet, where L79 stops exempting UniRef90 and a dispatch-tier PASS
# — computed with UniRef90 deliberately not required — would otherwise read as a
# database clearance nobody performed. So the tier is carried beside the verdict
# and the sheet writer demands the FINAL one by name.
NOVELTY_TIER_DISPATCH = "dispatch"
NOVELTY_TIER_FINAL = "final"

_NOVELTY_TIER_BY_SUBJECTS: dict[frozenset[str], str] = {
    frozenset(NOVELTY_REQUIRED_SUBJECTS_DISPATCH): NOVELTY_TIER_DISPATCH,
    frozenset(NOVELTY_REQUIRED_SUBJECTS_FINAL): NOVELTY_TIER_FINAL,
}


def novelty_tier(required_subjects: Iterable[str]) -> str:
    """Name the tier a required-subject set is, or describe it literally.

    A LOOKUP against the two frozen sets, never a count or a membership test.
    ``SUBJECT_UNIREF90 in required`` would be the natural thing to write and it
    is wrong in the direction that matters: any ad-hoc set that happens to
    mention UniRef90 would then report itself as FINAL, which is the one claim
    this token exists to make checkable. An unrecognized set reports its own
    sorted membership instead, so it reads on the row as "not one of the two
    frozen tiers" rather than silently claiming to be either.
    """
    subjects = frozenset(str(subject) for subject in required_subjects)
    named = _NOVELTY_TIER_BY_SUBJECTS.get(subjects)
    if named is not None:
        return named
    return "custom(" + ",".join(sorted(subjects)) + ")"


# ── the two tiers as an ORDER, weakest first ───────────────────────────────
#
# `novelty_tier` names a tier; this says which of two names is the stronger
# instrument. They are separate because the naming is a set lookup that must
# refuse anything ad-hoc, while the comparison has a caller that legitimately
# asks "is a FINAL-tier verdict good enough where I only demanded dispatch" —
# and the answer is yes, in that direction only.
#
# DISPATCH is a strict subset of FINAL by construction (FINAL is dispatch plus
# UniRef90), so the ladder is a real containment order and not a convention.
# Asserted rather than assumed, because a future edit that made the two tiers
# overlap instead of nest would silently turn this into a preference.
NOVELTY_TIER_LADDER: tuple[str, ...] = (NOVELTY_TIER_DISPATCH, NOVELTY_TIER_FINAL)

assert frozenset(NOVELTY_REQUIRED_SUBJECTS_DISPATCH) < frozenset(
    NOVELTY_REQUIRED_SUBJECTS_FINAL
), "the novelty tiers must nest for NOVELTY_TIER_LADDER to be an order"


def novelty_tier_at_least(carried: Any, floor: Any) -> bool:
    """Is ``carried`` the ``floor`` tier or a stronger one?

    UNRECOGNIZED IS FALSE, on BOTH sides, and that is the whole safety property.
    A blank tier, a ``custom(...)`` set and a token the model invented are all
    "not one of the two frozen tiers", and the one thing they must never do is
    satisfy a floor — that is how a row with no recorded tier would rank. A
    floor this function does not recognize also fails every row rather than
    admitting them, so a caller that passes a typo refuses a sheet instead of
    shipping an ungated one.
    """
    carried_token = str(carried or "").strip().lower()
    floor_token = str(floor or "").strip().lower()
    if carried_token not in NOVELTY_TIER_LADDER or floor_token not in NOVELTY_TIER_LADDER:
        return False
    return NOVELTY_TIER_LADDER.index(carried_token) >= NOVELTY_TIER_LADDER.index(
        floor_token
    )

NOVELTY_THRESHOLDS: dict[str, Any] = {
    "global_identity_reject_above": NOVELTY_GLOBAL_IDENTITY_REJECT_ABOVE,
    "global_coverage_reject_above": NOVELTY_GLOBAL_COVERAGE_REJECT_ABOVE,
    "local_identity_reject_at": NOVELTY_LOCAL_IDENTITY_REJECT_AT,
    "local_aligned_columns_reject_at": NOVELTY_LOCAL_ALIGNED_COLUMNS_REJECT_AT,
    "tm_score_reject_at": NOVELTY_TM_SCORE_REJECT_AT,
    "identity_denominator": "alignment columns (gap columns included)",
    "coverage_denominator": "query (design) length",
    "global_arm_subjects": tuple(sorted(GLOBAL_ARM_SUBJECT_KINDS)),
    "local_arm_subjects": tuple(sorted(LOCAL_ARM_SUBJECT_KINDS)),
}


# ── the Ubiquitin positive control ─────────────────────────────────────────
#
# The 76-residue human ubiquitin repeat unit. Both accessions protocol L81 names
# are POLYubiquitin precursors built from tandem copies of exactly this sequence:
# P0CG47 (UBB, polyubiquitin-B) is three copies plus one trailing residue, and
# P0CG48 (UBC, polyubiquitin-C) is nine copies plus one trailing residue. The
# repeat unit is what a structure generator actually reproduces — a co-folder
# trained on the PDB emits the mature 76-mer fold, never a 685-residue precursor
# — and it is the exact sequence every ubiquitin entry in the PDB carries.
#
# The trailing residue of each precursor is deliberately NOT stored. It is one
# residue outside every repeat, it cannot change any alignment by more than a
# single column, and asserting a specific letter for it from memory would be
# putting an unverified sequence into a gate that destroys designs.
UBIQUITIN_MONOMER = (
    "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
)
UBIQUITIN_MONOMER_LENGTH = 76
UBIQUITIN_ACCESSIONS: tuple[str, ...] = ("P0CG47", "P0CG48")

# The subject is searched as a TANDEM DIMER, not a single monomer. A binder may
# be up to 160 residues (protocol L62's permitted band) and 2 x 76 = 152, so a
# design reproducing the tail of one repeat and the head of the next spans a
# junction that a single monomer cannot represent: against the monomer that
# design scores as two separate sub-40-column hits and clears both arms, against
# the dimer it is one long hit and rejects. Two repeats is the smallest number
# that covers the whole permitted length band, so it is the number frozen.
UBIQUITIN_TANDEM_REPEATS_SEARCHED = 2

# ── the corpus loader ──────────────────────────────────────────────────────
KNOWN_BINDER_CORPUS_ENV = "CAMPAIGN_KNOWN_BINDER_CORPUS"
# Protocol L79 names the folder. Kept as a constant so an operator staging the
# corpus and a reviewer reading the NOT_RUN reason see the same string.
KNOWN_BINDER_CORPUS_FOLDER = "02 ProteinBase"
_CORPUS_FASTA_SUFFIXES = (".fasta", ".fa", ".faa", ".fas", ".seq")
_CORPUS_CSV_SUFFIXES = (".csv", ".tsv")
# Column spellings a ProteinBase collection export actually uses. Matched
# case-insensitively; the first present wins, in this order.
_CORPUS_CSV_SEQUENCE_COLUMNS = ("sequence", "binder_sequence", "seq", "protein_sequence")
_CORPUS_CSV_ID_COLUMNS = ("id", "name", "design_id", "designer", "submission_id")

# Anything shorter than this is not a binder record, it is a header artifact or a
# truncated cell. Protocol L62 puts the permitted binder band at 35-160 residues;
# the floor is set at the bottom of that band rather than lower, because a
# 6-residue "sequence" in a corpus file aligns to everything and would reject the
# pool. Entries below it are DROPPED WITH A COUNT, never silently.
CORPUS_MIN_ENTRY_LENGTH = 35

# ~0.5 ms per 100x152 alignment, measured (see
# tests/test_campaign_local_alignment.py). 2e6 pairs is ~17 minutes of wall
# clock, which is the most a pre-scoring pass may spend before the answer is
# "stage the MMseqs2 index protocol L79 already asks for". Raising rather than
# grinding: an hours-long silent stall in a 15-minute governor cycle looks
# exactly like a hang.
CORPUS_LOCAL_ALIGNMENT_MAX_PAIRS = 2_000_000

# ── when the corpus stops being "a handful" and becomes a DATABASE ─────────
#
# The scoping note above admits the low-identity arm against the known-binder
# corpus on the stated premise that it is "a handful of curated binders". That
# premise was never checked against a real corpus, and it is FALSE for the one
# protocol L79 actually points at: the ProteinBase collections are ~16,500
# published competition binders, not a handful.
#
# MEASURED, on the real staged corpus, not argued: 20 de novo sequences of
# designed composition and length 50-120, screened against all 16,519 entries
# (330,380 pairs), produced 959 local-arm hits and **20 REJECTs out of 20**. Not
# one global-arm hit among them. The per-subject chance rate is p = 0.0029,
# which is exactly the "well under 1% per subject" the note above measured
# against ONE ubiquitin subject — and 1 - (1-p)^S is the pool cost:
#
#     S=10 -> 2.9%   S=18 -> 5.1%   S=50 -> 13.5%
#     S=100 -> 25.2%   S=386 -> 67.4%   S=16519 -> ~100%
#
# So this is the identical failure the note already refuses for UniRef90 — "a
# gate that rejects the entire pool is not a stricter gate, it is a broken one"
# — reached at four orders of magnitude fewer subjects than anyone expected.
# The remedy is the module's own: above this size the corpus is treated like
# UniRef90, i.e. the 60%/50% global arm only, and the suppression is DISCLOSED
# on `subjects_screened` rather than silently applied.
#
# The threshold is the largest corpus whose expected false-reject cost stays
# under 5% of a clean pool at the measured rate: ln(0.95)/ln(1-0.0029) = 17.7.
# A genuinely hand-curated set of a dozen binders keeps both arms and behaves
# exactly as before; nothing at real corpus scale does.
CORPUS_LOCAL_ARM_MEASURED_CHANCE_RATE = 0.0029
CORPUS_LOCAL_ARM_MAX_ENTRIES = 17


@dataclass(frozen=True)
class CorpusEntry:
    """One known binder: an id and a sequence."""

    entry_id: str
    sequence: str
    source: str = ""


@dataclass(frozen=True)
class KnownBinderCorpus:
    """The staged known-binder corpus, or a stated reason there is none.

    ``available`` is the whole point. An empty corpus and a corpus that was never
    staged are the same object shape and completely different facts: the first
    would let the gate PASS every design against zero subjects, which is the
    "gate reports itself as run while filtering nothing" failure. So an empty or
    missing corpus is ``available=False`` and the gate reports NOT_RUN.
    """

    entries: tuple[CorpusEntry, ...] = ()
    source: str = ""
    available: bool = False
    unavailable_reason: str | None = None
    skipped_short_entries: int = 0

    def __len__(self) -> int:
        return len(self.entries)


def _parse_fasta(text: str, source: str) -> list[CorpusEntry]:
    entries: list[CorpusEntry] = []
    header: str | None = None
    chunks: list[str] = []

    def flush() -> None:
        if header is None:
            return
        sequence = clean_protein_sequence("".join(chunks))
        if sequence:
            entries.append(CorpusEntry(entry_id=header, sequence=sequence, source=source))

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            flush()
            header = stripped[1:].strip() or f"{source}:{len(entries) + 1}"
            chunks = []
        elif header is not None:
            chunks.append(stripped)
    flush()
    return entries


def _parse_delimited(path: Path) -> list[CorpusEntry]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    entries: list[CorpusEntry] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        fieldnames = [str(name or "") for name in (reader.fieldnames or [])]
        lowered = {name.strip().lower(): name for name in fieldnames}
        sequence_column = next(
            (lowered[c] for c in _CORPUS_CSV_SEQUENCE_COLUMNS if c in lowered), None
        )
        if sequence_column is None:
            # Named, not swallowed: a corpus file the loader could not read is a
            # hole in the gate, and "0 entries" would look like a small corpus.
            raise NoveltyGateError(
                f"{path.name} has no sequence column (looked for "
                f"{', '.join(_CORPUS_CSV_SEQUENCE_COLUMNS)}; it has "
                f"{', '.join(fieldnames) or 'no header'})"
            )
        id_column = next((lowered[c] for c in _CORPUS_CSV_ID_COLUMNS if c in lowered), None)
        for index, row in enumerate(reader):
            sequence = clean_protein_sequence(row.get(sequence_column))
            if not sequence:
                continue
            entry_id = str(row.get(id_column) or "").strip() if id_column else ""
            entries.append(
                CorpusEntry(
                    entry_id=entry_id or f"{path.stem}:{index + 1}",
                    sequence=sequence,
                    source=str(path),
                )
            )
    return entries


def load_known_binder_corpus(path: Any = None) -> KnownBinderCorpus:
    """Load the known-binder corpus from a file or directory. Never invents one.

    ``path`` defaults to the ``CAMPAIGN_KNOWN_BINDER_CORPUS`` environment
    variable. It may be a single FASTA/CSV/TSV, or a directory walked recursively
    for those suffixes — the shape protocol L79's folder "02 ProteinBase" would
    arrive in.

    Returns ``available=False`` with ``unavailable_reason`` when the path is
    unset, missing, or holds no usable entry. It does NOT raise for a missing
    corpus: an unstaged corpus is a legitimate NOT_RUN that the gate discloses,
    and a campaign in its first hour has not staged it yet. It DOES raise for a
    corpus file it cannot parse, because that is a staged corpus being silently
    read as empty — the same failure wearing a success's clothes.
    """
    raw = path if path is not None else os.environ.get(KNOWN_BINDER_CORPUS_ENV)
    if raw is None or not str(raw).strip():
        return KnownBinderCorpus(
            unavailable_reason=(
                "the known-binder corpus (protocol L79, corpus folder "
                f"{KNOWN_BINDER_CORPUS_FOLDER!r}) is not staged: no path given and "
                f"${KNOWN_BINDER_CORPUS_ENV} is unset"
            )
        )
    root = Path(str(raw)).expanduser()
    if not root.exists():
        return KnownBinderCorpus(
            source=str(root),
            unavailable_reason=(
                f"the known-binder corpus path {str(root)!r} does not exist "
                f"(protocol L79 stages corpus folder {KNOWN_BINDER_CORPUS_FOLDER!r})"
            ),
        )

    files: list[Path]
    if root.is_dir():
        suffixes = _CORPUS_FASTA_SUFFIXES + _CORPUS_CSV_SUFFIXES
        files = sorted(
            item
            for item in root.rglob("*")
            if item.is_file() and item.suffix.lower() in suffixes
        )
    else:
        files = [root]

    entries: list[CorpusEntry] = []
    for item in files:
        suffix = item.suffix.lower()
        if suffix in _CORPUS_CSV_SUFFIXES:
            entries.extend(_parse_delimited(item))
        else:
            entries.extend(
                _parse_fasta(
                    item.read_text(encoding="utf-8", errors="replace"), str(item)
                )
            )

    kept = [entry for entry in entries if len(entry.sequence) >= CORPUS_MIN_ENTRY_LENGTH]
    skipped = len(entries) - len(kept)
    if not kept:
        return KnownBinderCorpus(
            source=str(root),
            skipped_short_entries=skipped,
            unavailable_reason=(
                f"the known-binder corpus at {str(root)!r} yielded no entry of at "
                f"least {CORPUS_MIN_ENTRY_LENGTH} residues "
                f"({len(files)} file(s) read, {skipped} entr(y/ies) too short)"
            ),
        )
    return KnownBinderCorpus(
        entries=tuple(kept),
        source=str(root),
        available=True,
        skipped_short_entries=skipped,
    )


def ubiquitin_subjects() -> list[CorpusEntry]:
    """The Ubiquitin positive control, as the tandem repeat actually searched."""
    return [
        CorpusEntry(
            entry_id="/".join(UBIQUITIN_ACCESSIONS),
            sequence=UBIQUITIN_MONOMER * UBIQUITIN_TANDEM_REPEATS_SEARCHED,
            source=(
                f"ubiquitin repeat unit x{UBIQUITIN_TANDEM_REPEATS_SEARCHED} "
                f"(UniProt {', '.join(UBIQUITIN_ACCESSIONS)})"
            ),
        )
    ]


# ── the arms ───────────────────────────────────────────────────────────────


def _arms_triggered(
    alignment: LocalAlignment,
    kind: str,
    *,
    global_identity_above: float,
    global_coverage_above: float,
    local_identity_at: float,
    local_columns_at: int,
    suppress_local_arm: bool = False,
) -> list[str]:
    """Which REJECT arms of L81 this alignment trips, for this subject kind."""
    hits: list[str] = []
    if kind in GLOBAL_ARM_SUBJECT_KINDS and (
        alignment.gapped_identity > global_identity_above
        and alignment.query_coverage > global_coverage_above
    ):
        hits.append("global_identity_coverage")
    if not suppress_local_arm and kind in LOCAL_ARM_SUBJECT_KINDS and (
        alignment.gapped_identity >= local_identity_at
        and alignment.aligned_columns >= local_columns_at
    ):
        hits.append("local_identity_length")
    return hits


@dataclass
class _SubjectOutcome:
    kind: str
    subject_id: str
    arms: list[str] = field(default_factory=list)
    record: dict[str, Any] = field(default_factory=dict)


def align_against_subjects(
    sequence: Any,
    subjects: Iterable[Any],
    kind: str,
    *,
    global_identity_above: float = NOVELTY_GLOBAL_IDENTITY_REJECT_ABOVE,
    global_coverage_above: float = NOVELTY_GLOBAL_COVERAGE_REJECT_ABOVE,
    local_identity_at: float = NOVELTY_LOCAL_IDENTITY_REJECT_AT,
    local_columns_at: int = NOVELTY_LOCAL_ALIGNED_COLUMNS_REJECT_AT,
    suppress_local_arm: bool = False,
) -> list[dict[str, Any]]:
    """Align one design against one subject set; return only the arm-tripping hits.

    Returns the HITS, not every alignment: 2,000 corpus alignments per design is
    2,000 rows of nothing, and a reject record that carries the whole scan cannot
    be read. The best non-hit is reported separately by the caller so the margin
    is still visible on a PASS.

    ``suppress_local_arm`` runs the 60%/50% arm ONLY. It exists for one caller —
    a known-binder corpus past ``CORPUS_LOCAL_ARM_MAX_ENTRIES``, where the
    low-identity arm's measured chance rate rejects the whole pool. Defaulting
    False keeps every other subject set exactly as it was.
    """
    if kind not in SUBJECT_KINDS:
        raise NoveltyGateError(
            f"unknown novelty subject kind {kind!r}; expected one of "
            f"{', '.join(SUBJECT_KINDS)}"
        )
    query = clean_protein_sequence(sequence)
    if not query:
        raise NoveltyGateError(
            "novelty needs a readable design sequence; got an empty one. An "
            "unreadable sequence is NOT_RUN for this design, never a scan with "
            "no hits."
        )
    out: list[dict[str, Any]] = []
    for subject in subjects:
        entry = _as_entry(subject)
        alignment = smith_waterman(query, entry.sequence)
        if alignment is None:
            continue
        arms = _arms_triggered(
            alignment,
            kind,
            suppress_local_arm=suppress_local_arm,
            global_identity_above=global_identity_above,
            global_coverage_above=global_coverage_above,
            local_identity_at=local_identity_at,
            local_columns_at=local_columns_at,
        )
        if not arms:
            continue
        out.append(
            {
                "kind": kind,
                "subject_id": entry.entry_id,
                "subject_source": entry.source,
                "arms": arms,
                **alignment.as_record(),
            }
        )
    return out


def _as_entry(subject: Any) -> CorpusEntry:
    if isinstance(subject, CorpusEntry):
        return subject
    if isinstance(subject, Mapping):
        sequence = clean_protein_sequence(
            subject.get("sequence") or subject.get("seq") or ""
        )
        entry_id = str(
            subject.get("entry_id")
            or subject.get("id")
            or subject.get("label")
            or subject.get("chain")
            or "unnamed"
        )
        source = str(subject.get("source") or "")
    elif isinstance(subject, str):
        sequence, entry_id, source = clean_protein_sequence(subject), "unnamed", ""
    elif isinstance(subject, Sequence) and len(subject) >= 2:
        entry_id, sequence = str(subject[0]), clean_protein_sequence(subject[1])
        source = ""
    else:
        raise NoveltyGateError(
            f"novelty subject {subject!r} is not a CorpusEntry, a mapping with a "
            "`sequence`, an (id, sequence) pair, or a bare sequence string"
        )
    if not sequence:
        raise NoveltyGateError(
            f"novelty subject {entry_id!r} carries no readable sequence. An empty "
            "subject silently screens against nothing."
        )
    return CorpusEntry(entry_id=entry_id, sequence=sequence, source=source)


def evaluate_precomputed_hits(
    hits: Iterable[Any],
    kind: str = SUBJECT_UNIREF90,
    *,
    global_identity_above: float = NOVELTY_GLOBAL_IDENTITY_REJECT_ABOVE,
    global_coverage_above: float = NOVELTY_GLOBAL_COVERAGE_REJECT_ABOVE,
) -> list[dict[str, Any]]:
    """The MMseqs2 seam: judge hits somebody else's search already produced.

    UniRef90 is ~200 million sequences behind an MMseqs2 index that protocol L79
    stages separately; nothing in this process can search it, and pretending
    otherwise is how the arm the protocol calls mandatory becomes a no-op. So the
    caller runs the search and hands the rows here, each carrying at least
    ``identity`` and ``coverage``.

    FRACTIONS OR PERCENTS, DISAMBIGUATED BY VALUE AND THEN REFUSED IF STILL
    AMBIGUOUS. MMseqs2's ``fident`` is a fraction and its convert-alis ``pident``
    is a percent; the same column name is used for both in different pipelines,
    and 0.85 read as a percent clears every threshold while 85 read as a fraction
    rejects everything. A value in (1, 100] is read as a percent, a value in
    [0, 1] as a fraction, and anything else raises. The one genuinely ambiguous
    value is exactly 1 — 1% or 100% — and it is read as a FRACTION (100%), the
    reading that rejects, because a novelty ban's failure direction is to let a
    copy through.
    """
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(hits or []):
        if not isinstance(raw, Mapping):
            raise NoveltyGateError(
                f"precomputed hit {index} is {type(raw).__name__}, not a mapping "
                "with `identity` and `coverage`"
            )
        identity = _as_fraction(raw.get("identity", raw.get("fident", raw.get("pident"))), "identity", index)
        coverage = _as_fraction(raw.get("coverage", raw.get("qcov", raw.get("cov"))), "coverage", index)
        if identity is None or coverage is None:
            raise NoveltyGateError(
                f"precomputed hit {index} is missing identity or coverage "
                "(identity/fident/pident and coverage/qcov/cov). A hit with no "
                "coverage cannot be judged against L81's >50% clause, and "
                "treating it as 0 would pass a full-length copy."
            )
        if identity > global_identity_above and coverage > global_coverage_above:
            out.append(
                {
                    "kind": kind,
                    "subject_id": str(
                        raw.get("subject_id") or raw.get("target") or f"hit_{index + 1}"
                    ),
                    "subject_source": str(raw.get("source") or kind),
                    "arms": ["global_identity_coverage"],
                    "gapped_identity": round(identity, 6),
                    "query_coverage": round(coverage, 6),
                    "precomputed": True,
                }
            )
    return out


def _as_fraction(value: Any, label: str, index: int) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise NoveltyGateError(
            f"precomputed hit {index} has a non-numeric {label} {value!r}"
        ) from exc
    if 0.0 <= number <= 1.0:
        return number
    if 1.0 < number <= 100.0:
        return number / 100.0
    raise NoveltyGateError(
        f"precomputed hit {index} has {label}={number}, which is neither a "
        "fraction in [0, 1] nor a percent in (1, 100]"
    )


# ── the per-design verdict ─────────────────────────────────────────────────


def novelty_verdict(
    sequence: Any,
    *,
    corpus: KnownBinderCorpus | None = None,
    corpus_hits: Iterable[Any] | None = None,
    target_chains: Iterable[Any] = (),
    control_chains: Iterable[Any] = (),
    uniref90_hits: Iterable[Any] | None = None,
    tm_screen: Mapping[str, Any] | None = None,
    check_ubiquitin: bool = True,
    required_subjects: Iterable[str] = NOVELTY_REQUIRED_SUBJECTS_DISPATCH,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """L81 for one design: ``{"verdict", "reason", "hits", "subjects", ...}``.

    THE COMBINATION RULE, and why it is not "all arms must run":

      REJECT   any arm on any subject tripped. Definite, and reported even when
               other subject sets could not be screened — a proven copy is a copy
               whether or not UniRef90 was staged.
      NOT_RUN  no arm tripped, but a REQUIRED subject set was unavailable. The
               design is NOT cleared; the reason names which set is missing.
      PASS     no arm tripped and every required subject set was screened.

    ``required_subjects`` defaults to the DISPATCH tier
    (``NOVELTY_REQUIRED_SUBJECTS_DISPATCH``) because protocol L79 says production
    scoring is not gated on UniRef90 staging. The sheet writer must pass
    ``NOVELTY_REQUIRED_SUBJECTS_FINAL``: the same sentence makes the full-UniRef90
    check and the Ubiquitin rejection required "before any row reaches the FINAL
    ranked sheet". Two named tiers rather than a bare boolean, so which tier a
    call site chose is readable at the call site.

    ``tm_screen`` is ``qa_tm_helpers.target_mimic_screen``'s returned dict, passed
    through rather than recomputed. Its REJECT is L81's third arm and is adopted
    verbatim; its NOT_RUN is carried into the reason, never absorbed into a pass.

    ``arms_not_run`` is always present and maps every arm that did NOT run to the
    reason it did not, independently of ``required_subjects`` — see
    ``NOVELTY_SKIPPABLE_ARMS`` for why disclosure is decoupled from enforcement.
    ``subjects_screened`` keeps its existing meaning exactly: a key appears only
    for an arm that DID run, so the two are complements and a reader can tell
    "screened and clean" from "never screened" without inferring either.
    """
    limits = dict(NOVELTY_THRESHOLDS)
    limits.update(thresholds or {})
    # Materialized BEFORE the empty-sequence return so that return can name its
    # tier too. A NOT_RUN row still travels to the sheet, and a NOT_RUN with no
    # tier is indistinguishable there from a row the gate never reached.
    # Validation of the members stays below, where it was: raising on a bad
    # subject set for a design whose sequence is unreadable would replace this
    # function's own NOT_RUN with an exception.
    required = tuple(required_subjects)
    tier = novelty_tier(required)
    query = clean_protein_sequence(sequence)
    if not query:
        blank = (
            "the design carries no readable sequence, so no novelty arm could "
            "be evaluated"
        )
        return {
            "verdict": VERDICT_NOT_RUN,
            "reason": None,
            "not_run_reason": blank,
            "hits": [],
            "subjects_screened": {},
            # EVERY arm, not `{}`. An empty map here would read as "all arms ran"
            # — the same silence this key exists to remove — and this return is
            # the one path where genuinely none of them did.
            "arms_not_run": {arm: blank for arm in NOVELTY_SKIPPABLE_ARMS},
            "thresholds": limits,
            "tier": tier,
            "required_subjects": required,
        }

    unknown = [kind for kind in required if kind not in SUBJECT_KINDS]
    if unknown:
        raise NoveltyGateError(
            f"unknown required novelty subject(s) {', '.join(unknown)}; expected "
            f"from {', '.join(SUBJECT_KINDS)}"
        )

    arm_kwargs = {
        "global_identity_above": float(limits["global_identity_reject_above"]),
        "global_coverage_above": float(limits["global_coverage_reject_above"]),
        "local_identity_at": float(limits["local_identity_reject_at"]),
        "local_columns_at": int(limits["local_aligned_columns_reject_at"]),
    }

    hits: list[dict[str, Any]] = []
    screened: dict[str, int] = {}
    missing: list[str] = []
    arms_not_run: dict[str, str] = {}

    def _skipped(arm: str, reason: str, *, blocks: bool | None = None) -> None:
        """Record an arm that did not run; downgrade the design only if required.

        ONE reason string written to BOTH places, so an artifact's
        ``arms_not_run`` entry and the ``not_run_reason`` a reviewer reads can
        never drift apart. ``blocks`` defaults to "is this subject required",
        which is the meaning ``required`` has always had and the behaviour this
        function must not change. The TM arm passes it explicitly: it is an arm
        rather than a subject kind, so it can never appear in ``required``.
        """
        arms_not_run[arm] = reason
        if blocks is None:
            blocks = arm in required
        if blocks:
            missing.append(reason)

    if check_ubiquitin:
        subjects = ubiquitin_subjects()
        hits.extend(
            align_against_subjects(query, subjects, SUBJECT_UBIQUITIN, **arm_kwargs)
        )
        screened[SUBJECT_UBIQUITIN] = len(subjects)
    else:
        _skipped(
            SUBJECT_UBIQUITIN,
            "the Ubiquitin positive-control rejection was switched off, and "
            "protocol L79 requires it before any row reaches the FINAL sheet",
        )

    corpus_screened = False
    corpus_screened = False
    if corpus is not None and corpus.available:
        pairs = len(corpus.entries)
        if pairs > CORPUS_LOCAL_ALIGNMENT_MAX_PAIRS:
            raise NoveltyGateError(
                f"the known-binder corpus holds {pairs} entries, above the "
                f"{CORPUS_LOCAL_ALIGNMENT_MAX_PAIRS}-alignment cap for the "
                "in-process aligner. Stage the MMseqs2 index protocol L79 asks "
                "for and feed its rows through evaluate_precomputed_hits."
            )
        # THE ARM SET DEPENDS ON THE CORPUS SIZE, not on its name. See
        # CORPUS_LOCAL_ARM_MAX_ENTRIES: measured on the real staged corpus, the
        # low-identity arm rejects 20 of 20 clean de novo designs at 16,519
        # entries, which is the "gate that rejects the entire pool" this module
        # already refuses for UniRef90.
        corpus_is_database = pairs > CORPUS_LOCAL_ARM_MAX_ENTRIES
        hits.extend(
            align_against_subjects(
                query,
                corpus.entries,
                SUBJECT_KNOWN_BINDER_CORPUS,
                suppress_local_arm=corpus_is_database,
                **arm_kwargs,
            )
        )
        screened[SUBJECT_KNOWN_BINDER_CORPUS] = pairs
        if corpus_is_database:
            screened["known_binder_corpus_local_arm_not_run"] = 1
        corpus_screened = True
    # THE SAME SEAM UniRef90 HAS, for the same reason. Past the caller's budget
    # the in-process aligner is the wrong instrument, and L79 already names the
    # right one — an MMseqs2 search whose rows arrive here.
    #
    # DISCLOSED REDUCTION, not equivalence: a precomputed row carries identity
    # and coverage and nothing else, so it is judged on L81's 60%/50% arm only.
    # The >=30%-over->=40-columns arm needs the alignment itself and is NOT
    # evaluated for a corpus screened this way.
    if corpus_hits is not None:
        supplied = list(corpus_hits)
        hits.extend(
            evaluate_precomputed_hits(
                supplied,
                SUBJECT_KNOWN_BINDER_CORPUS,
                global_identity_above=arm_kwargs["global_identity_above"],
                global_coverage_above=arm_kwargs["global_coverage_above"],
            )
        )
        screened["known_binder_corpus_hit_rows"] = len(supplied)
        screened["known_binder_corpus_hits_are_precomputed"] = 1
        screened["known_binder_corpus_local_arm_not_run"] = 1
        corpus_screened = True
    if not corpus_screened:
        # Track A's disclosure, preserved through the merge: an arm that did not
        # run says so on the artifact whether or not `required` blocks on it.
        _skipped(
            SUBJECT_KNOWN_BINDER_CORPUS,
            (corpus.unavailable_reason if corpus is not None else None)
            or load_known_binder_corpus(None).unavailable_reason
            or "the known-binder corpus is not staged",
        )

    for kind, chains in (
        (SUBJECT_TARGET_CHAIN, target_chains),
        (SUBJECT_CONTROL_CHAIN, control_chains),
    ):
        entries = [_as_entry(chain) for chain in chains]
        if entries:
            hits.extend(align_against_subjects(query, entries, kind, **arm_kwargs))
            screened[kind] = len(entries)
        else:
            # THE SILENT SKIP THIS KEY EXISTS FOR. Both of these default to `()`
            # and neither subject is in either `required` tier, so before
            # `_skipped` recorded them unconditionally this branch produced
            # nothing at all — a design that was a verbatim slice of the
            # campaign's own target came back NOT_RUN with no trace that the
            # target-mimic arm had never been pointed at the target.
            _skipped(kind, f"no {kind.replace('_', ' ')} sequences were supplied")

    if uniref90_hits is not None:
        supplied = list(uniref90_hits)
        hits.extend(
            evaluate_precomputed_hits(
                supplied,
                SUBJECT_UNIREF90,
                global_identity_above=arm_kwargs["global_identity_above"],
                global_coverage_above=arm_kwargs["global_coverage_above"],
            )
        )
        # For every other kind this is a count of SUBJECTS aligned here. For
        # UniRef90 it is the count of precomputed hit ROWS judged, because this
        # process did not search UniRef90 and must not report a number implying
        # it searched 200 million sequences. `uniref90_hits_are_precomputed`
        # marks the difference so a reader of the artifact cannot miss it.
        screened[SUBJECT_UNIREF90] = len(supplied)
        screened["uniref90_hits_are_precomputed"] = 1
    else:
        _skipped(
            SUBJECT_UNIREF90,
            "no UniRef90 MMseqs2 hits were supplied; protocol L79 requires the "
            "full-UniRef90 novelty check before any row reaches the FINAL sheet",
        )

    tm_verdict = str((tm_screen or {}).get("verdict") or "")
    if tm_verdict == VERDICT_REJECT:
        hits.append(
            {
                "kind": SUBJECT_TARGET_CHAIN,
                "subject_id": str((tm_screen or {}).get("closest") or "unnamed chain"),
                "subject_source": "qa_tm_helpers.target_mimic_screen",
                "arms": [ARM_TM_SCORE],
                "tm_score": (tm_screen or {}).get("tm_max"),
            }
        )
    elif tm_screen is None:
        # NOT blocking, deliberately. A screen that was supplied and could not
        # run is an active failure of a check the caller intended (below); a
        # screen that was never supplied is a caller that has not wired the arm
        # up, and on the production path that is EVERY design. Downgrading the
        # whole pool to NOT_RUN for it would stall the campaign rather than
        # screen it, so this arm is disclosed and not enforced — which is the
        # entire reason `arms_not_run` is separate from `missing`.
        _skipped(
            ARM_TM_SCORE,
            "no TM target-mimic screen was supplied; protocol L81's third arm "
            "did not run for this design",
            blocks=False,
        )
    elif tm_verdict == VERDICT_NOT_RUN:
        _skipped(
            ARM_TM_SCORE,
            "the TM target-mimic arm is NOT_RUN: "
            + str((tm_screen or {}).get("not_run_reason") or "no reason given"),
            blocks=True,
        )

    if hits:
        worst = max(hits, key=lambda hit: float(hit.get("gapped_identity") or 0.0))
        return {
            "verdict": VERDICT_REJECT,
            "reason": _reason(worst, limits),
            "not_run_reason": "; ".join(missing) or None,
            "hits": hits,
            "subjects_screened": screened,
            "arms_not_run": arms_not_run,
            "thresholds": limits,
        }
    if missing:
        return {
            "verdict": VERDICT_NOT_RUN,
            "reason": None,
            "not_run_reason": "; ".join(missing),
            "hits": [],
            "subjects_screened": screened,
            "arms_not_run": arms_not_run,
            "thresholds": limits,
        }
    # A PASS carries `arms_not_run` too, and that is the whole point: this is the
    # verdict that used to be indistinguishable from a full screen. "Clean
    # against everything the caller pointed at me" is not "clean", and the
    # difference has to be on the artifact rather than inferable from it.
    return {
        "verdict": VERDICT_PASS,
        "reason": None,
        "not_run_reason": None,
        "hits": [],
        "subjects_screened": screened,
        "arms_not_run": arms_not_run,
        "thresholds": limits,
    }


def _reason(hit: Mapping[str, Any], limits: Mapping[str, Any]) -> str:
    """A reason a reviewer can act on: the arm, the subject and the numbers."""
    arms = ", ".join(str(arm) for arm in (hit.get("arms") or []))
    if "tm_score" in (hit.get("arms") or []):
        return (
            f"novelty REJECT ({arms}): TM-score {hit.get('tm_score')} to "
            f"{hit.get('subject_id')} >= {limits['tm_score_reject_at']} "
            "(protocol L81)"
        )
    return (
        f"novelty REJECT ({arms}) against {hit.get('kind')} "
        f"{hit.get('subject_id')!r}: {hit.get('gapped_identity')} gapped local "
        f"identity over {hit.get('aligned_columns')} aligned columns, "
        f"{hit.get('query_coverage')} query coverage (protocol L81 rejects at "
        f">{limits['global_identity_reject_above']} identity over "
        f">{limits['global_coverage_reject_above']} coverage, or "
        f">={limits['local_identity_reject_at']} identity over "
        f">={limits['local_aligned_columns_reject_at']} aligned residues)"
    )


def novelty_verdicts(
    sequences_by_design_id: Mapping[Any, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Run L81 over a pool. Same shape as ``monomer_foldability_verdicts``.

    ``rejected`` is the list protocol L86 needs, and
    :func:`novelty_rejects` turns it into the traceable records the pool check
    consumes.

    ``arms_not_run`` is the pool's arm-coverage gap: the arms that ran for NO
    design here. Without it the per-design disclosure never reaches an artifact
    at all — a PASS design contributes nothing to ``measurements`` (only REJECTs
    do) and nothing to ``not_run_reasons``, so a pool that was screened against
    no target chain at all looked identical to one that was screened clean.
    """
    verdicts: dict[str, str] = {}
    reasons: dict[str, str] = {}
    measurements: dict[str, Any] = {}
    not_run_reasons: dict[str, str] = {}
    pool_arms_not_run: dict[str, str] | None = None
    for raw_id, sequence in sequences_by_design_id.items():
        design_id = "" if raw_id is None else str(raw_id).strip()
        if not design_id or design_id in verdicts:
            continue
        try:
            outcome = novelty_verdict(sequence, **kwargs)
        except LocalAlignmentError as exc:
            # An unreadable sequence is this design's NOT_RUN, not the pool's
            # crash: one blank cell must not stop the other 19,999 designs from
            # being screened.
            verdicts[design_id] = VERDICT_NOT_RUN
            not_run_reasons[design_id] = str(exc)
            continue
        verdicts[design_id] = str(outcome["verdict"])
        # INTERSECTION, not union. Every design here is screened with the same
        # kwargs, so the intersection is exactly the pool's configuration gap:
        # "these arms ran for no design in this pool". A union would be a lie —
        # a blank-sequence design reports every arm as not-run (correct for
        # itself), and unioning it in would claim the Ubiquitin arm never ran
        # for a pool where it ran on all but that one row. Designs that raised
        # `LocalAlignmentError` above `continue` before reaching here and so
        # contribute nothing: they were not screened at all, which says nothing
        # about how the pool was configured.
        design_arms = dict(outcome.get("arms_not_run") or {})
        if pool_arms_not_run is None:
            # A COPY: `design_arms` is also stored on this design's REJECT
            # measurements below, and the two must not alias.
            pool_arms_not_run = dict(design_arms)
        else:
            pool_arms_not_run = {
                arm: reason
                for arm, reason in pool_arms_not_run.items()
                if arm in design_arms
            }
        if outcome["verdict"] == VERDICT_REJECT:
            reasons[design_id] = str(outcome["reason"])
            measurements[design_id] = {
                "hits": outcome["hits"],
                "subjects_screened": outcome["subjects_screened"],
                # A REJECT record names what was NOT screened as well as what
                # was: L86 asks for traceable rejects, and "rejected on the
                # corpus arm, with the target-chain arm never run" is a
                # different fact from "rejected after a full screen".
                "arms_not_run": design_arms,
            }
        elif outcome["not_run_reason"]:
            not_run_reasons[design_id] = str(outcome["not_run_reason"])
    return {
        "verdicts": verdicts,
        "passed": [d for d, v in verdicts.items() if v == VERDICT_PASS],
        "rejected": [d for d, v in verdicts.items() if v == VERDICT_REJECT],
        "not_run": [d for d, v in verdicts.items() if v == VERDICT_NOT_RUN],
        "not_run_reasons": not_run_reasons,
        "reasons": reasons,
        "arms_not_run": pool_arms_not_run or {},
        "thresholds": dict(NOVELTY_THRESHOLDS),
        "measurements": measurements,
    }


def novelty_rejects(outcome: Mapping[str, Any]) -> list[PrescoringReject]:
    """:func:`novelty_verdicts` output -> the L86 reject records."""
    from .prescoring_rejects import rejects_from_verdicts

    return rejects_from_verdicts(
        outcome.get("verdicts") or {},
        PRESCORING_GATE_NOVELTY,
        reasons=outcome.get("reasons") or {},
        measurements=outcome.get("measurements") or {},
    )
