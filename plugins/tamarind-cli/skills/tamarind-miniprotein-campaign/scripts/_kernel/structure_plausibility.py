"""Pre-scoring structural plausibility — protocol L84, the fourth mandatory gate.

The protocol clause this implements, verbatim (L84)::

    4. structural-plausibility: backbone geometry, steric clashes, core packing,
       with thresholds you choose at kickoff and freeze.

WHAT WAS HERE BEFORE: nothing. Not a constant, not an offender check, not a
column. ``structural_plausibility`` was a token in ``prescoring_rejects`` and a
sentence in a prompt, and protocol L79 makes the assessment mandatory ("Every
candidate must, before being scored, be assessed for" all four). Three of the
four had code — ``novelty_gate`` for L81, ``qa_analysis_helpers``' liability
offenders for L82, ``screen_gate_metrics`` for L83 — and this one was the hole.
An unimplemented gate is not a lenient gate: ``prescoring_gate_pool_violations``
returns ``{}`` when a gate recorded no rejects, so a campaign that never ran this
one reads downstream exactly like a campaign that ran it and found nothing.

WHY THE THRESHOLDS ARE OURS AND WHAT THAT OBLIGES
-------------------------------------------------
L84 is the only one of the four that hands the numbers to us: "with thresholds
you choose at kickoff and freeze". That is a licence to pick, not a licence to
leave them undefended, so every constant below carries either a literature
citation or an explicit "ours, chosen because ...". They are frozen in
:data:`STRUCTURAL_PLAUSIBILITY_THRESHOLDS` as ONE dict so a charter can disclose
the whole set and the sheet writer can recompute against it (protocol L90 makes
the writer recompute every gate and match the carried value to 1e-4 — which is
also why every check below returns its NUMBERS and not merely a boolean).

THE THREE SUB-CHECKS ARE INDEPENDENT, AND THAT IS THE POINT
-----------------------------------------------------------
L84 names three things and they fail on different evidence. Backbone geometry
reads a CA trace; steric clashes need side chains; core packing needs enough
residues for a core to exist. Folding them into one boolean would mean a
backbone-only generator output — which HAS a readable CA trace and NO side
chains — either passes a clash check it never ran, or is rejected for geometry
that is fine. So each sub-check returns its own PASS / REJECT / NOT_RUN, and the
combination rule is stated once, in :func:`structural_plausibility_verdict`.

THE SUBJECTS ARE PREDICTED AND DESIGNED BACKBONES, not crystal structures. The
bands below are tight enough that a moderate-resolution deposited model can trip
them (a real 2.4 A entry can carry a 3.19 A CA-CA virtual bond in a disordered
Gly-Gly stretch, which is not a valid peptide geometry at any omega). That is
the correct verdict for such a link and it is worth stating out loud, because it
is the one place the gate is stricter than "would the PDB have accepted this".

Self-contained: standard library + numpy. numpy is a production dependency
(transitive via pandas). ``biotite``, ``scipy`` and ``biopython`` are NOT in the
campaign image — ``Dockerfile.campaign`` runs ``uv sync --no-dev --extra
campaign`` and biopython is dev-group only — so nothing here may reach for one.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .prescoring_rejects import (
    PRESCORING_GATE_STRUCTURAL_PLAUSIBILITY,
    VERDICT_NOT_RUN,
    VERDICT_PASS,
    VERDICT_REJECT,
    PrescoringReject,
    rejects_from_verdicts,
)

__all__ = [
    "CHECK_BACKBONE_GEOMETRY",
    "CHECK_CORE_PACKING",
    "CHECK_STERIC_CLASHES",
    "STRUCTURAL_PLAUSIBILITY_CHECKS",
    "STRUCTURAL_PLAUSIBILITY_THRESHOLDS",
    "StructurePlausibilityInputError",
    "StructureUnreadable",
    "backbone_geometry_check",
    "core_packing_check",
    "steric_clash_check",
    "structural_plausibility_gate_stamp",
    "structural_plausibility_offenders",
    "structural_plausibility_rejects",
    "structural_plausibility_verdict",
    "structural_plausibility_verdicts",
]


class StructurePlausibilityInputError(ValueError):
    """The structure handed in cannot answer the question that was asked of it.

    RAISES rather than degrading to NOT_RUN, and the distinction is the whole
    discipline of this module. A multi-chain file handed to a monomer gate is not
    a design we could not measure — it is the WRONG design being measured, and
    silently picking whichever chain came first would score the target instead of
    the binder. ``screen_gate_metrics.monomer_plddt_from_fold_rows`` raises on
    exactly this class of error (a co-folded table read as a monomer table) and
    ``qa_tm_helpers._ca_coordinates`` raises on exactly this input, for the same
    reason: the answer would look fine and be about something else.
    """


class StructureUnreadable(StructurePlausibilityInputError):
    """There is no readable structure here at all. Becomes NOT_RUN, never a pass.

    Subclass of the above so a caller that wants to treat every input problem
    alike still can, but the per-design entry points catch THIS one specifically
    and stamp NOT_RUN. Absence of a structure is a hole in the measurement (a
    legitimate, disclosable state); a complex where a monomer belongs is a wiring
    error that must not be absorbed into a per-design NOT_RUN, because it is
    systematic — it would silently blank the gate for the entire pool.
    """


# ── sub-check names ────────────────────────────────────────────────────────
#
# Tokens, not free text, for the reason `prescoring_rejects` gives for the gate
# names: these are dict keys and grep targets, and a sub-check spelled two ways
# is a sub-check whose REJECT is reported under one spelling and looked for under
# the other.
CHECK_BACKBONE_GEOMETRY = "backbone_geometry"
CHECK_STERIC_CLASHES = "steric_clashes"
CHECK_CORE_PACKING = "core_packing"

STRUCTURAL_PLAUSIBILITY_CHECKS: tuple[str, ...] = (
    CHECK_BACKBONE_GEOMETRY,
    CHECK_STERIC_CLASHES,
    CHECK_CORE_PACKING,
)


# ── (a) backbone geometry ──────────────────────────────────────────────────
#
# CA(i)-CA(i+1) IS A RIGID DISTANCE, not a soft preference, and that is what
# makes it a gate rather than a statistic. The peptide unit is planar and its
# internal geometry is fixed by Engh & Huber (1991) ideal values (N-CA 1.458,
# CA-C 1.525, C-N 1.329 A; angles CA-C-N 116.2, C-N-CA 121.7 deg); feeding those
# through a trans peptide (omega = 180) puts CA(i)-CA(i+1) at 3.80 A, and the
# crystallographic spread about it is ~0.04 A. Nothing a folding model or a
# backbone generator emits moves it.
BACKBONE_CA_CA_TRANS_A = 3.80  # Engh & Huber 1991 ideal geometry, omega = 180
# The same geometry at omega = 0. Carried as a named constant even though cis is
# DISALLOWED below, because it is the number that sets where the band's lower
# edge may sit: a band wide enough to reach 2.93 is a band that has stopped
# distinguishing a peptide bond from a modelling error.
BACKBONE_CA_CA_CIS_A = 2.93  # Engh & Huber 1991 ideal geometry, omega = 0

# OURS, chosen because: the crystallographic sigma on the trans virtual bond is
# ~0.04 A, so +/-0.30 is roughly 7 sigma — wide enough that no predictor's or
# relaxation's numerical slack trips the gate, and narrow enough that the two
# things it exists to catch are nowhere near it. A chain break (the CA-CA jump
# across a missing segment, or two segments a generator never joined) is
# typically > 5 A; the nearest competing REAL geometry, a cis peptide at 2.93 A,
# is 0.57 A outside the lower edge. Widening this to +/-0.6 would swallow cis and
# stop the check from meaning anything; tightening it to +/-0.1 would start
# rejecting ordinary predicted backbones.
BACKBONE_CA_CA_TOLERANCE_A = 0.30

# THE CIS DECISION, made rather than left implicit: cis peptides are REJECTED.
#
# Ours, chosen because none of the campaign's generators sample omega = 0.
# RFdiffusion / RFdiffusion3 backbones, ProteinMPNN-threaded sequences and
# ESMFold2 / Protenix predictions are trans by construction, so a CA-CA landing
# in the cis range in one of OUR designs is a modelling artifact, not a designed
# cis-proline. Opening a second admitted band at 2.93 +/- 0.30 would cost more
# than it buys: [2.63, 3.23] also admits genuinely distorted links (a real 2.4 A
# deposited entry carries a Gly-Gly CA-CA of 3.19 A that is a valid geometry at
# no omega at all), so the "allow cis" reading passes the exact modelling error
# this sub-check exists to find.
#
# THE COST IS REAL AND STATED: a design that genuinely wanted a cis-Pro — a
# macrocycle or a constrained peptide, protocol territory but not this campaign's
# arms — would be rejected here. Flip this to True at kickoff for such a campaign
# and the band widens; do not widen the tolerance instead.
BACKBONE_ALLOW_CIS_PEPTIDE = False

# The peptide bond itself, when N and C are in the file. Engh & Huber 1991:
# C-N = 1.329 +/- 0.014 A. Tolerance is ours at +/-0.10 A (~7 sigma, the same
# multiple as the CA-CA band, so the two arms are equally forgiving) — the arm
# exists to catch a backbone whose atoms were written independently of each other
# (a re-assembled or mis-ordered chain), which misses by whole Angstroms.
BACKBONE_PEPTIDE_C_N_A = 1.329
BACKBONE_PEPTIDE_C_N_TOLERANCE_A = 0.10

# Two residues is the fewest that HAS a consecutive pair. Below it the sub-check
# is NOT_RUN, never PASS: "there was no bond to measure" is not "every bond was
# fine", and a one-residue file reaching a gate is itself worth surfacing.
BACKBONE_MIN_RESIDUES = 2


# ── (b) steric clashes ─────────────────────────────────────────────────────
#
# MolProbity's definition, adopted verbatim: a clash is a non-bonded overlap of
# >= 0.4 A between two atoms' van der Waals surfaces, and the clashscore is the
# number of such overlaps per 1000 atoms (Chen et al. 2010, Acta Cryst D66, 12).
STERIC_CLASH_OVERLAP_A = 0.40
STERIC_CLASHSCORE_PER_ATOMS = 1000

# THE NORMALIZATION IS NOT MolProbity's, and saying so is load-bearing.
# MolProbity runs on an all-atom model with hydrogens added by Reduce, and most
# of the clashes it counts involve a hydrogen. We have heavy atoms only — the
# structures reaching this gate come out of generators and folding models that
# emit no hydrogens — so the denominator here is HEAVY atoms and the numerator is
# heavy-heavy overlaps only. Every overlap counted here is one MolProbity would
# also count; MolProbity additionally counts overlaps we cannot see. So this
# number is a LOWER BOUND on the MolProbity clashscore, and a ceiling of X here
# is strictly stricter than a ceiling of X there.
STERIC_CLASHSCORE_NORMALIZATION = (
    "clashes per 1000 HEAVY atoms of the scored chain (no hydrogens; a lower "
    "bound on the MolProbity all-atom clashscore, not the same number)"
)

# OURS, chosen because a 0.4 A heavy-atom overlap at the level of one or two per
# few-hundred atoms is ordinary in a predicted side-chain packing and would be
# relieved by any rotamer repack — it is not evidence of an implausible fold.
# A 50-residue design carries ~400 heavy atoms, so one clash scores ~2.5 and the
# granularity of this metric on a miniprotein is coarse: a ceiling of 5 would
# reject an ordinary model for its second mild contact. 10 per 1000 is ~3 clashes
# in a 50-residue design and ~13 in a 160-residue one (protocol L62's upper
# length), which is pervasive rather than incidental. Pervasiveness is all this
# arm is asked to judge; a single catastrophic interpenetration is the next
# constant's job, precisely because normalizing by atom count dilutes it.
STERIC_CLASHSCORE_MAX = 10.0

# OURS, chosen because the clashscore is a DENSITY and one impossible contact is
# not dense. Two heavy atoms overlapping by 0.9 A are closer than the sum of
# their covalent radii while not being bonded — a carbon and an oxygen at 1.2 A,
# which happens when a side chain is built through the backbone. No amount of
# repacking fixes that and no correct structure contains one, so a single pair at
# or above this rejects on its own however large the design is.
STERIC_SEVERE_OVERLAP_A = 0.90

# WITHOUT HYDROGENS, EVERY HYDROGEN BOND LOOKS LIKE A CLASH. Bondi's O and N
# radii sum to 3.04-3.10 A and a real N-H...O sits at 2.7-3.0 A, so a naive
# heavy-atom criterion reports one "clash" per hydrogen bond and the resulting
# clashscore measures the secondary structure rather than the errors — a
# well-formed helix scores worse than a disordered one. Probe handles this by
# subtracting a hydrogen-bond allowance for donor-acceptor pairs (Word et al.
# 1999, J Mol Biol 285, 1711, "Visualizing and quantifying molecular
# goodness-of-fit"); 0.6 A is that allowance and is what is frozen here. Applied
# only when BOTH atoms can donate or accept, so a carbon jammed into an oxygen
# gets no relief.
STERIC_HBOND_ALLOWANCE_A = 0.60
STERIC_HBOND_CAPABLE_ELEMENTS: frozenset[str] = frozenset({"N", "O", "S"})

# Atoms in the same residue and in sequence-ADJACENT residues are bonded, or 1-3
# / 1-4 related through the peptide bond, and their close approach is geometry
# rather than error. Excluding |i - j| <= 1 by residue position in the chain is
# the coarse form of Probe's bonded-pair exclusion; it is deliberately coarser
# (it also drops genuine i, i+1 side-chain-to-side-chain contacts), because the
# alternative is a bond-graph this module has no connectivity records to build.
STERIC_SEQUENCE_SEPARATION_EXCLUDED = 1

# The one covalent bond that is NOT captured by sequence adjacency, and the one
# that would otherwise dominate the count in this campaign's designs: a
# disulfide. Two SG atoms 2.05 A apart overlap by 1.55 A on Bondi radii, which is
# a "severe" clash under the rule above — and protocol L82's Cys-parity liability
# check exists precisely because these designs carry cysteine pairs. An SG-SG
# pair inside this distance is read as bonded and excluded.
STERIC_DISULFIDE_SG_SG_MAX_A = 2.50  # S-S bond is 2.05 A; 2.5 admits strained ones

# Bondi (1964), J Phys Chem 68, 441 — the standard van der Waals radii, and the
# set MolProbity's own numbers descend from. Only the elements a protein file
# actually carries are listed; SE is here because MSE (selenomethionine) is in
# the residue whitelist this module shares with the rest of the repo.
VDW_RADII_BONDI_A: dict[str, float] = {
    "C": 1.70,
    "N": 1.55,
    "O": 1.52,
    "S": 1.80,
    "SE": 1.90,
    "P": 1.80,
    "F": 1.47,
}
# Carbon, because it is the most common protein heavy atom and the LARGEST of the
# three that make up ~97% of them (C 1.70 > S excepted, N 1.55, O 1.52) — so an
# unrecognised element is given the radius that makes a clash EASIER to declare,
# not harder. The count of atoms that needed this is reported in `measurements`;
# a structure where it is not zero is one whose element column should be looked
# at rather than trusted.
VDW_RADIUS_DEFAULT_A = 1.70

# The atoms every residue has by virtue of being a residue. Anything else is a
# side chain, and a file with NO side-chain heavy atom cannot answer the clash
# question at all — see `steric_clash_check` for why that is NOT_RUN and not a
# comfortable zero.
_BACKBONE_ATOM_NAMES: frozenset[str] = frozenset({"N", "CA", "C", "O", "OXT"})


# ── (c) core packing ───────────────────────────────────────────────────────
#
# Rg ~= 2.2 * N^0.38 Angstrom — the compact-globule (Flory) scaling for NATIVE
# folded proteins. The exponent is the compact-state 0.38, not the 0.588 of a
# self-avoiding coil, which is exactly what makes the ratio below diagnostic: an
# extended or single-helix artifact does not merely score badly against it, it
# scores against a different power law.
CORE_RG_SCALING_PREFACTOR_A = 2.2
CORE_RG_SCALING_EXPONENT = 0.38

# OURS, chosen because of what sits on either side of it. Compact single-domain
# folds land at 0.98-1.02 of the scaling; an elongated but real designed
# miniprotein (a helical hairpin, a long two-layer design) lands at 1.20-1.25;
# an ideal single continuous alpha helix of 60 residues lands at 2.4, because a
# helix's Rg grows linearly in N (rise 1.5 A/residue) against the law's N^0.38.
# 1.35 sits above every folded shape and far below the artifact class, so this
# arm rejects "this is a rod, not a protein" and declines to have an opinion
# about anything tighter.
#
# NO LOWER BOUND, deliberately. A structure BELOW the scaling is interpenetrating
# rather than merely compact, and the steric arm reads that directly off the atom
# positions instead of inferring it from a bulk statistic.
CORE_RG_MAX_RATIO = 1.35

# Neighbour count: for each residue, the number of OTHER residues whose
# representative atom (CB, or CA for glycine and for CB-less files) lies within
# this radius of its own. The classic contact-number definition; 10 A is its
# usual radius.
CORE_NEIGHBOUR_RADIUS_A = 10.0

# OURS, chosen because 14 is the smallest count an ideal single alpha helix
# CANNOT reach. At 1.5 A rise and 100 deg twist, a residue in the middle of an
# infinite helix has exactly 12 neighbours inside 10 A (i +/- 1..6) and no more,
# whatever the helix's length — so a single-helix or extended artifact scores a
# buried fraction of exactly 0.00 at this cutoff, by construction rather than by
# calibration. Compact folds of 45-120 residues put 20-60% of their residues at
# or above it. The separation is structural, not fitted.
CORE_NEIGHBOUR_COUNT_MIN = 14

# The residue itself is NOT counted as its own neighbour. Recorded as a named
# fact because it shifts every count by one and protocol L90 makes the sheet
# writer reproduce these numbers to 1e-4.
CORE_NEIGHBOUR_COUNTS_SELF = False

# OURS, chosen because the artifact class this arm targets scores exactly zero
# (see above), so the value's only job is to sit far enough above zero that one
# accidentally over-packed loop cannot clear it. At protocol L62's shortest
# permitted binder (35 residues) 0.10 is four residues; at its longest (160) it
# is sixteen. Compact folds measure 0.2-0.6, so the margin is wide in the
# direction that matters.
#
# RESIDUAL, stated rather than papered over: a design whose hydrophobic core is
# SHARED across its interface with the target — real, and common in co-designed
# heterodimer arms — can measure 0.04-0.06 standalone and is rejected here. That
# is the intended reading, not a false positive: protocol L83 already requires
# the binder to fold ON ITS OWN, and a binder with no core of its own does not.
CORE_MIN_BURIED_FRACTION = 0.10

# OURS, chosen because protocol L62 puts the permitted binder band at 35-160
# residues and the compact-globule scaling is fitted to folded domains. Below ~30
# residues there is no core to have and no fitted law to compare against, so the
# arm reports NOT_RUN rather than an opinion it cannot support.
CORE_MIN_RESIDUES = 30


# ── shared input bounds ────────────────────────────────────────────────────
#
# The clash arm is O(atoms^2). Protocol L62 caps a binder at 160 residues
# (~1,300 heavy atoms); 400 leaves generous headroom for a padded or
# multi-domain design while stopping a target ectodomain handed in by mistake
# from turning a pre-scoring pass into a multi-minute stall that then reports
# itself as a measurement. Mirrors `qa_tm_helpers.MAX_CHAIN_RESIDUES` in intent.
MAX_DESIGN_RESIDUES = 400

# Rows per block in the pairwise sweep. 400 residues is ~3,400 heavy atoms and a
# dense 3,400^2 float64 matrix is ~92 MB per intermediate — several of which the
# clash test needs at once. Blocking bounds it at a few MB and costs nothing.
_PAIR_BLOCK_ROWS = 256

# The residue whitelist the rest of the repo indexes on
# (`qa_analysis_helpers._PROTEIN_RESIDUES`, `qa_tm_helpers._PROTEIN_RESIDUES`,
# `interface.py`). MSE kept, waters / ligands / glycans dropped. Duplicated
# rather than imported for the reason `qa_tm_helpers` states: importing
# `qa_analysis_helpers` here would pull ~100k characters of module into an
# app-side import path that needs none of it.
_PROTEIN_RESIDUES = frozenset(
    {
        "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU",
        "LYS", "MET", "MSE", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    }
)  # fmt: skip

# Elements whose PDB atom names begin with two letters that must not be split.
# `SG` (cysteine sulfur) must read as S and `SE` (selenomethionine) as Se, and
# only a two-letter table can tell those apart from the first character alone.
_TWO_LETTER_ELEMENTS: frozenset[str] = frozenset({"SE"})

# Hydrogen and deuterium. Excluded from every heavy-atom computation here, and
# named so the exclusion is greppable rather than a bare string literal.
_HYDROGEN_ELEMENTS: frozenset[str] = frozenset({"H", "D"})


# ── the frozen set, as one dict ────────────────────────────────────────────
#
# Every number above, in one place, so the charter discloses the set the campaign
# froze and the sheet writer recomputes against the same set (protocol L90). The
# per-check functions take a `thresholds` mapping that is merged OVER this and
# REFUSES an unknown key — a mistyped override that silently did nothing would
# leave a campaign believing it had frozen a value it never applied.
STRUCTURAL_PLAUSIBILITY_THRESHOLDS: dict[str, Any] = {
    # (a) backbone geometry
    "ca_ca_ideal_a": BACKBONE_CA_CA_TRANS_A,
    "ca_ca_tolerance_a": BACKBONE_CA_CA_TOLERANCE_A,
    "allow_cis_peptide": BACKBONE_ALLOW_CIS_PEPTIDE,
    "ca_ca_cis_a": BACKBONE_CA_CA_CIS_A,
    "peptide_c_n_ideal_a": BACKBONE_PEPTIDE_C_N_A,
    "peptide_c_n_tolerance_a": BACKBONE_PEPTIDE_C_N_TOLERANCE_A,
    # (b) steric clashes
    "clash_overlap_a": STERIC_CLASH_OVERLAP_A,
    "clash_hbond_allowance_a": STERIC_HBOND_ALLOWANCE_A,
    "clash_severe_overlap_a": STERIC_SEVERE_OVERLAP_A,
    "clashscore_max": STERIC_CLASHSCORE_MAX,
    "clash_sequence_separation_excluded": STERIC_SEQUENCE_SEPARATION_EXCLUDED,
    "clash_disulfide_sg_sg_max_a": STERIC_DISULFIDE_SG_SG_MAX_A,
    "clashscore_normalization": STERIC_CLASHSCORE_NORMALIZATION,
    "vdw_radii": "Bondi 1964",
    # (c) core packing
    "rg_scaling_prefactor_a": CORE_RG_SCALING_PREFACTOR_A,
    "rg_scaling_exponent": CORE_RG_SCALING_EXPONENT,
    "rg_max_ratio": CORE_RG_MAX_RATIO,
    "neighbour_radius_a": CORE_NEIGHBOUR_RADIUS_A,
    "neighbour_count_core_min": CORE_NEIGHBOUR_COUNT_MIN,
    "neighbour_counts_self": CORE_NEIGHBOUR_COUNTS_SELF,
    "min_buried_fraction": CORE_MIN_BURIED_FRACTION,
    "core_min_residues": CORE_MIN_RESIDUES,
    # shared
    "backbone_min_residues": BACKBONE_MIN_RESIDUES,
    "max_design_residues": MAX_DESIGN_RESIDUES,
}

# Keys whose value is prose (a provenance stamp), not a bound. Split out so the
# numeric validation below can refuse a NaN without tripping over them.
_NON_NUMERIC_THRESHOLD_KEYS: frozenset[str] = frozenset(
    {
        "allow_cis_peptide",
        "clashscore_normalization",
        "vdw_radii",
        "neighbour_counts_self",
    }
)


def _resolve_thresholds(overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    """The frozen set with the caller's overrides merged in, or an error.

    UNKNOWN KEYS RAISE. An override the gate silently ignored is the worst of
    both worlds: the charter records a frozen threshold, the code applies a
    different one, and the sheet writer's 1e-4 recomputation reproduces the
    CODE's answer, so nothing downstream ever notices.

    NaN RAISES, and it is the dangerous one in this direction. Every comparison
    here is written as "reject when the measurement exceeds the bound", and
    ``value > nan`` is False for every value — so a NaN threshold does not reject
    the pool the way it would in ``monomer_foldability_verdicts`` (whose test is
    ``value >= floor``). It PASSES the entire pool while reporting that a gate
    ran, which is the exact failure the pre-scoring filters exist to prevent.
    """
    resolved = dict(STRUCTURAL_PLAUSIBILITY_THRESHOLDS)
    for key, value in (overrides or {}).items():
        if key not in resolved:
            raise StructurePlausibilityInputError(
                f"unknown structural-plausibility threshold {key!r}; expected one "
                f"of {', '.join(sorted(resolved))}. A threshold the gate does not "
                "recognise would be silently dropped and the campaign would "
                "believe it froze a value it never applied."
            )
        resolved[key] = value
    for key, value in resolved.items():
        if key in _NON_NUMERIC_THRESHOLD_KEYS:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StructurePlausibilityInputError(
                f"structural-plausibility threshold {key}={value!r} is not a number"
            )
        if not math.isfinite(float(value)):
            raise StructurePlausibilityInputError(
                f"structural-plausibility threshold {key}={value!r} is not finite. "
                "NaN is the dangerous one: every `measurement > nan` is False, so "
                "the gate would PASS the entire pool while reporting itself as run."
            )
    return resolved


# ── reading the structure ──────────────────────────────────────────────────


def _structure_text(pdb_text_or_path: Any) -> str:
    """PDB text, from either the text itself or a path to it.

    The same idiom as ``qa_tm_helpers._structure_text``, written out rather than
    imported for one reason: that function raises ``TmScoreError``, and a
    ``TmScoreError`` escaping a structural-plausibility call would not be caught
    by any handler here or at any call site, so an unreadable file would kill the
    pool instead of stamping one design NOT_RUN.
    """
    text = str(pdb_text_or_path or "")
    if not text.strip():
        raise StructureUnreadable("empty structure input")
    if "\n" in text or "ATOM  " in text or "HETATM" in text:
        return text
    try:
        with open(text, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as exc:
        raise StructureUnreadable(f"could not read structure {text!r}: {exc}") from exc


def _element_for(atom_name: str, raw_element: str, resname: str) -> str:
    """The atom's element, preferring the file's own column.

    Columns 77-78 hold it when the writer bothered; plenty do not, and this
    repo's PDBs come from several generations of tool. The name fallback strips
    the leading digit some writers put on hydrogens ("1HB") and consults a
    two-letter table, because taking the first character alone maps
    selenomethionine's SE onto sulfur — a 0.1 A radius error, but silent.
    """
    element = (raw_element or "").strip().upper()
    if element:
        return element
    name = (atom_name or "").strip().upper().lstrip("0123456789")
    if not name:
        return ""
    if name[:2] in _TWO_LETTER_ELEMENTS and resname.strip().upper() == "MSE":
        return name[:2]
    return name[0]


@dataclass(frozen=True)
class _ParsedChain:
    """One protein chain's residues and every heavy atom in them, in file order."""

    chain_id: str
    resnames: tuple[str, ...]
    resids: tuple[tuple[int, str], ...]
    atom_names: tuple[str, ...]
    atom_elements: tuple[str, ...]
    atom_residue_index: np.ndarray  # (A,) int, index into resnames/resids
    coords: np.ndarray  # (A, 3) float
    residue_atoms: tuple[dict[str, int], ...]  # per residue: atom name -> row in coords
    unknown_element_atoms: int

    def __len__(self) -> int:
        return len(self.resnames)

    def named(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        """``(residue_indices, coords)`` for one atom name, residues that have it."""
        rows = [
            (index, atoms[name])
            for index, atoms in enumerate(self.residue_atoms)
            if name in atoms
        ]
        if not rows:
            return np.empty(0, dtype=int), np.empty((0, 3), dtype=float)
        indices = np.asarray([row[0] for row in rows], dtype=int)
        return indices, self.coords[[row[1] for row in rows]]


def _parse_chain(pdb_text_or_path: Any, chain: Any = None) -> _ParsedChain:
    """Every heavy atom of ONE protein chain of model 1.

    Column slicing is the repo's (``qa_analysis_helpers._pdb_chain_ca_residues``,
    ``qa_tm_helpers._ca_coordinates``): name ``[12:16]``, resname ``[17:20]``,
    chain ``[21]``, resseq ``[22:26]``, icode ``[26]``, xyz ``[30:38] [38:46]
    [46:54]``, element ``[76:78]``. First model only (stops at ``ENDMDL``), first
    altloc per atom name, protein polymer residues only, hydrogens dropped.

    ``chain=None`` IS ALLOWED ONLY FOR A FILE HOLDING ONE PROTEIN CHAIN. These
    are single-chain miniproteins; a co-folded complex whose first chain happens
    to be the 200-residue target would otherwise be measured as "the design", and
    a target ectodomain passes every plausibility threshold there is — the gate
    would report itself as run, on the wrong molecule, for every design in the
    pool. Same refusal, same reason, as ``_ca_coordinates`` and
    ``monomer_plddt_from_fold_rows``.
    """
    text = _structure_text(pdb_text_or_path)
    wanted = None if chain is None else (str(chain).strip() or "_")

    # Ordered per chain so "which chains are in this file" can be answered before
    # any one of them is selected — the multi-chain refusal has to name them.
    order: dict[str, list[tuple[int, str, str]]] = {}
    atoms: dict[str, dict[tuple[int, str], dict[str, tuple[str, tuple[float, float, float]]]]] = {}
    for line in text.splitlines():
        if line.startswith("ENDMDL"):
            break
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        resname = line[17:20].strip().upper()
        if resname not in _PROTEIN_RESIDUES:
            continue
        chain_id = line[21].strip() or "_"
        atom_name = line[12:16].strip()
        element = _element_for(atom_name, line[76:78], resname)
        if element in _HYDROGEN_ELEMENTS:
            continue
        try:
            key = (int(line[22:26]), line[26].strip())
            xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        except ValueError:
            continue
        if key not in atoms.setdefault(chain_id, {}):
            atoms[chain_id][key] = {}
            order.setdefault(chain_id, []).append((key[0], key[1], resname))
        # `setdefault`, so the FIRST altloc of an atom wins — the rule
        # `_ca_coordinates` already applies. Taking the last instead would make
        # the answer depend on file ordering for no stated reason.
        atoms[chain_id][key].setdefault(atom_name, (element, xyz))

    if not atoms:
        raise StructureUnreadable(
            f"no protein atoms in chain {wanted!r}"
            if wanted
            else "no protein atoms in the structure"
        )
    if wanted is None and len(atoms) > 1:
        raise StructurePlausibilityInputError(
            f"structure holds chains {sorted(atoms)}; structural plausibility is a "
            "MONOMER gate (protocol L84 assesses the candidate, and L83 already "
            "requires it to fold alone), so name the chain rather than let the "
            "first one in the file stand in for the design. A target chain "
            "clears every threshold here."
        )
    if wanted is not None and wanted not in atoms:
        raise StructurePlausibilityInputError(
            f"chain {wanted!r} is not in the structure; it holds {sorted(atoms)}"
        )
    chain_id = wanted if wanted is not None else next(iter(atoms))

    resnames: list[str] = []
    resids: list[tuple[int, str]] = []
    atom_names: list[str] = []
    atom_elements: list[str] = []
    atom_residue_index: list[int] = []
    coords: list[tuple[float, float, float]] = []
    residue_atoms: list[dict[str, int]] = []
    unknown_elements = 0
    for resseq, icode, resname in order[chain_id]:
        index = len(resnames)
        resnames.append(resname)
        resids.append((resseq, icode))
        rows: dict[str, int] = {}
        for name, (element, xyz) in atoms[chain_id][(resseq, icode)].items():
            rows[name] = len(coords)
            atom_names.append(name)
            atom_elements.append(element)
            atom_residue_index.append(index)
            coords.append(xyz)
            if element not in VDW_RADII_BONDI_A:
                unknown_elements += 1
        residue_atoms.append(rows)

    array = np.asarray(coords, dtype=float)
    # `float("nan")` parses happily out of a truncated or corrupt PDB and a
    # non-finite coordinate propagates silently through every distance here —
    # `nan >= 0.4` is False, so a corrupt structure would report ZERO clashes and
    # PASS. Caught at the boundary, where it can still be named, exactly as
    # `_ca_coordinates` catches it.
    if array.size and not np.isfinite(array).all():
        raise StructureUnreadable(
            f"chain {chain_id} carries a non-finite coordinate (NaN or inf); the "
            "structure is corrupt. Left in place it would report zero clashes."
        )
    if len(resnames) > MAX_DESIGN_RESIDUES:
        raise StructurePlausibilityInputError(
            f"chain {chain_id} has {len(resnames)} residues, above the "
            f"{MAX_DESIGN_RESIDUES}-residue cap. Protocol L62 permits 35-160 for a "
            "binder; this is a target-sized chain and the clash sweep is O(n^2)."
        )
    return _ParsedChain(
        chain_id=chain_id,
        resnames=tuple(resnames),
        resids=tuple(resids),
        atom_names=tuple(atom_names),
        atom_elements=tuple(atom_elements),
        atom_residue_index=np.asarray(atom_residue_index, dtype=int),
        coords=array if array.size else np.empty((0, 3), dtype=float),
        residue_atoms=tuple(residue_atoms),
        unknown_element_atoms=unknown_elements,
    )


def _as_chain(structure: Any, chain: Any) -> _ParsedChain:
    """``structure`` is either an already-parsed chain or something to parse."""
    if isinstance(structure, _ParsedChain):
        return structure
    return _parse_chain(structure, chain)


def _result(
    check: str,
    verdict: str,
    *,
    reason: str | None = None,
    not_run_reason: str | None = None,
    measurements: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One sub-check's answer, in the shape all three share."""
    return {
        "check": check,
        "verdict": verdict,
        "reason": reason,
        "not_run_reason": not_run_reason,
        "measurements": dict(measurements or {}),
    }


# ── (a) backbone geometry ──────────────────────────────────────────────────


def backbone_geometry_check(
    pdb_text_or_path: Any,
    chain: Any = None,
    *,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Is this a chain, geometrically? CA-CA virtual bonds, and C-N when present.

    Measures the CA(i)-CA(i+1) distance for every consecutive pair IN FILE ORDER
    and rejects any that falls outside ``ca_ca_ideal_a +/- ca_ca_tolerance_a``.
    That single band catches both failures L84's "backbone geometry" names: a
    chain break (two segments a generator never joined, or a missing internal
    span) reads as a distance of many Angstrom, and a squashed or impossible link
    reads as one far below 3.80.

    CONSECUTIVE MEANS CONSECUTIVE IN THE FILE, NOT IN THE NUMBERING, and the
    choice matters in both directions. Renumbering is routine — a design written
    with its target's offsets has a numbering jump and a perfectly good backbone
    — so treating a numbering gap as a break by itself would reject on
    bookkeeping. Conversely a genuinely missing internal segment shows up as a
    long CA-CA whether or not the numbers admit it. So the geometry decides, and
    the numbering discontinuities are REPORTED beside it
    (``residue_numbering_gaps``) so a reviewer can tell "this design is broken"
    from "this file is renumbered".

    The peptide C(i)-N(i+1) bond is checked too whenever both atoms are in the
    file, and skipped per pair when either is missing — a CA trace answers the
    first arm and simply has no second arm to answer, which is reported as
    ``peptide_bonds_measured = 0`` rather than as a pass.

    Verdict: REJECT on any out-of-band bond; NOT_RUN below
    ``backbone_min_residues`` (there is no consecutive pair to measure, which is
    not the same as every bond being fine); PASS otherwise.
    """
    limits = _resolve_thresholds(thresholds)
    parsed = _as_chain(pdb_text_or_path, chain)

    ca_index, ca = parsed.named("CA")
    if len(ca) < int(limits["backbone_min_residues"]):
        return _result(
            CHECK_BACKBONE_GEOMETRY,
            VERDICT_NOT_RUN,
            not_run_reason=(
                f"chain {parsed.chain_id} carries {len(ca)} CA atom(s); "
                f"{limits['backbone_min_residues']} are needed for a consecutive "
                "pair to exist"
            ),
            measurements={"ca_atoms": len(ca), "chain": parsed.chain_id},
        )

    ideal = float(limits["ca_ca_ideal_a"])
    tolerance = float(limits["ca_ca_tolerance_a"])
    low, high = ideal - tolerance, ideal + tolerance
    distances = np.linalg.norm(np.diff(ca, axis=0), axis=1)

    # The cis band, when a campaign opted into it. Two admitted intervals rather
    # than one widened one, so the gap between them — where a distorted or
    # mis-modelled link lands — stays closed.
    cis_low = cis_high = None
    if bool(limits["allow_cis_peptide"]):
        cis = float(limits["ca_ca_cis_a"])
        cis_low, cis_high = cis - tolerance, cis + tolerance

    def admitted(value: float) -> bool:
        if low <= value <= high:
            return True
        return cis_low is not None and cis_low <= value <= cis_high

    offenders: list[dict[str, Any]] = []
    for position, value in enumerate(distances):
        if admitted(float(value)):
            continue
        left, right = int(ca_index[position]), int(ca_index[position + 1])
        offenders.append(
            {
                "kind": "ca_ca",
                "from": _label(parsed, left),
                "to": _label(parsed, right),
                "distance_a": round(float(value), 4),
                "band_a": [round(low, 4), round(high, 4)],
            }
        )

    peptide_measured = 0
    peptide_distances: list[float] = []
    c_n_ideal = float(limits["peptide_c_n_ideal_a"])
    c_n_tolerance = float(limits["peptide_c_n_tolerance_a"])
    for position in range(len(ca_index) - 1):
        left, right = int(ca_index[position]), int(ca_index[position + 1])
        carbon = parsed.residue_atoms[left].get("C")
        nitrogen = parsed.residue_atoms[right].get("N")
        if carbon is None or nitrogen is None:
            continue
        peptide_measured += 1
        bond = float(np.linalg.norm(parsed.coords[carbon] - parsed.coords[nitrogen]))
        peptide_distances.append(bond)
        if abs(bond - c_n_ideal) > c_n_tolerance:
            offenders.append(
                {
                    "kind": "peptide_c_n",
                    "from": _label(parsed, left),
                    "to": _label(parsed, right),
                    "distance_a": round(bond, 4),
                    "band_a": [
                        round(c_n_ideal - c_n_tolerance, 4),
                        round(c_n_ideal + c_n_tolerance, 4),
                    ],
                }
            )

    numbering_gaps = [
        f"{_label(parsed, int(ca_index[position]))}->{_label(parsed, int(ca_index[position + 1]))}"
        for position in range(len(ca_index) - 1)
        if parsed.resids[int(ca_index[position + 1])][0]
        - parsed.resids[int(ca_index[position])][0]
        != 1
    ]

    measurements: dict[str, Any] = {
        "chain": parsed.chain_id,
        "residues": len(parsed),
        "ca_ca_bonds_measured": len(distances),
        "ca_ca_min_a": round(float(distances.min()), 4),
        "ca_ca_max_a": round(float(distances.max()), 4),
        "ca_ca_mean_a": round(float(distances.mean()), 4),
        "ca_ca_out_of_band": sum(1 for o in offenders if o["kind"] == "ca_ca"),
        "peptide_bonds_measured": peptide_measured,
        "peptide_c_n_min_a": (
            round(min(peptide_distances), 4) if peptide_distances else None
        ),
        "peptide_c_n_max_a": (
            round(max(peptide_distances), 4) if peptide_distances else None
        ),
        "peptide_c_n_out_of_band": sum(
            1 for o in offenders if o["kind"] == "peptide_c_n"
        ),
        "residue_numbering_gaps": numbering_gaps,
        "offenders": offenders,
    }
    if not offenders:
        return _result(CHECK_BACKBONE_GEOMETRY, VERDICT_PASS, measurements=measurements)
    worst = max(offenders, key=lambda o: abs(o["distance_a"] - ideal))
    return _result(
        CHECK_BACKBONE_GEOMETRY,
        VERDICT_REJECT,
        reason=(
            f"backbone geometry REJECT: {len(offenders)} bond(s) outside the frozen "
            f"band, worst {worst['kind']} {worst['from']}->{worst['to']} at "
            f"{worst['distance_a']} A (band {worst['band_a'][0]}-{worst['band_a'][1]} A"
            + (
                ""
                if bool(limits["allow_cis_peptide"])
                else "; cis peptides are not admitted, see BACKBONE_ALLOW_CIS_PEPTIDE"
            )
            + ")"
        ),
        measurements=measurements,
    )


def _label(parsed: _ParsedChain, index: int) -> str:
    """``ALA12`` / ``ALA12A`` — a residue a reviewer can find in the file."""
    resseq, icode = parsed.resids[index]
    return f"{parsed.resnames[index]}{resseq}{icode}"


# ── (b) steric clashes ─────────────────────────────────────────────────────


def steric_clash_check(
    pdb_text_or_path: Any,
    chain: Any = None,
    *,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """MolProbity-style heavy-atom clashes, and the clashscore they make.

    A clash is a non-bonded pair whose van der Waals surfaces overlap by at least
    ``clash_overlap_a`` (0.40 A, MolProbity's own definition), on Bondi radii.
    Excluded from the sweep: hydrogens, atoms in the same residue, atoms in
    sequence-adjacent residues (bonded or 1-3 / 1-4 related), and SG-SG pairs
    inside disulfide distance. Donor-acceptor pairs get Probe's hydrogen-bond
    allowance, WITHOUT WHICH THE SCORE MEASURES SECONDARY STRUCTURE — see
    ``STERIC_HBOND_ALLOWANCE_A``.

    Two independent rejections, because they catch different things:
      * ``clashscore`` above ``clashscore_max`` — packing that is pervasively
        wrong, judged as a density per 1000 heavy atoms;
      * ANY single pair at or above ``clash_severe_overlap_a`` — one physically
        impossible contact, which a density normalised by atom count dilutes to
        nothing in a large design.

    NOT_RUN WHEN THE FILE HAS NO SIDE-CHAIN HEAVY ATOM, and this is the part that
    must not be a pass. A CA trace or an N/CA/C/O backbone out of a de novo
    generator has nothing to clash: it will report zero clashes and a clashscore
    of 0.0, which is indistinguishable from a beautifully packed structure and is
    a statement about the FILE rather than the design. Side chains are where
    clashes live, so their absence is a hole in the measurement.

    RESIDUAL, stated: an all-glycine chain has no side-chain atom either and is
    reported NOT_RUN. There is no way to tell "designed poly-Gly" from "side
    chains were never written" from the coordinates, and of the two readings only
    NOT_RUN is safe.
    """
    limits = _resolve_thresholds(thresholds)
    parsed = _as_chain(pdb_text_or_path, chain)

    heavy_atoms = len(parsed.coords)
    side_chain_atoms = sum(
        1 for name in parsed.atom_names if name.upper() not in _BACKBONE_ATOM_NAMES
    )
    base: dict[str, Any] = {
        "chain": parsed.chain_id,
        "residues": len(parsed),
        "heavy_atoms": heavy_atoms,
        "side_chain_heavy_atoms": side_chain_atoms,
        "unknown_element_atoms": parsed.unknown_element_atoms,
        "clashscore_normalization": limits["clashscore_normalization"],
    }
    if heavy_atoms == 0 or side_chain_atoms == 0:
        return _result(
            CHECK_STERIC_CLASHES,
            VERDICT_NOT_RUN,
            not_run_reason=(
                f"chain {parsed.chain_id} carries no side-chain heavy atom "
                f"({heavy_atoms} heavy atom(s), all backbone). A backbone-only or "
                "CA-only model has nothing to clash, so a clashscore of 0.0 here "
                "would describe the file and not the design."
            ),
            measurements=base,
        )

    radii = np.asarray(
        [VDW_RADII_BONDI_A.get(element, VDW_RADIUS_DEFAULT_A) for element in parsed.atom_elements],
        dtype=float,
    )
    polar = np.asarray(
        [element in STERIC_HBOND_CAPABLE_ELEMENTS for element in parsed.atom_elements],
        dtype=bool,
    )
    is_sg = np.asarray(
        [name.upper() == "SG" for name in parsed.atom_names], dtype=bool
    )
    residue_index = parsed.atom_residue_index

    overlap_at = float(limits["clash_overlap_a"])
    allowance_a = float(limits["clash_hbond_allowance_a"])
    severe_at = float(limits["clash_severe_overlap_a"])
    separation = int(limits["clash_sequence_separation_excluded"])
    disulfide_max = float(limits["clash_disulfide_sg_sg_max_a"])

    clashes: list[dict[str, Any]] = []
    worst_effective = float("-inf")
    columns = np.arange(heavy_atoms)
    for start in range(0, heavy_atoms, _PAIR_BLOCK_ROWS):
        stop = min(start + _PAIR_BLOCK_ROWS, heavy_atoms)
        block = parsed.coords[start:stop]
        distance = np.linalg.norm(block[:, None, :] - parsed.coords[None, :, :], axis=-1)
        overlap = (radii[start:stop, None] + radii[None, :]) - distance
        allowance = np.where(
            polar[start:stop, None] & polar[None, :], allowance_a, 0.0
        )
        effective = overlap - allowance
        rows = np.arange(start, stop)[:, None]
        considered = (
            (columns[None, :] > rows)
            & (
                np.abs(residue_index[start:stop, None] - residue_index[None, :])
                > separation
            )
            & ~(
                is_sg[start:stop, None]
                & is_sg[None, :]
                & (distance <= disulfide_max)
            )
        )
        if considered.any():
            worst_effective = max(
                worst_effective, float(effective[considered].max())
            )
        for row, column in np.argwhere(considered & (effective >= overlap_at)):
            left, right = start + int(row), int(column)
            clashes.append(
                {
                    "atoms": [
                        f"{_label(parsed, int(residue_index[left]))}:{parsed.atom_names[left]}",
                        f"{_label(parsed, int(residue_index[right]))}:{parsed.atom_names[right]}",
                    ],
                    "distance_a": round(float(distance[row, column]), 4),
                    "overlap_a": round(float(overlap[row, column]), 4),
                    "effective_overlap_a": round(float(effective[row, column]), 4),
                }
            )

    # The normalization is NOT a threshold and is deliberately not overridable:
    # "per 1000 atoms" is what the word clashscore MEANS (Chen et al. 2010), and a
    # campaign that could re-base it would be reporting a number under a name that
    # no longer describes it — while the ceiling above stayed the same.
    clashscore = STERIC_CLASHSCORE_PER_ATOMS * len(clashes) / heavy_atoms
    severe = [c for c in clashes if c["effective_overlap_a"] >= severe_at]
    measurements = dict(base)
    measurements.update(
        {
            "clashes": len(clashes),
            "clashscore": round(clashscore, 4),
            "severe_clashes": len(severe),
            "max_effective_overlap_a": (
                round(worst_effective, 4) if math.isfinite(worst_effective) else None
            ),
            "clash_pairs": clashes,
        }
    )

    ceiling = float(limits["clashscore_max"])
    reasons: list[str] = []
    if severe:
        deepest = max(severe, key=lambda c: c["effective_overlap_a"])
        reasons.append(
            f"{len(severe)} severe overlap(s) at or above {severe_at} A, worst "
            f"{deepest['atoms'][0]} -- {deepest['atoms'][1]} overlapping by "
            f"{deepest['effective_overlap_a']} A at {deepest['distance_a']} A"
        )
    if clashscore > ceiling:
        reasons.append(
            f"clashscore {round(clashscore, 4)} above the frozen ceiling {ceiling} "
            f"({len(clashes)} clash(es) over {heavy_atoms} heavy atoms)"
        )
    if reasons:
        return _result(
            CHECK_STERIC_CLASHES,
            VERDICT_REJECT,
            reason="steric clashes REJECT: " + "; ".join(reasons),
            measurements=measurements,
        )
    return _result(CHECK_STERIC_CLASHES, VERDICT_PASS, measurements=measurements)


# ── (c) core packing ───────────────────────────────────────────────────────


def core_packing_check(
    pdb_text_or_path: Any,
    chain: Any = None,
    *,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Does this design have a core? Radius of gyration, and buried-residue count.

    Two independent criteria, either of which rejects:

      * ``rg_ratio`` — the CA radius of gyration over the compact-globule
        expectation ``2.2 * N^0.38 A``. Above ``rg_max_ratio`` the design is a
        rod or a coil, not a folded miniprotein: a single continuous alpha helix
        grows Rg linearly in N against the law's N^0.38 and lands near 2.4 by 60
        residues.
      * ``buried_fraction`` — the fraction of residues with at least
        ``neighbour_count_core_min`` other residues inside ``neighbour_radius_a``
        of their representative atom (CB; CA for glycine and for a file with no
        CB at all). Below ``min_buried_fraction`` the design has no hydrophobic
        core, which is the other way to be an implausible fold while having
        perfectly reasonable bond lengths.

    WHICH ATOM WAS COUNTED IS REPORTED (``neighbour_atom``), because a CB-based
    and a CA-based count are not the same measurement and protocol L90 makes the
    sheet writer reproduce this number to 1e-4. They agree closely in practice —
    the 1.53 A CB offset moves individual residues between the two sides of the
    cutoff without moving the population much — but "closely" is not "identically"
    and a recomputation that guessed the atom would drift.

    NOT_RUN below ``core_min_residues``: the scaling law is fitted to folded
    domains and a 20-residue peptide has no core to have, so there is no honest
    verdict to give.
    """
    limits = _resolve_thresholds(thresholds)
    parsed = _as_chain(pdb_text_or_path, chain)

    _ca_index, ca = parsed.named("CA")
    minimum = int(limits["core_min_residues"])
    if len(ca) < minimum:
        return _result(
            CHECK_CORE_PACKING,
            VERDICT_NOT_RUN,
            not_run_reason=(
                f"chain {parsed.chain_id} has {len(ca)} residue(s) with a CA, below "
                f"the {minimum}-residue floor. The compact-globule scaling is "
                "fitted to folded domains and a shorter chain has no core to have."
            ),
            measurements={
                "chain": parsed.chain_id,
                "residues_with_ca": len(ca),
            },
        )

    length = len(ca)
    rg = float(np.sqrt(((ca - ca.mean(axis=0)) ** 2).sum(axis=1).mean()))
    expected = float(limits["rg_scaling_prefactor_a"]) * (
        length ** float(limits["rg_scaling_exponent"])
    )
    rg_ratio = rg / expected

    # CB where the file has one, CA otherwise. Glycine has no CB by chemistry and
    # a backbone-only file has none by omission; both fall back to CA, and the
    # stamp below says which case dominated so the number can be reproduced.
    cb_present = sum(1 for atoms in parsed.residue_atoms if "CB" in atoms)
    representative_rows = [
        atoms.get("CB", atoms["CA"]) for atoms in parsed.residue_atoms if "CA" in atoms
    ]
    representative = parsed.coords[representative_rows]
    neighbour_atom = "CB (CA where absent)" if cb_present else "CA"

    radius = float(limits["neighbour_radius_a"])
    core_min = float(limits["neighbour_count_core_min"])
    counts = np.zeros(len(representative), dtype=int)
    for start in range(0, len(representative), _PAIR_BLOCK_ROWS):
        stop = min(start + _PAIR_BLOCK_ROWS, len(representative))
        block = representative[start:stop]
        distance = np.linalg.norm(
            block[:, None, :] - representative[None, :, :], axis=-1
        )
        within = distance <= radius
        # The residue is never its own neighbour (`CORE_NEIGHBOUR_COUNTS_SELF`);
        # the diagonal of this block is at column `start + row`.
        within[np.arange(stop - start), np.arange(start, stop)] = False
        counts[start:stop] = within.sum(axis=1)
    buried = int((counts >= core_min).sum())
    buried_fraction = buried / len(representative)

    measurements: dict[str, Any] = {
        "chain": parsed.chain_id,
        "residues": length,
        "radius_of_gyration_a": round(rg, 4),
        "radius_of_gyration_expected_a": round(expected, 4),
        "rg_ratio": round(rg_ratio, 4),
        "neighbour_atom": neighbour_atom,
        "residues_with_cb": cb_present,
        "neighbour_count_max": int(counts.max()) if len(counts) else 0,
        "neighbour_count_median": float(np.median(counts)) if len(counts) else 0.0,
        "buried_residues": buried,
        "buried_fraction": round(buried_fraction, 4),
    }

    ratio_ceiling = float(limits["rg_max_ratio"])
    fraction_floor = float(limits["min_buried_fraction"])
    reasons: list[str] = []
    if rg_ratio > ratio_ceiling:
        reasons.append(
            f"radius of gyration {round(rg, 4)} A is {round(rg_ratio, 4)}x the "
            f"compact-globule expectation {round(expected, 4)} A for {length} "
            f"residues (ceiling {ratio_ceiling}) — this is an extended or "
            "single-helix shape, not a folded miniprotein"
        )
    if buried_fraction < fraction_floor:
        reasons.append(
            f"buried fraction {round(buried_fraction, 4)} is below the frozen "
            f"floor {fraction_floor} ({buried} of {len(representative)} residues "
            f"have >= {int(core_min)} neighbours within {radius} A of their "
            f"{neighbour_atom}) — the design has no hydrophobic core"
        )
    if reasons:
        return _result(
            CHECK_CORE_PACKING,
            VERDICT_REJECT,
            reason="core packing REJECT: " + "; ".join(reasons),
            measurements=measurements,
        )
    return _result(CHECK_CORE_PACKING, VERDICT_PASS, measurements=measurements)


# ── one design ─────────────────────────────────────────────────────────────


def structural_plausibility_verdict(
    pdb_text_or_path: Any,
    chain: Any = None,
    *,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """L84 for one design: all three sub-checks, and the rule that combines them.

    THE COMBINATION RULE, and why it is this one:

      REJECT   any sub-check REJECTed. A definite reject is definite even when
               another sub-check could not run — a design with a chain break is
               broken whether or not it also carried side chains to test for
               clashes. This is the same precedence
               ``qa_tm_helpers.target_mimic_screen`` uses ("Definitive, and
               reported even when other chains could not be screened").
      NOT_RUN  nothing REJECTed but some sub-check could not run. The design is
               NOT cleared. Protocol L79 requires the candidate to be ASSESSED
               before scoring, and a partial assessment is not one; folding this
               into PASS is precisely how a gate reports itself as run while
               filtering nothing.
      PASS     all three ran and all three passed.

    The structure is parsed ONCE and the parse handed to all three sub-checks, so
    the three cannot disagree about which chain they measured — and so a
    multi-chain refusal happens once, at the boundary, rather than three times
    from inside three different handlers.

    FAILS OPEN AS NOT_RUN, NEVER AS A SILENT PASS: an empty input, an unreadable
    path, or a corrupt structure returns NOT_RUN for all three with the reason
    attached. It does NOT fail open on a multi-chain file — that raises, because
    it is the wrong molecule rather than a missing one (see
    :class:`StructurePlausibilityInputError`).
    """
    limits = _resolve_thresholds(thresholds)
    try:
        parsed = _as_chain(pdb_text_or_path, chain)
    except StructureUnreadable as exc:
        blank = {
            name: _result(name, VERDICT_NOT_RUN, not_run_reason=str(exc))
            for name in STRUCTURAL_PLAUSIBILITY_CHECKS
        }
        return {
            "gate": PRESCORING_GATE_STRUCTURAL_PLAUSIBILITY,
            "verdict": VERDICT_NOT_RUN,
            "reason": None,
            "not_run_reason": str(exc),
            "checks": blank,
            "measurements": {},
            "thresholds": limits,
        }

    checks = {
        CHECK_BACKBONE_GEOMETRY: backbone_geometry_check(parsed, thresholds=limits),
        CHECK_STERIC_CLASHES: steric_clash_check(parsed, thresholds=limits),
        CHECK_CORE_PACKING: core_packing_check(parsed, thresholds=limits),
    }

    # Flat and dotted, not nested: the sheet writer recomputes this gate and
    # matches to 1e-4 (protocol L90), and a flat map of scalar keys is what a
    # row-versus-row comparison can walk. The list-valued detail (offenders,
    # clash pairs) stays inside `checks` where a human reads it.
    measurements: dict[str, Any] = {}
    for name, result in checks.items():
        for key, value in result["measurements"].items():
            if isinstance(value, (list, tuple, dict)):
                continue
            measurements[f"{name}.{key}"] = value

    rejects = [name for name, r in checks.items() if r["verdict"] == VERDICT_REJECT]
    not_run = [name for name, r in checks.items() if r["verdict"] == VERDICT_NOT_RUN]
    not_run_reason = (
        "; ".join(
            f"{name}: {checks[name]['not_run_reason']}" for name in not_run
        )
        or None
    )
    if rejects:
        return {
            "gate": PRESCORING_GATE_STRUCTURAL_PLAUSIBILITY,
            "verdict": VERDICT_REJECT,
            "reason": " | ".join(str(checks[name]["reason"]) for name in rejects),
            "not_run_reason": not_run_reason,
            "checks": checks,
            "measurements": measurements,
            "thresholds": limits,
        }
    return {
        "gate": PRESCORING_GATE_STRUCTURAL_PLAUSIBILITY,
        "verdict": VERDICT_NOT_RUN if not_run else VERDICT_PASS,
        "reason": None,
        "not_run_reason": not_run_reason,
        "checks": checks,
        "measurements": measurements,
        "thresholds": limits,
    }


# ── the pool ───────────────────────────────────────────────────────────────


def _structure_spec(raw: Any) -> tuple[Any, Any]:
    """``(structure, chain)`` from a value, a ``(pdb, chain)`` pair, or a mapping.

    Mirrors ``qa_tm_helpers._reference_spec``'s tolerance of the three shapes a
    caller naturally has, so a pool keyed by design id can name a chain per
    design without a second parallel mapping to keep in step.
    """
    if isinstance(raw, Mapping):
        return raw.get("pdb", raw.get("structure")), raw.get("chain")
    if isinstance(raw, (str, bytes)):
        return raw, None
    if isinstance(raw, Sequence) and len(raw) == 2:
        return raw[0], raw[1]
    return raw, None


def structural_plausibility_verdicts(
    structures_by_design_id: Mapping[Any, Any],
    *,
    chain: Any = None,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run L84 over a pool. Same shape as ``monomer_foldability_verdicts``.

    Values may be PDB text, a path, a ``(pdb, chain)`` pair, or a mapping with
    ``pdb``/``chain``; ``chain=`` sets the default for entries that name none.

    ``rejected`` is the list protocol L86 needs — "a gate counts as run only when
    its rejects are traceably absent downstream" — and
    :func:`structural_plausibility_rejects` turns this whole dict into the
    traceable records ``prescoring_gate_pool_violations`` consumes.

    AN UNREADABLE STRUCTURE IS THAT DESIGN'S NOT_RUN; A MULTI-CHAIN ONE RAISES.
    The asymmetry is deliberate and matches ``monomer_foldability_verdicts``,
    which likewise lets its input error escape: one missing file is a per-design
    hole and must not stop the other designs being screened, while a caller
    handing complexes to a monomer gate is a wiring error that affects every
    design in the pool and would otherwise be reported as 20,000 quiet NOT_RUNs.
    """
    limits = _resolve_thresholds(thresholds)
    verdicts: dict[str, str] = {}
    reasons: dict[str, str] = {}
    not_run_reasons: dict[str, str] = {}
    measurements: dict[str, Any] = {}
    for raw_id, raw_structure in structures_by_design_id.items():
        # Mirrors `monomer_foldability_verdicts`' id normalization, including its
        # refusal to let `str(raw or "")` swallow the integer 0.
        design_id = "" if raw_id is None else str(raw_id).strip()
        if not design_id or design_id in verdicts:
            continue
        structure, per_design_chain = _structure_spec(raw_structure)
        outcome = structural_plausibility_verdict(
            structure,
            per_design_chain if per_design_chain is not None else chain,
            thresholds=limits,
        )
        verdicts[design_id] = str(outcome["verdict"])
        measurements[design_id] = dict(outcome["measurements"])
        if outcome["verdict"] == VERDICT_REJECT:
            reasons[design_id] = str(outcome["reason"])
        if outcome["not_run_reason"]:
            not_run_reasons[design_id] = str(outcome["not_run_reason"])
    return {
        "verdicts": verdicts,
        "passed": [d for d, v in verdicts.items() if v == VERDICT_PASS],
        "rejected": [d for d, v in verdicts.items() if v == VERDICT_REJECT],
        "not_run": [d for d, v in verdicts.items() if v == VERDICT_NOT_RUN],
        "reasons": reasons,
        "not_run_reasons": not_run_reasons,
        "thresholds": limits,
        "measurements": measurements,
    }


def structural_plausibility_rejects(
    outcome: Mapping[str, Any],
) -> list[PrescoringReject]:
    """:func:`structural_plausibility_verdicts` output -> the L86 reject records."""
    return rejects_from_verdicts(
        outcome.get("verdicts") or {},
        PRESCORING_GATE_STRUCTURAL_PLAUSIBILITY,
        reasons=outcome.get("reasons") or {},
        measurements=outcome.get("measurements") or {},
    )


def structural_plausibility_gate_stamp() -> str:
    """One line naming what ran and the bands it ran with, for a charter row."""
    return (
        "STRUCTURAL_PLAUSIBILITY(protocol L84; backbone CA-CA "
        f"{BACKBONE_CA_CA_TRANS_A}+/-{BACKBONE_CA_CA_TOLERANCE_A} A, cis "
        f"{'allowed' if BACKBONE_ALLOW_CIS_PEPTIDE else 'disallowed'}; clashes "
        f">= {STERIC_CLASH_OVERLAP_A} A overlap on Bondi 1964 radii, clashscore "
        f"<= {STERIC_CLASHSCORE_MAX} per 1000 heavy atoms, no single overlap "
        f">= {STERIC_SEVERE_OVERLAP_A} A; Rg <= {CORE_RG_MAX_RATIO}x "
        f"{CORE_RG_SCALING_PREFACTOR_A}*N^{CORE_RG_SCALING_EXPONENT} A, buried "
        f"fraction >= {CORE_MIN_BURIED_FRACTION} at >= {CORE_NEIGHBOUR_COUNT_MIN} "
        f"neighbours within {CORE_NEIGHBOUR_RADIUS_A} A)"
    )


_SURVIVED_FIELD = (
    "structural_plausibility REJECTs the pool kept (protocol L86: a gate counts "
    "as run only when its rejects are traceably absent downstream)"
)


def structural_plausibility_offenders(rows: Iterable[Any]) -> dict[str, list[str]]:
    """Surviving-pool rows this gate should have removed. Offenders by field.

    The companion to ``screen_gate_metrics.monomer_gate_pool_violations`` for
    L84, and the same shape (``dict[str, list[str]]``) so it feeds
    ``qa._describe_offenders`` unchanged. Empty — so nothing halts — when the
    pool carries no structural-plausibility columns at all, which is a legitimate
    NOT_RUN; what it catches is the pool that DID carry them and kept the rows
    they condemn.
    """
    offenders: dict[str, list[str]] = {}
    for index, row in enumerate(rows or []):
        if not isinstance(row, Mapping):
            continue
        design_id = str(row.get("design_id") or f"row_{index + 1}")
        verdict = str(row.get("structural_plausibility") or "").strip().upper()
        if verdict == VERDICT_REJECT:
            offenders.setdefault(_SURVIVED_FIELD, []).append(design_id)
    return offenders
