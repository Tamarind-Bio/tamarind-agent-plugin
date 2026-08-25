#!/usr/bin/env python3
"""Score, cap, rank and recompute the final design panel -- the deliverable.

Three things happen here, in this order, and the order is load-bearing:

1. THE GATE. Production scoring is blocked until the validation check on
   known-answer controls has PASSED. This script refuses to emit a panel
   without that artifact. On the campaign harness the refusal lives in the
   scoring-batch builder; here it lives in this script, which is why the panel
   must be produced by running it rather than by assembling rows by hand.
2. THE ALGEBRA. final_score is the RAW mean of the realized terms; rank_zscore
   is the 4:1-weighted z-average of the same terms; z-scores are transductive,
   so they are comparable only within this batch. A term an arm did not produce
   is None -- never 0, never averaged in.
3. THE CAPS, then the RECOMPUTE. Selection applies the diversity caps and the
   relaxation ladder (one rung per call), then every gate that ran is recomputed
   from the row's own sequence and structure and matched to 1e-4. A mismatch
   HALTS, naming the row, because a row whose gates cannot be reproduced is not
   a row you can ship.

Formulas come from the vendored kernel (_kernel/VENDORED.md), never from here.

Usage:
  python3 select_panel.py candidates.json --gate gate.json --out design_sheet.csv
  python3 select_panel.py candidates.json --gate gate.json --panel-size 30 --json
  python3 select_panel.py candidates.json --gate gate.json --max-relaxation-rung 2

`candidates.json` is a list of rows carrying design_id, sequence, provenance
(root_backbone_id, parent_design_id, opt_round, structure_method, seq_method),
the per-arm term columns, and the gate evidence written by campaign_gates.py.
`--gate` is the validation-check artifact; its `status` must be PASS or
PASS_REDUCED.
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GATE_OK = ("PASS", "PASS_REDUCED")
IPSAE_PREFIX = "ipsae_"
SCDOCKQ_PREFIX = "sc_DockQ_"

# Columns that share a score prefix but carry provenance, not a measurement.
# `ipsae_mask` is the one that bites: every scored row is REQUIRED to carry it,
# it is a string, and swept into the algebra it parses to None and makes the
# whole row ineligible -- so a correctly-stamped campaign scores nothing.
# Suffix-matched as well, so a future `*_tool` / `*_job` / `*_path` stamp under
# either prefix cannot silently become a seventh term.
NON_TERM_SUFFIXES = ("_mask", "_stamp", "_tool", "_job", "_path", "_reason", "_status")

# The residue alphabet a shipped sequence must be drawn from, in full. A value
# outside it is refused rather than salvaged: the kernel's normalizer strips
# punctuation and digits, so `results/design1.pdb` would otherwise survive as
# `RESULTSDESIGNPDB` and ship as a protein.
AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWYXBZJUO")

# The campaign's outer length bounds -- 50-120 nominal, 35-160 under the
# motivated exception. A 200-residue chain accidentally joined as the binder is
# syntactically valid protein and would otherwise rank. The >25%-away-from-the-
# target-chain mimic band is NOT checkable here: it needs the frozen construct's
# chain length, which is campaign state this script does not hold. The skill
# owns that half.
BINDER_LEN_MIN, BINDER_LEN_MAX = 35, 160

# "at least 3 distinct structure_methods" is stated as an absolute, and the
# relaxation ladder explicitly may not go under it. It does not scale with the
# panel size the caller asked for.
ABSOLUTE_STRUCTURE_METHOD_FLOOR = 3

# pose_dockq is the MIN over the arms that ran, and pose_PASS is that value
# against the frozen threshold. Both are derived here rather than trusted,
# because pose_PASS sits AHEAD of rank_zscore in the rank key: one stale or
# hand-authored TRUE sorts a pose-failing design above every honest row, and
# corrupts cap admission order on the way.
POSE_THRESHOLD_DEFAULT = 0.23


def _verify_companion(panel, path, ipsae_names, tolerance=1e-4):
    """Check the ranked rows against the per-seed companion.

    The failure this catches is an aggregate term cell that is STALE or joined to
    the WRONG design while staying numeric -- recomputing the score from that
    same cell cannot see it, which is why the check has to come from a different
    artifact.

    Two things are verified. COVERAGE: every ranked design_id appears, and no
    (design, arm) group is uniformly null on the ranking metric. VALUE: each
    row's per-arm ipSAE aggregate equals the MAX over that design-and-arm's seed
    rows, which is the frozen aggregation rule and one operation, not a
    re-derivation of the score.
    """
    with open(path, newline="") as fh:
        companion = list(csv.DictReader(fh))
    if not companion:
        return {"ran": False, "reason": f"{path} is empty"}

    fields = set(companion[0])
    for required in ("design_id", "arm"):
        if required not in fields:
            return {"ran": False, "reason": f"{path} has no {required!r} column"}
    metric = next(
        (c for c in ("ipsae_min", "ipsae", "ipSAE_min", "ipSAE") if c in fields), None
    )

    per_group = {}
    for entry in companion:
        key = (str(entry.get("design_id")), str(entry.get("arm")).strip())
        per_group.setdefault(key, []).append(_num(entry.get(metric)) if metric else None)

    seen = {design for design, _ in per_group}
    missing = [str(r.get("design_id")) for r in panel if str(r.get("design_id")) not in seen]
    uniformly_null = [
        f"{design}/{arm}" for (design, arm), values in per_group.items()
        if metric and all(v is None for v in values)
    ]

    mismatches = []
    if metric:
        for row in panel:
            design = str(row.get("design_id"))
            for name in ipsae_names:
                arm = name[len(IPSAE_PREFIX):]
                values = [v for v in per_group.get((design, arm), []) if v is not None]
                carried = _num(row.get(name))
                if not values or carried is None:
                    continue
                if abs(max(values) - carried) > tolerance:
                    mismatches.append(
                        f"{design}/{arm}: sheet {carried:.6f} vs companion max {max(values):.6f}"
                    )
    return {
        "ran": True,
        "metric_column": metric,
        "rows": len(companion),
        "missing_from_companion": missing,
        "uniformly_null_groups": uniformly_null,
        "value_mismatches": mismatches,
    }


def _load_rows(path):
    with open(path) as fh:
        if path.lower().endswith(".csv"):
            return list(csv.DictReader(fh))
        data = json.load(fh)
    for key in ("candidates", "designs", "rows", "items"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    if isinstance(data, list):
        return data
    raise SystemExit(f"{path}: expected a list of candidate rows")


def _check_gate(path):
    """Fail closed. No artifact, or a non-PASS one, and nothing is emitted."""
    if not path:
        raise SystemExit(
            "refusing to build a panel: --gate is required.\n"
            "The validation check on known-answer controls must PASS before any\n"
            "production scoring row is ranked. Run it, write the verdict, then retry."
        )
    if not os.path.exists(path):
        raise SystemExit(f"refusing to build a panel: gate artifact not found at {path}")
    with open(path) as fh:
        gate = json.load(fh)
    status = str(gate.get("status") or "").strip().upper()
    if status not in GATE_OK:
        raise SystemExit(
            f"refusing to build a panel: gate status is {status or 'MISSING'}, not PASS.\n"
            "This is the check that the scoring separates known binders from non-binders\n"
            "on this target. Do not edit the artifact to get past this."
        )
    # A bare {"status": "PASS"} is a word, not a verdict. The artifact has to
    # carry what was measured and what it was measured on, or a truncated or
    # hand-authored file unlocks ranking with no auditable evidence that the
    # scoring was ever validated.
    if _num(gate.get("separation")) is None:
        raise SystemExit(
            "refusing to build a panel: the gate artifact carries no numeric `separation`.\n"
            "PASS has to say what separated the controls, not merely that something did."
        )
    controls = gate.get("controls") or []
    if not isinstance(controls, (list, tuple)) or len(controls) < 2:
        raise SystemExit(
            "refusing to build a panel: the gate artifact names fewer than two `controls`.\n"
            "The check needs a positive control and at least one negative; a target-self-pair\n"
            "control belongs there too, since it is what falsifies target-mimic inflation."
        )
    return gate


def _num(value):
    # `bool` is a subclass of `int`, so float(True) is 1.0 -- a fabricated
    # perfect interface score that would promote a malformed row to the top of
    # the panel. Reject it explicitly, as the vendored numeric helper does.
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


# Verdict columns a row may carry from the pre-scoring gates. A REJECT here is a
# gate that already refused the design; the selector enforces only the
# target-mimic ban, so without this a rejected design with a good score ranks.
GATE_VERDICT_COLUMNS = (
    "liability_verdict",
    "novelty_verdict",
    "structural_plausibility_verdict",
    "monomer_foldability_verdict",
    "target_mimic_verdict",
)


RECOGNIZED_VERDICTS = ("PASS", "REJECT", "NOT_RUN")


def _bad_gate_verdicts(row):
    """Reason this row's gate verdicts do not clear it for ranking, or None.

    Refusing only the literal REJECT would let a row that never carried the
    column at all through -- and an absent verdict is indistinguishable
    downstream from a gate that ran and passed. Absence is not a pass, the same
    rule the kernel already applies to the target-mimic verdict.
    """
    for column in GATE_VERDICT_COLUMNS:
        verdict = str(row.get(column) or "").strip().upper()
        if not verdict:
            return f"{column} is absent: a gate with no verdict is not a gate that passed"
        if verdict not in RECOGNIZED_VERDICTS:
            return f"{column} is {verdict!r}, which is not one of {'/'.join(RECOGNIZED_VERDICTS)}"
        if verdict == "REJECT":
            return f"{column} is REJECT: a gate already refused this design"
    return None


def _mismatch_id(entry):
    """The design id inside one recompute mismatch.

    The kernel declares `mismatches` as a list of design-id STRINGS
    (`_kernel/sheet_recompute.py`), so reading it as a mapping raised
    AttributeError and crashed the very halt this id is printed by -- the
    operator got a traceback instead of the row and the gate. Accept both
    shapes so a widened kernel contract cannot resurrect that failure.
    """
    if isinstance(entry, dict):
        return str(entry.get("design_id") or entry.get("id") or entry)
    return str(entry)


def _folded_chains(value):
    """The chains of the construct a scoring job actually folded.

    A complex is submitted as one joined value -- `TARGET:BINDER` on the FASTA
    route this skill recommends -- and comes back from the platform that way.
    A monomer fold yields the single chain. Both separators in use are
    accepted, since the generation tables join with `/` and the scoring
    submissions with `:`.
    """
    joined = str(value).replace("/", ":")
    return [c.strip().upper() for c in joined.split(":") if c.strip()]


def _canonical_method(value):
    """Fold a method token to its canonical form.

    `rfdiffusion3`, `RFdiffusion3` and `rfdiffusion-3` are ONE tool. Counted raw
    they are three distinct structure methods, so a single generator satisfies
    the three-method floor and slips its per-method cap. The plan freezes a
    closed one-token-per-tool vocabulary; this is the mechanical half of that.
    """
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _bad_seed_count(row):
    """Reason this row's seed depth is unusable, or None.

    The rank key's first term is "full seed tier", so a missing count coerced to
    0 silently reads as a deliberately shallow result. A row that ships a
    headline score has to be able to say how deep the instrument ran.
    """
    raw = row.get("n_seeds")
    if raw is None or str(raw).strip() == "":
        return "n_seeds is absent: a ranked row cannot disclose its seed depth"
    try:
        seeds = int(str(raw).strip())
    except ValueError:
        return f"n_seeds {raw!r} is not a whole number"
    if seeds < 0:
        return f"n_seeds {seeds} is negative"
    return None


def _term_matrix(rows, prefix):
    """`[design][term]` -- the orientation the kernel's algebra requires.

    NOT `[arm][design]`. The kernel validates only that the matrix is
    rectangular, so a transposed input with as many arms as designs is accepted
    and silently scores every design against the wrong terms. Build it per
    design, in one stable arm order, and never by zipping columns.

    Only real per-arm metric columns count as terms; see NON_TERM_SUFFIXES.
    """
    names = sorted(
        k
        for k in {k for r in rows for k in r}
        if k.startswith(prefix) and not k.endswith(NON_TERM_SUFFIXES)
    )
    return names, [[_num(row.get(n)) for n in names] for row in rows]


def _bad_sequence(value):
    """Reason this is not a protein sequence, or None if it is one."""
    seq = "" if value is None else str(value).strip().upper()
    if not seq:
        return "empty sequence"
    offenders = sorted({ch for ch in seq if ch not in AMINO_ACIDS})
    if offenders:
        return f"non-residue characters {''.join(offenders)!r} in sequence"
    if not BINDER_LEN_MIN <= len(seq) <= BINDER_LEN_MAX:
        return (
            f"binder_len {len(seq)} is outside the frozen policy "
            f"({BINDER_LEN_MIN}-{BINDER_LEN_MAX} even under the motivated exception)"
        )
    return None


def _bad_lineage(row):
    """Reason this row's optimization lineage does not close, or None.

    The per-root cap is counted on `root_backbone_id`, so a child that mints a
    fresh root escapes it while looking like ordinary provenance. Round 0 is de
    novo and cannot claim a parent.
    """
    raw = row.get("opt_round")
    if raw is None or str(raw).strip() == "":
        return "opt_round is blank (round 0 is de novo, and it still has to say so)"
    try:
        rnd = int(str(raw).strip())
    except ValueError:
        return f"opt_round {raw!r} is not a whole number"
    if rnd < 0:
        return f"opt_round {rnd} is negative"
    parent = str(row.get("parent_design_id") or "").strip()
    if rnd == 0 and parent:
        return "a round-0 design claims a parent, but round 0 is de novo"
    if rnd > 0 and not parent:
        return f"opt_round {rnd} carries no parent_design_id"
    if parent and parent == str(row.get("design_id") or "").strip():
        return "design is its own parent"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidates")
    ap.add_argument("--gate", help="validation-check artifact; status must be PASS")
    ap.add_argument("--panel-size", type=int, default=30)
    ap.add_argument("--max-relaxation-rung", type=int, default=1)
    ap.add_argument("--monomer-floor", type=float, default=0.70,
                    help="frozen binder-alone mean-pLDDT floor, on the scale the arm emits")
    ap.add_argument("--out", help="write the design sheet here")
    ap.add_argument("--trace", help="write the cap/rejection/relaxation trace here")
    ap.add_argument("--allow-campaign-failure", action="store_true",
                    help="write the sheet even when the panel is below the structure-method floor; for inspection only, never to ship")
    ap.add_argument("--companion",
                    help="per_seed_metrics.csv; verifies coverage and that each per-arm\naggregate is the max over that design and arm's seed rows")
    ap.add_argument("--pose-threshold", type=float, default=POSE_THRESHOLD_DEFAULT,
                    help="frozen pose_dockq threshold; pose_PASS is derived, never trusted")
    ap.add_argument("--allow-reduced-instrument", action="store_true",
                    help="rank without the pose limb; a DISCLOSED reduction that must be\nreported on every row and in the deliverable")
    ap.add_argument("--skip-recompute", action="store_true",
                    help="emit the panel without the write-time gate recompute; DISCLOSE this")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    gate = _check_gate(args.gate)
    rows = _load_rows(args.candidates)
    if not rows:
        raise SystemExit("no candidate rows")

    try:
        from _kernel import qa_analysis_helpers as helpers
        from _kernel import qa_selection_helpers as selection
    except ImportError as exc:
        raise SystemExit(f"vendored kernel unavailable: {exc}")

    # DID THE SCORES COME FROM THIS ROW'S SEQUENCE?
    #
    # Nothing else on this page can tell. Every gate recomputes against the
    # row's own sequence, so a row whose SCORES belong to a different molecule
    # reproduces perfectly and ranks on numbers that are not its own.
    #
    # This is not hypothetical. Building a scoring submission by hand-copying
    # sequences into it produced, in one small real run: one row whose id named
    # design n1 while the job folded n0, and one row whose submitted sequence
    # matched NO design in any result table -- it shared a prefix with a real
    # design and then diverged. The platform accepted both, folded them, and
    # returned entirely plausible confidence numbers.
    #
    # So carry `scored_sequence` -- the sequence the scoring job actually
    # received, read back from the platform, not from the notes you submitted
    # from -- and check it here.
    # The scoring construct is a COMPLEX. The recommended route folds a FASTA
    # record holding the joined `TARGET:BINDER` value, so the stored input read
    # back from the platform carries BOTH chains while the row's `sequence` is
    # the binder alone. Compare against the CHAINS of what was folded, not
    # against the whole construct: plain equality refuses every correctly
    # scored complex, turning this halt on the good case.
    scored = [
        r for r in rows
        if str(r.get("scored_sequence") or "").strip() and str(r.get("sequence") or "").strip()
    ]
    mismatched = [
        r for r in scored
        if str(r.get("sequence")).strip().upper() not in _folded_chains(r["scored_sequence"])
    ]
    if mismatched:
        lines = []
        for r in mismatched[:5]:
            folded = _folded_chains(r["scored_sequence"])
            lines.append(
                f"  {r.get('design_id')}: row carries {len(str(r.get('sequence') or ''))} aa, "
                f"the scoring job folded {'+'.join(str(len(c)) for c in folded)} aa"
            )
        raise SystemExit(
            f"HALTED: {len(mismatched)} row(s) carry a sequence that is not among the "
            "chains the scoring job folded:\n" + "\n".join(lines) + "\n"
            "  These rows rank on numbers that belong to another molecule, and every "
            "gate still reproduces\n"
            "  because the gates read the row's own sequence. Rebuild the scoring "
            "pool by threading the\n"
            "  sequence programmatically from the generation table -- never by "
            "transcribing it."
        )
    if rows and not scored:
        print(
            "  WARNING: no row carries scored_sequence, so nothing verifies that these "
            "scores came from\n"
            "  these designs. A row scored on another molecule ranks normally and "
            "reproduces every gate.",
            file=sys.stderr,
        )
    elif scored and len(scored) < len(rows):
        # Partial coverage is MORE suspicious than none: the read-back ran, and
        # these rows escaped it. A non-empty `scored` silenced the warning
        # above, so an unverified row shipped with no disclosure at all.
        # Identity, not equality: `r not in scored` compares dicts by VALUE, so
        # two rows that happen to be equal would mask each other.
        checked = {id(r) for r in scored}
        missing = sorted(
            str(r.get("design_id")) for r in rows if id(r) not in checked
        )
        print(
            f"  WARNING: {len(missing)} of {len(rows)} row(s) carry no scored_sequence, "
            "so nothing verifies\n"
            f"  that their scores came from their designs: {', '.join(missing[:5])}"
            + (" ..." if len(missing) > 5 else "") + "\n"
            "  The other rows were checked. These were not, and a row scored on "
            "another molecule ranks\n"
            "  normally and reproduces every gate.",
            file=sys.stderr,
        )

    # A repeated design_id is a WHOLE-RUN refusal, not a per-row unranking:
    # nothing here can tell which row is the real one, and the caps, the
    # rejects ledger and the trace all address rows by that id. The kernel
    # catches it too, but only as a bare ValueError escaping mid-selection --
    # every other refusal on this path is a clean paragraph, so raise it here
    # in the same shape campaign_gates.py already uses one stage earlier.
    # Compare ids the way the KERNEL compares them -- it stringifies before
    # its own duplicate check, so a pool carrying numeric 1 beside string "1"
    # walked past a raw-value set here and hit `ValueError: duplicate
    # design_id '1'` inside selection: a bare traceback from the one path this
    # refusal exists to keep clean. Reproduced, not reasoned about.
    seen_ids, duplicated = set(), []
    for row in rows:
        did = row.get("design_id") or row.get("id")
        if did is None:
            continue
        did = str(did).strip()
        if did in seen_ids:
            duplicated.append(did)
        seen_ids.add(did)
    if duplicated:
        shown = ", ".join(sorted(set(duplicated))[:5])
        raise SystemExit(
            f"refusing to build a panel: duplicate design_id {shown}.\n"
            "  Design ids address rows in the caps, the rejects ledger and the "
            "trace, so a repeated one makes all three ambiguous.\n"
            "  This usually means two pools were concatenated, or a "
            "sequence-design pass minted a second id space over the same "
            "backbones."
        )

    # The arms do NOT agree on the pLDDT scale. Measured on real rows for the
    # same construct: ESMFold2 reports 0-1 (0.7884) and Protenix 0-100 (86.75).
    # Against a 0-1 floor a 0-100 value clears for EVERY design -- the
    # foldability gate stops rejecting anything while still reporting PASS on
    # every row. That is a vacuous gate, which is worse than an absent one, so
    # refuse rather than rescale: only the campaign knows which arm produced
    # the column.
    #
    # This is a comparison of two numbers and needs NOTHING from the kernel, so
    # it runs HERE rather than beside the recompute. Sited there it was inside
    # `if sr is not None`, which is False on exactly the stock machine with no
    # numpy that SKILL.md calls the common case -- the guard was absent from
    # every run that most needed it, and the sheet shipped with the mismatch
    # disclosed only as a skipped recompute.
    _plddt = [
        (str(r.get("design_id")), _num(r.get("monomer_plddt")))
        for r in rows
    ]
    on_0_100 = sorted(did for did, v in _plddt if v is not None and v > 1.0)
    on_0_1 = sorted(did for did, v in _plddt if v is not None and v <= 1.0)
    if on_0_100 and args.monomer_floor <= 1.0:
        raise SystemExit(
            f"HALTED: monomer_plddt exceeds 1.0 on {len(on_0_100)} row(s) while "
            f"--monomer-floor is {args.monomer_floor} (a 0-1 scale).\n"
            f"  first: {', '.join(on_0_100[:5])}\n"
            "  The arms disagree on this scale -- ESMFold2 reports pLDDT on "
            "0-1 and Protenix on 0-100.\n"
            "  Against a 0-1 floor a 0-100 value passes for every design, so "
            "the foldability gate\n"
            "  would report PASS on every row while rejecting nothing. Put the "
            "column and the floor on\n"
            "  the same scale in the pool, and record which arm's convention "
            "the frozen floor is in."
        )
    # The same disagreement the other way round -- but this direction is an
    # INFERENCE and the one above is not, so it does not get the same trigger.
    #
    # A value above 1.0 is IMPOSSIBLE on a 0-1 scale, so one of them proves a
    # units mismatch. The reverse is not proof: a value at or below 1.0 is
    # merely astonishing on a 0-100 scale, not impossible, and aborting the run
    # over one catastrophic prediction would refuse a correctly declared
    # campaign instead of letting the monomer gate reject that row -- the same
    # false-positive mode this script declined a mixed-scale detector over.
    # So demand unanimity: EVERY value under 1.0 against a 0-100 floor is a
    # units mismatch, one of them is a bad design.
    #
    # Worth checking at all because the loud failure only happens when the
    # comparison runs. Under `--skip-recompute`, or with no numpy, nothing
    # recomputes the floor and the rows ship on carried verdicts with the
    # declared floor never reconciled against the column at all.
    if on_0_1 and not on_0_100 and args.monomer_floor > 1.0:
        raise SystemExit(
            f"HALTED: every monomer_plddt in this pool is at or below 1.0 "
            f"({len(on_0_1)} row(s)) while --monomer-floor is "
            f"{args.monomer_floor} (a 0-100 scale).\n"
            f"  first: {', '.join(on_0_1[:5])}\n"
            "  The arms disagree on this scale -- ESMFold2 reports pLDDT on "
            "0-1 and Protenix on 0-100.\n"
            "  Against a 0-100 floor a 0-1 value fails for every design, so the "
            "foldability gate would\n"
            "  reject the whole pool on its units. Put the column and the floor "
            "on the same scale in the\n"
            "  pool, and record which arm's convention the frozen floor is in."
        )

    # ── ELIGIBILITY FIRST, THEN THE ALGEBRA ─────────────────────────────────
    # rank_zscore is TRANSDUCTIVE: the mean and spread come from the scored
    # pool. A row that will be dropped for a bad sequence, broken lineage or a
    # carried REJECT must not be in that population, or it moves the z-scores of
    # every row that does ship. So the row-intrinsic checks -- none of which
    # need a score -- run before the algebra, not after it.
    eligible, unranked = [], []
    for row in rows:
        reason = (
            _bad_sequence(row.get("sequence"))
            or _bad_lineage(row)
            or _bad_gate_verdicts(row)
            or _bad_seed_count(row)
        )
        if reason:
            row["unranked_reason"] = reason
            unranked.append(row)
        else:
            eligible.append(row)

    # Which columns exist is a property of the POOL's schema, so read the term
    # names off every row -- otherwise a pool whose rows are all ineligible
    # reports "no ipsae columns" and hides the real reason they were dropped.
    # The VALUES, and therefore the transductive statistics, come from the
    # eligible rows only.
    ipsae_names, _ = _term_matrix(rows, IPSAE_PREFIX)
    dockq_names, _ = _term_matrix(rows, SCDOCKQ_PREFIX)
    if not ipsae_names:
        raise SystemExit(
            f"no {IPSAE_PREFIX}* columns on the candidate rows: there is nothing to rank.\n"
            "Every co-folding stage runs all three arms; a pool with no interface-confidence\n"
            "terms has not been scored."
        )
    # rank_zscore is per-target and transductive, so two targets' artifacts
    # concatenated into one file would pool their means and variances and rank
    # against each other. Mixing is fatal. A pool where NO row names a target is
    # a different, softer problem -- nothing can be mixed if nothing is
    # labelled -- so that is reported rather than refused.
    targets = {str(r.get("target") or "").strip() for r in eligible}
    named = {name for name in targets if name}
    if len(named) > 1:
        raise SystemExit(
            "refusing to score: eligible rows name more than one target "
            f"({', '.join(sorted(named))}).\n"
            "rank_zscore is per-target and transductive -- pooling two targets changes every\n"
            "z-score and lets one target's designs enter the other's panel. Split the file."
        )
    if named and len(targets) > len(named):
        raise SystemExit(
            f"refusing to score: some eligible rows name target {named.pop()!r} and others "
            "name none.\nA partially-labelled pool cannot be shown to be single-target."
        )

    ipsae_terms = [[_num(r.get(n)) for n in ipsae_names] for r in eligible]
    dockq_terms = [[_num(r.get(n)) for n in dockq_names] for r in eligible]

    # An instrument that lost its whole self-consistency limb still ranks
    # happily on interface confidence alone. The protocol treats that as an
    # explicit reduction to be disclosed, not a smaller version of the same
    # measurement: every remaining term is a confidence estimate from the same
    # co-folder family, so a design whose arms agree on a WRONG pose stops being
    # caught. Require it to be named rather than discovered.
    if not dockq_names and not args.allow_reduced_instrument:
        raise SystemExit(
            "refusing to rank: no sc_DockQ_* column on any candidate, so the pose limb "
            "did not run.\n"
            "That limb is the instrument's only geometric check. Ranking without it is a\n"
            "DISCLOSED REDUCTION, not a complete score -- pass --allow-reduced-instrument\n"
            "and report the consequence on every row and in the deliverable."
        )

    realized = list(ipsae_names) + list(dockq_names)
    if eligible:
        final = helpers.final_score_from_terms(ipsae_terms, dockq_terms)
        rank_z = helpers.rank_zscore_from_terms(ipsae_terms, dockq_terms)
        for row, fs, rz in zip(eligible, final, rank_z):
            row["final_score"] = fs
            row["rank_zscore"] = rz
            row["score_instrument"] = ",".join(realized)

    # Now the score-dependent refusals. final_score non-null is never relaxed,
    # and a null rank_zscore -- which the algebra returns when a term is
    # constant across the pool, or fewer than two rows are eligible -- means the
    # ranking metric is UNDEFINED for that row. Ranking it anyway would order it
    # by file position while the sheet claims it was ranked on the instrument.
    # A term with no spread has an undefined z-score, and the weighted average
    # is None for EVERY row as a result -- not just the offending one. Unranking
    # them all would empty the panel and report "no candidate survived", which
    # names the symptom and hides the cause. Halt on the cause instead.
    if eligible and all(row.get("rank_zscore") is None for row in eligible):
        flat = [
            (name, [_num(r.get(name)) for r in eligible])
            for name in realized
        ]
        constant = [
            name for name, values in flat
            if len({v for v in values if v is not None}) == 1
        ]
        raise SystemExit(
            "refusing to rank: rank_zscore is undefined for every eligible row.\n"
            + (f"  constant across the pool: {', '.join(constant)}\n" if constant else "")
            + f"  eligible rows: {len(eligible)}\n"
            "A term with no spread has no z-score, and the weighted average inherits that\n"
            "for the whole pool. Widen the pool or drop the degenerate term and re-score --\n"
            "do not rank on an instrument that cannot separate these designs."
        )

    ranked = []
    for row in eligible:
        if row.get("final_score") is None:
            row["unranked_reason"] = "final_score is null: a realized term is missing or unparseable"
            unranked.append(row)
        elif row.get("rank_zscore") is None:
            row["unranked_reason"] = (
                "rank_zscore is undefined: a realized term is constant across the pool, "
                "or fewer than two rows are eligible"
            )
            unranked.append(row)
        else:
            ranked.append(row)

    # The sheet's column names and the selector's input names differ in one
    # place: the sheet writes `tm90_cluster_id`, the selector reads `tm_cluster`.
    # Alias rather than rename, so the shipped sheet keeps the protocol's column
    # name and the selector still sees the cluster. A row with neither is
    # refused as missing provenance -- absence of a cluster is not a pass.
    for row in ranked:
        row["structure_method"] = _canonical_method(row.get("structure_method"))
        row["seq_method"] = _canonical_method(row.get("seq_method"))
        if not row.get("tm_cluster") and row.get("tm90_cluster_id"):
            row["tm_cluster"] = row["tm90_cluster_id"]

    # Rank key: full seed tier first, then pose pass, then rank z-score. A pose
    # term that is NOT_RUN on every row is a constant and sorts as one -- it is
    # never coerced to true or false.
    def key(row):
        seeds = _num(row.get("n_seeds"))
        seeds = 0.0 if seeds is None else seeds
        pose = str(row.get("pose_PASS") or "").strip().upper()
        pose_rank = 1 if pose == "TRUE" else 0
        z = _num(row.get("rank_zscore"))
        # A z-score of exactly 0.0 is a real value; `or` would demote it to the
        # bottom alongside rows that have no score at all.
        z = float("-inf") if z is None else z
        return (-(1 if seeds >= 5 else 0), -pose_rank, -z)

    # Derive the pose verdict from the realized terms. A row missing ANY arm's
    # term carries NOT_RUN rather than a min over what is left -- two arms of
    # three read systematically HIGHER than three, so a partial min turns a
    # missing check into a passing one.
    pose_conflicts = []
    for row in ranked:
        terms = [_num(row.get(name)) for name in dockq_names]
        carried = str(row.get("pose_PASS") or "").strip().upper()
        if not dockq_names or any(term is None for term in terms):
            row["pose_dockq"] = "NOT_RUN"
            row["pose_PASS"] = "NOT_RUN"
            if carried in ("TRUE", "FALSE"):
                pose_conflicts.append(
                    f"{row.get('design_id')}: carries pose_PASS={carried} but "
                    "at least one arm's sc_DockQ term did not run"
                )
            continue
        pose_dockq = min(terms)
        derived = "TRUE" if pose_dockq >= args.pose_threshold else "FALSE"
        if carried and carried != derived:
            pose_conflicts.append(
                f"{row.get('design_id')}: carries pose_PASS={carried}, "
                f"but min over arms is {pose_dockq:.4f} -> {derived}"
            )
        row["pose_dockq"] = pose_dockq
        row["pose_PASS"] = derived
    if pose_conflicts:
        raise SystemExit(
            "HALTED: carried pose verdicts disagree with the realized sc_DockQ terms:\n  "
            + "\n  ".join(pose_conflicts[:5])
            + "\nThe sheet must not report a pose value no scoring run measured."
        )

    # Sort BEFORE the caps, not after. The selector admits greedily in input
    # order, so an unsorted pool lets a low-scoring row consume a cap that a
    # better row then cannot use -- and sorting the finished panel cannot
    # recover a candidate the caps already excluded.
    ranked.sort(key=key)

    result = selection.select_with_diversity_caps(
        ranked, panel_size=args.panel_size, max_relaxation_rung=args.max_relaxation_rung
    )
    panel = result.get("selected") or result.get("panel") or []
    panel = sorted(panel, key=key)
    for i, row in enumerate(panel, 1):
        row["rank"] = i

    recompute = {"ran": False, "gates": {}, "skipped": []}
    if not args.skip_recompute and panel:
        try:
            from _kernel import sheet_recompute as sr
        except ImportError as exc:
            # sheet_recompute pulls in structure_plausibility, which needs numpy.
            # Degrade to a named, disclosed skip rather than crashing the run or
            # forcing the caller to discover --skip-recompute.
            recompute = {
                "ran": False,
                "gates": {},
                "skipped": [f"every gate: {exc}"],
                "reason": "recompute unavailable in this environment",
            }
            sr = None
        if sr is not None:
            reports = {"liability": sr.liability_recompute(panel)}

            # Plausibility reproduces only where the row names the structure it
            # was measured on and the chain within it. Rows that name neither
            # are recorded as not-recomputable, never as reproduced.
            structures = {
                str(r.get("design_id")): r.get("designed_structure_path")
                for r in panel
                if r.get("designed_structure_path")
            }
            chains = {
                str(r.get("design_id")): r.get("binder_chain")
                for r in panel
                if r.get("binder_chain")
            }
            if structures and chains:
                try:
                    reports["plausibility"] = sr.plausibility_recompute(
                        panel, structures, chain_by_design_id=chains
                    )
                except Exception as exc:
                    recompute["skipped"].append(f"plausibility: {exc}")
            else:
                recompute["skipped"].append(
                    "plausibility: no row names both a designed structure and its binder chain"
                )

            # Monomer foldability reproduces against the per-design pLDDT the
            # binder-alone fold produced. Absent that column there is nothing to
            # check against, which is a disclosed skip and not a pass.
            plddt = {
                str(r.get("design_id")): _num(r.get("monomer_plddt"))
                for r in panel
                if _num(r.get("monomer_plddt")) is not None
            }
            if plddt:
                try:
                    reports["monomer"] = sr.monomer_recompute(
                        panel, plddt, floor=args.monomer_floor
                    )
                except Exception as exc:
                    recompute["skipped"].append(f"monomer: {exc}")
            else:
                recompute["skipped"].append("monomer: no row carries monomer_plddt")

            # Novelty needs the known-binder corpus and the reference chains,
            # which are deployment inputs the campaign stages out of band.
            recompute["skipped"].append(
                "novelty: needs the known-binder corpus and reference chains, "
                "which are campaign deployment inputs rather than sheet columns"
            )

            recompute["ran"] = True
            # `recomputed` is the list of GATE NAMES the report covered, not a
            # row count -- read rows_checked for that.
            recompute["gates"] = {
                name: {
                    "rows_checked": rep.get("rows_checked") or 0,
                    "not_recomputable": len(rep.get("not_recomputable") or []),
                    "mismatches": len(rep.get("mismatches") or []),
                }
                for name, rep in reports.items()
            }
            # A recompute that checked nothing is not a recompute that passed.
            # Without this the summary reads "ran" on a panel carrying no
            # evidence at all, which is the shape every gate in this campaign is
            # supposed to make impossible.
            recompute["vacuous"] = sorted(
                name for name, tally in recompute["gates"].items()
                if not tally["rows_checked"]
            )
            failed = {
                name: rep.get("mismatches") or []
                for name, rep in reports.items()
                if rep.get("mismatches")
            }
            if failed:
                lines = []
                for name, rows_bad in failed.items():
                    ids = ", ".join(_mismatch_id(m) for m in rows_bad[:5])
                    lines.append(f"  {name}: {len(rows_bad)} row(s) (first: {ids})")
                raise SystemExit(
                    "HALTED: carried gate numbers do not reproduce from the row's own "
                    "sequence and structure to 1e-4:\n"
                    + "\n".join(lines)
                    + "\nDo not ship a row whose gates you could not reproduce."
                )

    # The >=N-distinct-structure-methods floor is ABSOLUTE: §7 caps the
    # relaxation ladder at "never fewer than 3 distinct structure_methods", so a
    # panel below it is not shippable at any rung.
    #
    # Gate on that floor specifically, NOT on the kernel's `campaign_failure`
    # flag, which is composite: it is set for any panel that could not be filled
    # to the requested size, including one shortened by the Levenshtein or
    # cluster caps while still carrying enough methods. Refusing on the flag
    # would block the case the protocol explicitly sanctions -- "if even that
    # cannot reach the panel size, ship the actual N; padding with duplicates is
    # forbidden". A short panel ships, loudly; an under-method one does not.
    distinct = result.get("distinct_structure_methods")
    # The kernel scales its floor down for a small panel, so --panel-size 1 or 2
    # would clear a one-method panel and report no failure. The campaign's floor
    # is an absolute 3; take the stricter of the two so a small panel size
    # cannot buy its way under it.
    floor = result.get("min_structure_methods")
    if isinstance(floor, int):
        floor = max(floor, ABSOLUTE_STRUCTURE_METHOD_FLOOR)
    if (
        panel
        and isinstance(distinct, int)
        and isinstance(floor, int)
        and distinct < floor
        and not args.allow_campaign_failure
    ):
        raise SystemExit(
            f"refusing to write the sheet: the panel carries {distinct} distinct "
            f"structure method(s), and the floor is {floor}.\n"
            "That floor is absolute -- no rung of the relaxation ladder goes below it -- so\n"
            "the repair is upstream: more designs from more methods. Re-run with\n"
            "--allow-campaign-failure only to inspect the partial selection, never to ship it."
        )

    # ── #3847121418: check the sheet against a DIFFERENT artifact ──────────
    # Recomputing a row's score from its own cells cannot catch a cell that is
    # stale or misjoined but still numeric. Only the companion can.
    companion = {"ran": False, "reason": "no --companion supplied"}
    if args.companion:
        companion = _verify_companion(panel, args.companion, ipsae_names)
        problems = []
        if companion.get("missing_from_companion"):
            problems.append(
                f"{len(companion['missing_from_companion'])} ranked design(s) absent from the "
                f"companion: {', '.join(companion['missing_from_companion'][:5])}"
            )
        if companion.get("uniformly_null_groups"):
            problems.append(
                f"{len(companion['uniformly_null_groups'])} (design, arm) group(s) uniformly "
                f"null: {', '.join(companion['uniformly_null_groups'][:5])}"
            )
        if companion.get("value_mismatches"):
            problems.append(
                f"{len(companion['value_mismatches'])} term(s) disagree with the companion: "
                f"{'; '.join(companion['value_mismatches'][:3])}"
            )
        if problems:
            raise SystemExit(
                "HALTED: the sheet does not agree with the per-seed companion:\n  "
                + "\n  ".join(problems)
                + "\nCompanion coverage is 100% by contract; regenerate it rather than "
                "shipping rows it cannot corroborate."
            )

    # An empty panel is not a successful run. Exiting 0 while silently not
    # creating --out leaves a pipeline to fail later on a missing file, and the
    # summary would name a design_sheet that does not exist.
    if not panel:
        detail = ", ".join(
            f"{cap}={n}" for cap, n in sorted(
                (result.get("rejection_counts") or {}).items(), key=lambda kv: -kv[1]
            )
        )
        # The row-intrinsic checks (bad sequence, broken lineage, absent
        # verdict, unusable n_seeds) drop a row BEFORE selection, so they never
        # reach `rejection_counts`. A pool emptied entirely that way printed a
        # refusal naming no reason at all -- on precisely the run where the
        # operator has nothing else to go on. Name both populations: the caps
        # are one repair, the malformed rows are a different one.
        why = ", ".join(sorted({r["unranked_reason"] for r in unranked}))
        raise SystemExit(
            "refusing to report success: no candidate survived to the panel.\n"
            f"  {len(rows)} candidate(s) in, {len(unranked)} unranked, "
            f"{len(ranked)} reached selection.\n"
            + (f"  rejected by: {detail}\n" if detail else "")
            + (f"  unranked because: {why}\n" if why else "")
            + "Nothing was written. Fix the pool upstream rather than shipping an empty sheet."
        )

    if args.out:
        cols, seen = [], set()
        for r in panel:
            for k in r:
                if k not in seen:
                    seen.add(k)
                    cols.append(k)
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(panel)
    if args.trace:
        with open(args.trace, "w") as fh:
            json.dump({k: v for k, v in result.items() if k != "panel"}, fh, indent=2, default=str)

    # Why rows did not make it matters more than the count. A panel emptied by
    # `missing tm_cluster` is a pipeline gap; one emptied by the diversity caps
    # is an under-diverse pool. They have opposite repairs.
    summary = {
        "gate_status": gate.get("status"),
        "candidates": len(rows),
        "unranked": len(unranked),
        "unranked_reasons": sorted({r["unranked_reason"] for r in unranked}),
        "panel_size_requested": args.panel_size,
        "panel_size_shipped": len(panel),
        "short_of_request": max(0, args.panel_size - len(panel)),
        "realized_terms": realized,
        "rejection_counts": result.get("rejection_counts") or {},
        "target_mimic_not_run": len(result.get("target_mimic_not_run") or []),
        "distinct_structure_methods": result.get("distinct_structure_methods"),
        "campaign_failure": bool(result.get("campaign_failure")),
        "relaxations_applied": result.get("relaxations_applied") or [],
        "relaxation_rung": result.get("relaxation_rung"),
        "recompute": recompute,
        "companion": companion,
        "design_sheet": args.out,
    }
    if args.json:
        json.dump(summary, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print(f"gate {summary['gate_status']}; {len(rows)} candidates -> {len(panel)} shipped")
        print(f"  realized terms: {', '.join(realized) or 'none'}")
        for reason in summary["unranked_reasons"]:
            print(f"  unranked: {reason}")
        for cap, n in sorted(summary["rejection_counts"].items(), key=lambda kv: -kv[1]):
            print(f"  rejected by {cap}: {n}")
        if summary["target_mimic_not_run"]:
            print(f"  {summary['target_mimic_not_run']} row(s) carry NO mimic verdict - absence is not a pass")
        if summary["relaxations_applied"]:
            print(f"  relaxed: {', '.join(summary['relaxations_applied'])} - disclose every one")
        if summary["short_of_request"]:
            print(f"  SHORT by {summary['short_of_request']} - fix upstream; ship the real N, never pad")
        if recompute["ran"]:
            for name, tally in recompute["gates"].items():
                note = "  <- checked NOTHING; not a pass" if not tally["rows_checked"] else ""
                print(
                    f"  recomputed {name}: {tally['rows_checked']} row(s), "
                    f"{tally['mismatches']} mismatch(es), "
                    f"{tally['not_recomputable']} not recomputable{note}"
                )
        else:
            print("  gate recompute: SKIPPED - disclose this")
        if companion.get("ran"):
            print(f"  companion: {companion['rows']} row(s) corroborate the sheet "
                  f"on {companion.get('metric_column')}")
        else:
            print(f"  companion NOT checked - {companion.get('reason')}; "
                  "scores are not independently corroborated")
        for skip in recompute.get("skipped") or []:
            print(f"  not recomputed - {skip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
