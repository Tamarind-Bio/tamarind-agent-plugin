#!/usr/bin/env python3
"""Run the pre-scoring gates over a design pool, before any co-folding spend.

What runs HERE, on the host, at zero co-folding cost: liability (composition
entropy, hydrophobic patches, homopolymer runs, cysteine parity), structural
plausibility (backbone geometry, steric clashes, core packing), the target-mimic
screen (TM-score against every target and control chain), and fold class for the
diversity target.

Novelty runs here too, and most of it needs no job at all. Protocol L81 is four
arms over five subject sets, and three of them are local: the campaign's own
target and control chains, and ubiquitin -- which the kernel screens by local
alignment because it "often emerges with short terminal extensions" and so is
invisible to an exact match. Only the UniRef90 limb needs a search, and that one
is a Tamarind job whose hits are handed back via `--uniref90-hits`.

The combination rule is the kernel's, not this script's: any arm tripping on any
subject is REJECT even when another subject set could not be screened -- a proven
copy is a copy whether or not UniRef90 was staged. Clean-but-incomplete is
NOT_RUN, never PASS, and the reason names the missing set.

One mandatory gate still CANNOT run here, and this script says so on every row
rather than leaving the column absent: monomer foldability needs a binder-alone
fold, which is a Tamarind job. An absent column reads downstream exactly like a
gate that ran and found nothing.

Every gate emits its own NUMBERS, not just a verdict, because the sheet writer
recomputes each one and matches to 1e-4 -- a verdict with no numbers beside it
is unfalsifiable. A gate that could not run emits NOT_RUN with empty evidence
cells, never a zero and never a plausible-looking number.

The formulas come from the vendored kernel (see _kernel/VENDORED.md), not from
this file. Re-deriving them by hand is the defect this script exists to prevent.

Usage:
  python3 campaign_gates.py pool.json --out gates.csv --rejects rejects.json
  python3 campaign_gates.py pool.json --reference-chains refs.json --out gates.csv
  python3 campaign_gates.py pool.json --json

Pool is a JSON list (or CSV) of objects carrying at least `design_id` and
`sequence`; `designed_structure_path` and `binder_chain` enable the structural
gates.

`--reference-chains` is a JSON list of every target chain and every control
chain, in either of two shapes:

    ["ref.pdb", "A"]                                   structure only
    {"pdb": "ref.pdb", "chain": "A",                   structure AND sequence
     "sequence": "AFTVT...", "role": "target"}

The pair form feeds the structural mimic screen only. Novelty's self-similarity
arm aligns SEQUENCES, so a reference with no `sequence` leaves that arm NOT_RUN
with a reason naming the chain -- it is not inferred from the PDB, because a
silently mis-parsed reference is a gate pointed at the wrong molecule. `role` is
"target" (the default) or "control".
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERDICT_PASS = "PASS"
VERDICT_REJECT = "REJECT"
VERDICT_NOT_RUN = "NOT_RUN"

# Mirrors the panel selector's alphabet and length policy, applied one stage
# EARLIER and for a sharper reason: the ledger records only literal gate
# REJECTs, so a malformed design is reported as SCREENED with no entry keeping
# it out -- and it reaches paid folding before the selector ever sees it. The
# liability helper would meanwhile strip `results/design1.pdb` to
# RESULTSDESIGNPDB and hand it a PASS.
AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWYXBZJUO")
BINDER_LEN_MIN, BINDER_LEN_MAX = 35, 160


def _load_pool(path):
    with open(path) as fh:
        if path.lower().endswith((".csv", ".tsv")):
            delim = "\t" if path.lower().endswith(".tsv") else ","
            return list(csv.DictReader(fh, delimiter=delim))
        data = json.load(fh)
    for key in ("designs", "pool", "rows", "items"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    if isinstance(data, list):
        return data
    raise SystemExit(f"{path}: expected a list of designs or an object carrying one")


def _liability(helpers, seq):
    """Composition gate. Returns (verdict, evidence) with the numbers that decided it."""
    if not seq:
        return VERDICT_NOT_RUN, {}
    flags = helpers.composition_liability_flags(seq)
    ev = {
        "liability_min_window_entropy_bits": flags.get("min_window_entropy_bits"),
        "liability_max_hydrophobic_patch_fraction": flags.get("max_hydrophobic_patch_fraction"),
        "liability_max_homopolymer_run": (flags.get("homopolymer") or {}).get("longest_run"),
        "liability_cys_parity": (flags.get("cys_parity") or {}).get("parity"),
    }
    return (VERDICT_REJECT if flags.get("flagged") else VERDICT_PASS), ev


def _plausibility(sp, pdb, chain):
    if not pdb or not os.path.exists(pdb):
        return VERDICT_NOT_RUN, {}, "no designed structure on this row"
    try:
        result = sp.structural_plausibility_verdict(pdb, chain)
    except Exception as exc:  # the kernel raises rather than guessing a chain
        return VERDICT_NOT_RUN, {}, f"{type(exc).__name__}: {exc}"
    ev = {
        f"plausibility_{k.split('.', 1)[-1]}": v
        for k, v in (result.get("measurements") or {}).items()
    }
    return result.get("verdict", VERDICT_NOT_RUN), ev, result.get("reason") or ""


def _mimic(tm, pdb, refs, chain):
    if not refs:
        return VERDICT_NOT_RUN, {}, "no reference chains supplied", None
    if not pdb or not os.path.exists(pdb):
        return VERDICT_NOT_RUN, {}, "no designed structure on this row", None
    try:
        screen = tm.target_mimic_screen(pdb, refs, design_chain=chain)
    except Exception as exc:
        return VERDICT_NOT_RUN, {}, f"{type(exc).__name__}: {exc}", None
    # The screen dict travels on to novelty_verdict as `tm_screen`. L81 makes the
    # TM arm one of novelty's four REJECT arms, so the kernel adopts this
    # verdict verbatim rather than recomputing it -- two screens of the same
    # design against the same references that could disagree is a defect, not a
    # cross-check.
    return (screen.get("verdict", VERDICT_NOT_RUN),
            {"target_mimic_tm_max": screen.get("tm_max")}, "", screen)


def _novelty(novelty, seq, corpus, target_seqs, control_seqs, uniref_hits,
             corpus_hits, screen, tier):
    """Protocol L81 for one design. The kernel decides; this only supplies subjects.

    Every threshold, the ubiquitin detector and the combination rule live in
    `novelty_gate`. Re-deriving any of them here is the defect this whole file
    exists to prevent -- and novelty is the worst place to do it, because its
    REJECT arms are the only ones that catch a design which is a copy of
    something real. Every other gate on this row would happily pass ubiquitin.
    """
    if novelty is None:
        return VERDICT_NOT_RUN, {}, "numpy unavailable in this environment"
    try:
        out = novelty.novelty_verdict(
            seq,
            corpus=corpus,
            target_chains=target_seqs,
            control_chains=control_seqs,
            uniref90_hits=uniref_hits,
            corpus_hits=corpus_hits,
            tm_screen=screen,
            required_subjects=tier,
        )
    except Exception as exc:
        return VERDICT_NOT_RUN, {}, f"{type(exc).__name__}: {exc}"
    screened = out.get("subjects_screened") or {}
    not_run = out.get("arms_not_run") or {}
    top = _top_hit(out.get("hits"))
    ev = {
        # The two are complements by the kernel's own contract: a subject kind
        # appears in exactly one of them. Shipping both means a reader can tell
        # "screened and clean" from "never screened" without inferring either,
        # which is the whole difference between a PASS and a NOT_RUN.
        "novelty_subjects_screened": ";".join(
            f"{k}={v}" for k, v in sorted(screened.items())
        ),
        "novelty_arms_not_run": ";".join(sorted(not_run)),
        "novelty_top_identity": top.get("gapped_identity"),
        "novelty_top_subject": top.get("subject_id"),
        "novelty_top_subject_kind": top.get("kind"),
        "novelty_top_aligned_columns": top.get("aligned_columns"),
    }
    # The kernel routes its explanation by outcome: a REJECT fills `reason`, and
    # a NOT_RUN fills `not_run_reason` and leaves `reason` None. Reading only
    # `reason` left the actionable half -- WHICH required subject was missing --
    # out of the artifact, while `novelty_arms_not_run` kept only bare arm names.
    verdict = out.get("verdict", VERDICT_NOT_RUN)
    explanation = out.get("not_run_reason") if verdict == VERDICT_NOT_RUN else out.get("reason")
    return verdict, ev, str(explanation or out.get("reason") or "")


# L81's own term is "gapped local identity", and `gapped_identity` is the key
# the kernel writes it under. Naming it here rather than probing a list of
# plausible spellings: a probe that misses returns an empty evidence cell on a
# row whose REJECT reason quotes the very number, which reads as an arm that
# found nothing rather than a column that was never filled.
_NOVELTY_IDENTITY_KEY = "gapped_identity"


def _top_hit(hits):
    """The strongest hit any arm found, for the evidence columns.

    A verdict with no numbers beside it is unfalsifiable, and these are the
    numbers that decided it -- plus WHICH subject it matched, which is what
    tells a reader whether a REJECT was ubiquitin, the campaign's own target, or
    a known binder. Empty when no arm ran; never a zero, which would read as
    "searched and found nothing alike".
    """
    best = {}
    for hit in hits or ():
        if not isinstance(hit, dict):
            continue
        value = hit.get(_NOVELTY_IDENTITY_KEY)
        if not isinstance(value, (int, float)):
            continue
        if not best or value > best.get(_NOVELTY_IDENTITY_KEY, float("-inf")):
            best = hit
    return best


def _lcp(lcp, seq):
    """L73's mandatory sequence restraint. Returns (score, not_run_reason).

    Reported, never a gate: the protocol makes LCP a restraint on sequence
    DESIGN and a recorded metric, not a rejection threshold, so this writes the
    number and lets selection and the report use it.

    It says WHY it is absent rather than going blank, and the reason is not
    hypothetical: the pool validator accepts the ambiguity codes X, B, Z, J, U
    and O, and the LCP implementation accepts only the standard twenty and
    raises on each of those six. A blanket catch returning None therefore
    dropped a MANDATORY recorded metric on every design carrying an X, with
    nothing on the row to say it had been dropped.
    """
    if lcp is None:
        return None, "numpy unavailable in this environment"
    if not seq:
        return None, "no sequence on this row"
    try:
        return lcp.lcp_score(seq), ""
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _pdb_body(pdb_path):
    """The file's text, or None. Matches what `dssp_fold_class` reads."""
    try:
        with open(pdb_path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _resolved_ss_method(helpers, body, chain, ss_codes):
    """Which resolver actually produced the fold class -- ASKED, not guessed.

    The first version of this grepped the whole file for a line starting HELIX
    or SHEET. That does not reproduce what the classifier does, in two ways
    that both mislabel P-SEA output as record-derived:

      - the kernel keeps only records whose chain matches the one being
        classified (HELIX column 20, SHEET column 22), so on a complex whose
        records annotate the TARGET chain, the binder falls through to P-SEA
        while a file-wide grep still says "pdb-records";
      - a record that paints residues not present in the chain does not count
        as an annotation at all, and the kernel says so explicitly, because an
        all-coil "other" would be counted as non-all-alpha by the diversity
        target.

    So call the kernel's own resolver and read whether it produced anything.
    Re-implementing its chain filter and validity rule here would be a second
    copy of a load-bearing rule, free to drift from the one that decides.
    """
    if ss_codes is not None:
        return "supplied"
    if body is None:
        return None
    try:
        return "pdb-records" if helpers._ss_from_pdb_records(body, chain) else "biotite-psea"
    except Exception:
        return None


def _check_ss_codes(helpers, did, codes, body, chain, seq):
    """Refuse per-residue codes that cannot be describing THIS design.

    `_normalize_ss_codes` maps every unrecognized character to coil and does no
    length check, and `_fold_class_from_ss` takes fractions over whatever length
    it is handed. So a stale array joined onto the wrong row does not fail --
    it returns a plausible class. Worse, an all-coil result is `other`, and
    `other` COUNTS as non-all-alpha, so a misjoin manufactures evidence for the
    diversity target rather than destroying it.

    The codes describe the chain's residues, so that is what they are measured
    against; with no structure on the row the sequence is the only reference
    left. Fails the pool rather than the row: a misjoin is a bug in how the
    pool was assembled, and the neighbouring rows were assembled the same way.
    """
    text = "".join(str(c).strip()[:1] or "-" for c in codes)
    unknown = sorted({c for c in text if c not in helpers._SS_ANY_CODES})
    if unknown:
        raise SystemExit(
            f"refusing the pool: design {did!r} has ss_codes containing "
            f"{''.join(unknown)!r}, which are not secondary-structure codes.\n"
            "Every unrecognized character is read as coil, and an all-coil design "
            "classifies as `other`,\n"
            "which COUNTS toward the >=10% non-all-alpha diversity target. Pass DSSP "
            "8-state (HGIEBTSC-)\n"
            "or biotite 3-state codes, one per residue."
        )
    expected, source = None, ""
    if body is not None:
        try:
            _, residues = helpers._pdb_chain_ca_residues(body, chain)
        except Exception:
            residues = []
        if not residues:
            raise SystemExit(
                f"refusing the pool: design {did!r} supplies ss_codes for chain "
                f"{chain!r}, which has no residues in its structure.\n"
                "The codes cannot be describing this design. Check the chain id and "
                "the join that built the pool."
            )
        # UNIQUE (resseq, icode). The kernel's CA scan appends one entry per CA
        # record, and two realistic shapes emit more than one per residue:
        # measured on a 30-residue chain, a two-MODEL file counts 60 and
        # alternate-location CAs count 60. DSSP emits one code per RESIDUE, so
        # comparing against the raw record count refuses valid input -- the same
        # false-refusal class as stripping terminal coil, one line over.
        expected = len(set(residues))
        source = f"chain {chain!r} of the designed structure"
    elif seq:
        expected, source = len(seq), "the design's sequence"
    if expected is not None and len(codes) != expected:
        raise SystemExit(
            f"refusing the pool: design {did!r} supplies {len(codes)} ss_codes but "
            f"{source} has {expected} residues.\n"
            "Per-residue codes joined onto the wrong row still classify -- they just "
            "classify something else,\n"
            "and the answer lands in the diversity evidence. Fix the join."
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pool", help="JSON or CSV design pool")
    ap.add_argument("--reference-chains",
                    help="JSON list of target/control chains: [pdb, chain] pairs, or "
                         "objects with pdb/chain/sequence/role (see the module docstring)")
    ap.add_argument("--known-binders",
                    help="known-binder corpus: FASTA/CSV/TSV file or a directory of them "
                         "(defaults to $CAMPAIGN_KNOWN_BINDER_CORPUS). Protocol L79 stages "
                         "this in the first hour; until it is staged, a clean design is "
                         "NOT_RUN rather than PASS, because a corpus of zero subjects "
                         "would clear every design against nothing.")
    ap.add_argument("--known-binder-hits",
                    help="JSON of precomputed known-binder-corpus hits, "
                         "{design_id: [hit, ...]}, in the same shape as "
                         "--uniref90-hits. Use this instead of --known-binders "
                         "at campaign scale: the in-process aligner is "
                         "O(pool x corpus) and the protocol's own corpus is "
                         "~16,500 entries.")
    ap.add_argument("--uniref90-hits",
                    help="JSON of precomputed MMseqs2 hits from a Tamarind sequence-identity "
                         "search: {design_id: [hit, ...]}. Each hit carries MMseqs2's own "
                         "columns -- identity/fident/pident and coverage/qcov/cov, plus an "
                         "optional subject_id/target. This is the one novelty limb that "
                         "cannot run locally; without it the UniRef90 arm is NOT_RUN.")
    ap.add_argument("--novelty-tier", choices=("dispatch", "final"), default="dispatch",
                    help="which subject sets are REQUIRED. `dispatch` (default) follows L79 "
                         "-- production scoring is not gated on UniRef90 staging. `final` "
                         "adds UniRef90, which L79 requires before any row reaches the "
                         "ranked sheet.")
    ap.add_argument("--out", help="write the per-design evidence CSV here")
    ap.add_argument("--rejects", help="write the rejected-design ledger here")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = ap.parse_args()

    try:
        from _kernel import qa_analysis_helpers as helpers
    except ImportError as exc:
        raise SystemExit(f"vendored kernel unavailable: {exc}")
    try:
        from _kernel import qa_tm_helpers as tm, structure_plausibility as sp
        structural = True
    except ImportError:
        # numpy is the only reason these two fail. An honest NOT_RUN on every
        # structural gate beats a campaign that silently skips them.
        tm = sp = None
        structural = False
    try:
        # `novelty_gate` imports without numpy and then raises inside the
        # aligner, which would surface as a per-row exception string rather than
        # a stated gate outcome. Probe the dependency at the seam instead, so
        # the whole novelty column reads NOT_RUN for one clear reason.
        import numpy as _numpy_probe  # noqa: F401
        from _kernel import novelty_gate as novelty, lcp
    except ImportError:
        novelty = lcp = None

    refs, target_seqs, control_seqs, refs_without_sequence = [], [], [], []
    if args.reference_chains:
        with open(args.reference_chains) as fh:
            raw_refs = json.load(fh)
        for item in raw_refs:
            if isinstance(item, dict):
                pdb_path, chain_id = item.get("pdb"), item.get("chain")
                sequence = str(item.get("sequence") or "").strip()
                role = str(item.get("role") or "target").strip().lower()
                if sequence:
                    label = f"{os.path.basename(str(pdb_path or 'ref'))}:{chain_id or '?'}"
                    (control_seqs if role.startswith("control") else target_seqs).append(
                        (label, sequence)
                    )
                if not sequence:
                    refs_without_sequence.append(
                        f"{os.path.basename(str(pdb_path or 'ref'))}:{chain_id or '?'}"
                    )
                if pdb_path and chain_id:
                    refs.append((pdb_path, chain_id))
            else:
                pair = tuple(item)
                refs.append(pair)
                refs_without_sequence.append(
                    f"{os.path.basename(str(pair[0]))}:{pair[1] if len(pair) > 1 else '?'}"
                )

    if novelty is not None and (target_seqs or control_seqs):
        # Judge every reference ONCE, here, for exactly the reason the hits file
        # is judged here: `_as_entry` raises while CONVERTING a subject, and the
        # kernel converts the target/control chains AFTER it has already run the
        # ubiquitin and corpus arms. So a reference like "123" raises on top of
        # an ALREADY-ESTABLISHED REJECT, and a per-row catch reports the whole
        # verdict as NOT_RUN -- the copied design keeps its rejection nowhere.
        # Same failure as a malformed hits file, one call site over.
        for label, sequence in list(target_seqs) + list(control_seqs):
            try:
                novelty._as_entry((label, sequence))
            except Exception as exc:
                raise SystemExit(
                    f"{args.reference_chains}: reference {label!r} is unusable -- {exc}\n"
                    "Refusing here rather than per row: the kernel converts references "
                    "AFTER running the\n"
                    "ubiquitin and known-binder arms, so a bad one raises on top of a "
                    "rejection already made\n"
                    "and the catch would report novelty NOT_RUN for a design that IS a copy."
                )

    corpus = None
    # Precomputed hits REPLACE the in-process corpus arm, so the corpus is not
    # resolved at all when they are supplied. Testing only `args.known_binders`
    # missed the environment route: with $CAMPAIGN_KNOWN_BINDER_CORPUS staged,
    # `load_known_binder_corpus(None)` still finds it, and the row then reports
    # BOTH `known_binder_corpus=1` and `known_binder_corpus_hits_are_precomputed=1`
    # -- the arm run twice against different subject sets, which is exactly what
    # the exclusivity check exists to prevent. Worse at protocol scale: the
    # aggregate cap then refuses the very path that was supposed to scale.
    if novelty is not None and not args.known_binder_hits:
        # Loading it here rather than per row: `load_known_binder_corpus` RAISES
        # on a staged corpus it cannot parse (a corpus being silently read as
        # empty is the failure wearing a success's clothes) and that belongs at
        # startup, not 6,000 rows in.
        corpus = novelty.load_known_binder_corpus(args.known_binders)
        if not corpus.available:
            print(f"  novelty: known-binder corpus NOT staged - {corpus.unavailable_reason}",
                  file=sys.stderr)

    def _load_hits(path, kind):
        if not path:
            return {}
        with open(path) as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, dict):
            raise SystemExit(
                f"{path}: expected an object keyed by design_id.\n"
                "A bare list cannot be attributed to a design, and novelty hits "
                "joined to the wrong design is a gate pointed at another molecule."
            )
        if novelty is not None:
            for design_key, design_hits in loaded.items():
                try:
                    novelty.evaluate_precomputed_hits(design_hits, kind)
                except Exception as exc:
                    raise SystemExit(
                        f"{path}: design {design_key!r} has an unusable hit -- {exc}\n"
                        "Emit the search's own columns (fident/pident for identity, "
                        "qcov/cov for coverage).\n"
                        "Refusing here rather than per row: a hit the kernel cannot "
                        "judge raises inside the\n"
                        "verdict, which would report novelty NOT_RUN and discard a "
                        "rejection another arm had already made."
                    )
        return loaded

    uniref_hits = _load_hits(
        args.uniref90_hits, novelty.SUBJECT_UNIREF90 if novelty else ""
    )
    corpus_hits = _load_hits(
        args.known_binder_hits,
        novelty.SUBJECT_KNOWN_BINDER_CORPUS if novelty else "",
    )
    if args.known_binder_hits and args.known_binders:
        raise SystemExit(
            "pass --known-binders OR --known-binder-hits, not both: the corpus arm "
            "would run twice\n"
            "against different subject sets and the row could not say which one "
            "produced its verdict."
        )
        # Judge the whole file HERE, once, and refuse the run if any hit is
        # malformed -- rather than letting the kernel raise per row into
        # `_novelty`'s catch, which would report NOT_RUN.
        #
        # That difference is the whole reason this block exists, and it is
        # measured, not hypothetical: with a hits file whose columns were named
        # `gapped_identity`/`query_coverage` instead of MMseqs2's own, a design
        # the known-binder arm had ALREADY REJECTED came back NOT_RUN, because
        # the raise happened before the verdict was assembled and took the
        # standing rejection with it. A bad hits file must never be able to
        # downgrade a rejecting gate.
        if novelty is not None:
            for design_key, design_hits in uniref_hits.items():
                try:
                    novelty.evaluate_precomputed_hits(
                        design_hits, novelty.SUBJECT_UNIREF90
                    )
                except Exception as exc:
                    raise SystemExit(
                        f"{args.uniref90_hits}: design {design_key!r} has an "
                        f"unusable hit -- {exc}\n"
                        "Emit the search's own columns (fident/pident for identity, "
                        "qcov/cov for coverage).\n"
                        "Refusing here rather than per row: a hit the kernel cannot "
                        "judge raises inside the\n"
                        "verdict, which would report novelty NOT_RUN and discard a "
                        "rejection another arm had already made."
                    )

    novelty_tier = (
        novelty.NOVELTY_REQUIRED_SUBJECTS_FINAL if args.novelty_tier == "final"
        else novelty.NOVELTY_REQUIRED_SUBJECTS_DISPATCH
    ) if novelty is not None else ()
    if args.novelty_tier == "final" and (not target_seqs or refs_without_sequence):
        missing = ", ".join(refs_without_sequence[:4]) or "(none supplied)"
        raise SystemExit(
            "--novelty-tier final requires a SEQUENCE on every reference chain in "
            "--reference-chains.\n"
            f"Missing on: {missing}\n"
            "The final tier certifies that the whole novelty gate ran, and its "
            "self-similarity arm aligns\n"
            "against sequences. A reference in the [pdb, chain] pair form supplies "
            "none, so the kernel\n"
            "records that arm in `arms_not_run` while the row still stamps `final` "
            "-- promising a comparison\n"
            "against a target or control that never happened. Controls count here "
            "as much as targets: a\n"
            "campaign that never compared its designs to its own controls has not "
            "run this gate.\n"
            'Use the object form ({"pdb": ..., "chain": ..., "sequence": ..., '
            '"role": "target"|"control"}).'
        )
    if args.novelty_tier == "final" and not args.uniref90_hits:
        raise SystemExit(
            "--novelty-tier final requires --uniref90-hits.\n"
            "L79 makes the full-UniRef90 check required before any row reaches the "
            "FINAL ranked sheet;\n"
            "asking for the final tier with no hits to judge would mark every design "
            "NOT_RUN and rank none."
        )

    rows, rejects, counts = [], [], {}
    pool = _load_pool(args.pool)
    # A silently dropped row is an ungated design with no ledger entry proving
    # it stayed out -- indistinguishable downstream from one that passed. Name
    # the offender and refuse the pool.
    # An empty pool exits 0 and names a gates.csv nobody wrote, so the stage
    # reads as successful and whatever runs next fails on the missing file. It
    # also means no constant-gate warning can fire, because there is nothing to
    # be constant over.
    if not pool:
        raise SystemExit(
            "refusing an empty pool: nothing to screen.\n"
            "An empty gate stage cannot be distinguished from one that ran and rejected\n"
            "everything. Fix the generation or the join upstream."
        )
    nameless = [i for i, e in enumerate(pool)
                if not str(e.get("design_id") or e.get("id") or "").strip()]
    if nameless:
        shown = ", ".join(str(i) for i in nameless[:5])
        raise SystemExit(
            f"refusing the pool: {len(nameless)} row(s) carry no design_id or id "
            f"(first at index {shown}).\n"
            "A row with no durable identifier cannot be tracked into or out of a gate."
        )
    # A multi-row pool in which every design carries the SAME sequence is not a
    # design pool. The way this happens is measured, not hypothetical: a
    # generator writes the binder and the target joined in one field, and the
    # split takes the wrong half -- so every row becomes the target. RFdiffusion
    # ships exactly that shape, and its own schema documents the two chains in
    # the opposite order from the one it delivers, so following the
    # documentation produces this pool. The target is of legal length and
    # ordinary composition, so every other check here passes it.
    #
    # Fires ONLY on a pool that is otherwise perfectly well formed. A row with
    # no id, a duplicate id, a missing sequence or an illegal length has its own
    # refusal that says more, and those must win -- otherwise a two-row pool
    # where one row simply lacks a sequence gets reported as a chain-split bug.
    _seqs = [str(e.get("sequence") or "").strip().upper() for e in pool]
    _ids = [str(e.get("design_id") or e.get("id") or "").strip() for e in pool]
    well_formed = (
        all(_seqs) and all(_ids) and len(set(_ids)) == len(_ids)
        and all(BINDER_LEN_MIN <= len(s) <= BINDER_LEN_MAX for s in _seqs)
        # The alphabet too, and this one is not hypothetical: an UN-SPLIT
        # `TARGET/BINDER` string is identical on every row and of legal
        # length, so without this it collected the chain-split diagnosis
        # below instead of the sharper "has non-residue characters '/'" that
        # names the actual repair.
        and all(not (set(s) - AMINO_ACIDS) for s in _seqs)
    )
    if len(pool) > 1 and well_formed and len(set(_seqs)) == 1:
        only = _seqs[0]
        raise SystemExit(
            f"refusing the pool: all {len(pool)} designs carry an identical "
            f"{len(only)}-residue sequence.\n"
            "  A pool of one repeated sequence is not a design pool. The usual cause "
            "is a joined\n"
            "  sequence field (binder and target in one string) split on the wrong "
            "side -- every row\n"
            "  is then the TARGET, which is of legal length and passes every other "
            "check here.\n"
            "  Identify the binder by excluding your frozen target sequence and "
            "asserting the\n"
            "  designed length, not by taking a fixed position in the split.\n"
            "  If instead these rows genuinely converged on one binder from "
            "different backbones,\n"
            "  that pool cannot make a panel either -- the selector rejects "
            "exact-sequence duplicates,\n"
            "  so it would collapse to a single design. Screen the distinct "
            "sequence once."
        )

    # THE AGGREGATE COST, checked before the loop rather than inside it.
    # The kernel's cap is per invocation and compares only `len(corpus.entries)`
    # against CORPUS_LOCAL_ALIGNMENT_MAX_PAIRS, so a 16,500-entry corpus (the
    # size protocol L79's own corpus folder ships) never trips it -- while the
    # POOL multiplies it. Measured at 0.5 ms per local alignment, the protocol's
    # 20,000-design pool against that corpus is ~330M alignments, about 46 hours
    # single-core, on a campaign with a 24-hour clock. Refusing up front with the
    # arithmetic beats discovering it two days in.
    if novelty is not None and corpus is not None and corpus.available:
        pair_total = len(pool) * len(corpus.entries)
        if pair_total > novelty.CORPUS_LOCAL_ALIGNMENT_MAX_PAIRS:
            raise SystemExit(
                f"refusing the run: {len(pool)} designs x {len(corpus.entries)} "
                f"corpus entries is {pair_total:,} local alignments, above the "
                f"kernel's {novelty.CORPUS_LOCAL_ALIGNMENT_MAX_PAIRS:,}-alignment "
                "cap.\n"
                "The in-process aligner is O(pool x corpus) and runs at roughly "
                "0.5 ms per pair, so this\n"
                "would take on the order of "
                f"{pair_total * 0.0005 / 3600:.0f} hours single-core.\n"
                "Stage the MMseqs2 index the protocol asks for, search the pool "
                "against the corpus once,\n"
                "and pass its rows with --known-binder-hits instead of "
                "--known-binders."
            )

    seen = set()
    for entry in pool:
        did = str(entry.get("design_id") or entry.get("id") or "").strip()
        if did in seen:
            raise SystemExit(f"refusing the pool: duplicate design_id {did!r}")
        seen.add(did)
        # No sequence means liability cannot run, and the ledger records only
        # REJECT -- so the row is reported as screened with no rejection entry,
        # and a downstream pool built by removing ledger ids carries it into
        # paid folding ungated. Fail closed, like a missing id.
        seq = str(entry.get("sequence") or "").strip().upper()
        if not seq:
            raise SystemExit(
                f"refusing the pool: design {did!r} carries no sequence.\n"
                "Liability cannot run on it, and a row that is neither gated nor "
                "rejected is one nothing downstream can keep out."
            )
        offenders = sorted({ch for ch in seq if ch not in AMINO_ACIDS})
        if offenders:
            raise SystemExit(
                f"refusing the pool: design {did!r} has non-residue characters "
                f"{''.join(offenders)!r} in its sequence.\n"
                "The liability helper would strip these and score whatever letters remain,\n"
                "so the row would be reported as screened and reach paid folding."
            )
        if not BINDER_LEN_MIN <= len(seq) <= BINDER_LEN_MAX:
            raise SystemExit(
                f"refusing the pool: design {did!r} is {len(seq)} residues, outside the "
                f"frozen {BINDER_LEN_MIN}-{BINDER_LEN_MAX} policy.\n"
                "Gating it would spend co-folding compute on a design the selector refuses."
            )
        pdb = entry.get("designed_structure_path") or entry.get("structure_path")
        chain = entry.get("binder_chain")
        row = {"design_id": did}

        lv, lev = _liability(helpers, entry.get("sequence"))
        row["liability_verdict"] = lv
        row.update(lev)

        if structural:
            pv, pev, preason = _plausibility(sp, pdb, chain)
            mv, mev, mreason, mscreen = _mimic(tm, pdb, refs, chain)
        else:
            pv, pev, preason = VERDICT_NOT_RUN, {}, "numpy unavailable in this environment"
            mv, mev, mreason = VERDICT_NOT_RUN, {}, "numpy unavailable in this environment"
            mscreen = None
        row["structural_plausibility_verdict"] = pv
        row.update(pev)
        row["target_mimic_verdict"] = mv
        # ALSO under the kernel's own name, because `select_with_diversity_caps`
        # resolves the ban from `row["target_mimic"]` and falls back to the bare
        # `target_mimic_tm_max` only when that key is absent. Writing the verdict
        # under a name the ban does not read let a NOT_RUN row ship on the
        # strength of its number; measured against a PASS control, both arms
        # shipped 3 of 3.
        #
        # WHICH value goes there is the whole question, because the kernel
        # prefers a verdict WORD over the number. Neither one alone is safe:
        #
        #   - the word alone lets a stale or misjoined PASS override a measured
        #     TM at or above the ban threshold, and nothing downstream re-runs
        #     the mimic screen to catch it;
        #   - the number alone reads the `failures` shape -- one reference
        #     scored low, another could not be scored -- as a PASS, which is
        #     the NOT_RUN this whole block exists to preserve.
        #
        # So: NOT_RUN dominates everything, and where the screen did produce a
        # measurement that MEASUREMENT decides, exactly as selection.md says
        # ("the ban reads the measurement, not the verdict").
        tm_measured = mev.get("target_mimic_tm_max")
        if mv == VERDICT_NOT_RUN or tm_measured is None:
            row["target_mimic"] = mv
        else:
            row["target_mimic"] = tm_measured
        row.update(mev)

        # Fold class feeds the >=10% non-all-alpha diversity target. Reported,
        # never a ranking gate.
        #
        # A row MAY carry `ss_codes` -- DSSP 8-state (HGIEBTSC-) or biotite's
        # 3-state (abc) for the designed chain. Forward it, because the target
        # is defined "not-all-alpha under DSSP" while the classifier's only
        # dependency-free fallback is P-SEA, a different assignment. Without
        # this the canonical path was unreachable from here: generator PDBs
        # carry no HELIX/SHEET records, so the run silently fell to P-SEA or
        # to NOT_RUN no matter what DSSP the campaign had in hand.
        # Preserve an ITERABLE as-is. A DSSP tool -- and biotite's own
        # annotate_sse -- emits per-residue codes as a list, and str() on that
        # yields "['E', 'E', ...]", whose brackets, quotes and commas the
        # kernel reads as coil: 40 strand residues classify all_beta passed
        # directly and `other` after coercion. Only a scalar needs trimming.
        raw_ss = entry.get("ss_codes")
        if isinstance(raw_ss, (list, tuple)):
            ss_codes = list(raw_ss) or None
        else:
            # DO NOT strip a scalar. DSSP writes SPACE for coil and the kernel
            # accepts it (` ` is in `_SS_ANY_CODES`, normalised to C), so a real
            # assignment with coil at either terminus -- " " + "H"*58 + " " --
            # loses two per-residue codes to `.strip()`. Harmless while the
            # codes were merely forwarded; once the count is checked against the
            # chain it turns a VALID canonical input into a refused pool.
            #
            # Incidental CSV padding is not a reason to trim: the length check
            # is what tells the two apart. Padding makes the count wrong and is
            # refused; a true DSSP string matches the chain exactly and passes.
            # Whitespace is DATA here, not padding: DSSP writes coil as a
            # space, so an entirely-coil assignment is an all-space string and
            # `text.strip()` discards it whole. Only a genuinely EMPTY field
            # means "no codes supplied". Measured on a 60-residue chain:
            #
            #   all-coil DSSP (60 spaces)   was fold_class NOT_RUN, now `other`
            #                               under method `supplied` -- and
            #                               `other` is what counts toward the
            #                               non-all-alpha diversity target, so
            #                               the evidence was being thrown away
            #   a stray one-space CSV cell  was a silent NOT_RUN, now a refusal
            #                               naming the count mismatch
            #
            # Both directions improve: the valid input survives, and the
            # malformed one stops being silent.
            text = str(raw_ss or "")
            ss_codes = text if text else None
        body = _pdb_body(pdb) if pdb and os.path.exists(pdb) else None
        if ss_codes is not None:
            _check_ss_codes(helpers, did, ss_codes, body, chain, seq)
        if pdb and os.path.exists(pdb):
            try:
                fold = helpers.dssp_fold_class(pdb, chain=chain, ss_codes=ss_codes)
            except Exception as exc:
                row["fold_class"] = VERDICT_NOT_RUN
                row["fold_class_not_run_reason"] = f"{type(exc).__name__}: {exc}"
            else:
                # `dssp_fold_class` returns a STRING -- `FoldClass` is a Literal
                # of "all_alpha" | "all_beta" | "alpha_beta" | "other" |
                # "unknown", not an object. Reading it through getattr yields
                # None for every real classification and turns the whole column
                # into NOT_RUN, which deletes the evidence for the >=10%
                # non-all-alpha diversity target.
                #
                # Only "unknown" is a non-classification: the kernel returns it
                # when no secondary structure could be resolved, and its own
                # docstring says it must not count toward the diversity target
                # and must be reported NOT_RUN. It does not raise to say so,
                # which is why this branch exists at all.
                label = str(fold).strip()
                if not label or label.lower() == "unknown":
                    row["fold_class"] = VERDICT_NOT_RUN
                    row["fold_class_not_run_reason"] = (
                        "the fold classifier returned no class for this structure "
                        "(no secondary structure resolved on the designed chain)"
                    )
                else:
                    row["fold_class"] = label
                    # WHICH method produced it. The diversity target is defined
                    # under DSSP and the classifier's last resort is P-SEA, so a
                    # class with no method beside it cannot be reported against
                    # that target. Derived from the kernel's own resolver order.
                    method = _resolved_ss_method(helpers, body, chain, ss_codes)
                    if method:
                        row["fold_ss_method"] = method
        else:
            row["fold_class"] = VERDICT_NOT_RUN
            row["fold_class_not_run_reason"] = "no designed structure on this row"

        # The one gate this script cannot run. Written explicitly: an absent
        # column reads downstream exactly like a gate that ran and passed.
        row["monomer_foldability_verdict"] = VERDICT_NOT_RUN
        row["monomer_foldability_not_run_reason"] = (
            "needs a binder-alone fold job; run it and join monomer_plddt onto the row"
        )

        # L81. The TM screen computed just above is handed over rather than
        # recomputed, so the mimic arm the kernel adopts is the same measurement
        # this row already reports under `target_mimic`.
        nv, nev, nreason = _novelty(
            novelty, seq, corpus, target_seqs, control_seqs,
            uniref_hits.get(did), corpus_hits.get(did), mscreen, novelty_tier,
        )
        row["novelty_verdict"] = nv
        # WHICH tier cleared it. A dispatch-tier PASS did not screen UniRef90 --
        # the protocol exempts it before dispatch and requires it before the
        # ranked sheet -- so without this column the two clearances are
        # indistinguishable to the sheet writer and dispatch evidence ships as
        # final evidence.
        row["novelty_tier"] = args.novelty_tier if novelty is not None else ""
        row.update(nev)

        # L73's restraint, recorded per design. Higher is worse.
        row["lcp_score"], lcp_reason = _lcp(lcp, seq)
        if lcp_reason:
            row["lcp_not_run_reason"] = lcp_reason
        elif lcp is not None:
            # The parameterisation travels WITH the number. Figure 1's exact
            # settings are not recoverable from the figure, the public
            # implementations disagree, and the kernel exports its choice for
            # exactly this reason -- so a score separated from this revision is
            # otherwise uninterpretable, and two campaigns' values are not
            # comparable without it.
            row["lcp_parameterisation"] = str(
                getattr(lcp, "LCP_PARAMETERISATION", "") or ""
            )

        # Route each reason by ITS OWN verdict. The kernel returns a `reason`
        # for any outcome, so folding them together wrote REJECT rationales
        # into a column named `_not_run_reason` -- and a consumer filtering on
        # "this column is non-empty" then counted refused designs as gates that
        # never ran, which is the exact confusion every NOT_RUN here exists to
        # prevent.
        not_run, rejected_because = [], []
        for verdict, reason in ((pv, preason), (mv, mreason), (nv, nreason)):
            if not reason:
                continue
            (not_run if verdict == VERDICT_NOT_RUN else rejected_because).append(reason)
        if not_run:
            row["gate_not_run_reason"] = "; ".join(not_run)
        if rejected_because:
            row["gate_reject_reason"] = "; ".join(rejected_because)

        # The ledger carries the MEASUREMENTS beside each rejection, not just
        # the gate's name. A ledger entry reading {design_id, gate} says a
        # design was removed and gives a reader no way to check whether it
        # should have been -- which is the audit the rejects file exists for,
        # and what the deliverables page promises it holds.
        gate_evidence = {
            "liability": lev,
            "structural_plausibility": pev,
            "target_mimic": mev,
            "novelty": nev,
            "monomer_foldability": {},
        }
        gate_reason = {
            "structural_plausibility": preason, "target_mimic": mreason,
            "novelty": nreason,
        }
        for gate, verdict in (
            ("liability", lv), ("structural_plausibility", pv), ("target_mimic", mv),
            ("novelty", nv), ("monomer_foldability", VERDICT_NOT_RUN),
        ):
            counts.setdefault(gate, {}).setdefault(verdict, 0)
            counts[gate][verdict] += 1
            if verdict == VERDICT_REJECT:
                entry = {"design_id": did, "gate": gate}
                entry.update({k: v for k, v in (gate_evidence.get(gate) or {}).items()
                              if v is not None and v != ""})
                if gate_reason.get(gate):
                    entry["reason"] = gate_reason[gate]
                rejects.append(entry)
        rows.append(row)

    if args.out and rows:
        cols, seen = [], set()
        for r in rows:
            for k in r:
                if k not in seen:
                    seen.add(k)
                    cols.append(k)
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    if args.rejects:
        with open(args.rejects, "w") as fh:
            json.dump({"rejected": rejects}, fh, indent=2)

    rejected_ids = sorted({r["design_id"] for r in rejects})
    summary = {
        "screened": len(rows),
        "rejected": len(rejected_ids),
        "rejected_design_ids": rejected_ids,
        "verdict_counts": counts,
        # Availability and execution are different claims. numpy importing says
        # nothing about whether any row had a structure to screen, and a JSON
        # consumer that reads one as the other treats a zero-row structural
        # screen as a completed one.
        "structural_gates_available": structural,
        "structural_gates_evaluated": {
            gate: sum(n for verdict, n in (counts.get(gate) or {}).items()
                      if verdict != VERDICT_NOT_RUN)
            for gate in ("structural_plausibility", "target_mimic")
        },
        "evidence_csv": args.out,
        "rejects_ledger": args.rejects,
    }
    if args.json:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"screened {summary['screened']} designs, {summary['rejected']} rejected")
        for gate, tally in counts.items():
            print(f"  {gate}: " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
        if not structural:
            print("  NOTE: numpy unavailable - plausibility, mimic and novelty are NOT_RUN, "
                  "not passed, and lcp_score is absent")
    # A gate that passes everything, fails everything, or returns a constant is
    # broken until investigated -- all three, not just the un-run case. The
    # job-borne gates are legitimately all-NOT_RUN here, so they are exempt from
    # that one arm and named as such in the row.
    always_not_run = {"monomer_foldability"}
    for gate, tally in counts.items():
        if not rows:
            break
        if tally.get(VERDICT_NOT_RUN, 0) == len(rows) and gate not in always_not_run:
            print(f"  WARNING: {gate} did not run on any design - it is NOT a passed gate",
                  file=sys.stderr)
        elif tally.get(VERDICT_PASS, 0) == len(rows):
            print(f"  WARNING: {gate} passed every one of {len(rows)} designs - "
                  "a constant gate is broken until investigated", file=sys.stderr)
        elif tally.get(VERDICT_REJECT, 0) == len(rows):
            print(f"  WARNING: {gate} rejected every one of {len(rows)} designs - "
                  "a constant gate is broken until investigated", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
