"""The campaign kernel and its two entry points.

These tests pin the things that are silently wrong when they break. Every case
below reproduced a real defect during development, or guards a rule the
protocol states in prose and only code can enforce.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MCP_SCRIPTS = (
    ROOT / "plugins/tamarind-mcp/skills/tamarind-mcp-miniprotein-campaign/scripts"
)
CLI_SCRIPTS = ROOT / "plugins/tamarind-cli/skills/tamarind-miniprotein-campaign/scripts"
ENTRY_POINTS = ("campaign_gates.py", "select_panel.py")

numpy = pytest.importorskip("numpy", reason="the structural gates need numpy")


@pytest.fixture(scope="module")
def kernel():
    sys.path.insert(0, str(MCP_SCRIPTS))
    from _kernel import qa_analysis_helpers, qa_selection_helpers  # noqa: E402

    return qa_analysis_helpers, qa_selection_helpers


def test_both_plugins_ship_the_identical_kernel_and_entry_points() -> None:
    """A divergent copy computes different numbers than the other transport."""
    for name in ENTRY_POINTS:
        assert (MCP_SCRIPTS / name).read_bytes() == (CLI_SCRIPTS / name).read_bytes(), name
    mcp_kernel = sorted(p.name for p in (MCP_SCRIPTS / "_kernel").glob("*.py"))
    cli_kernel = sorted(p.name for p in (CLI_SCRIPTS / "_kernel").glob("*.py"))
    assert mcp_kernel == cli_kernel
    for name in mcp_kernel:
        assert (MCP_SCRIPTS / "_kernel" / name).read_bytes() == (
            CLI_SCRIPTS / "_kernel" / name
        ).read_bytes(), name


def test_kernel_records_the_commit_it_was_vendored_from() -> None:
    """Drift is only detectable if the source commit is written down."""
    for scripts in (MCP_SCRIPTS, CLI_SCRIPTS):
        manifest = (scripts / "_kernel" / "VENDORED.md").read_text()
        assert "commit: `" in manifest
        assert "content digest: `" in manifest


def test_score_algebra_takes_terms_per_design_not_per_arm(kernel) -> None:
    """The transposed input is ACCEPTED and silently scores the wrong terms.

    `_as_term_matrix` validates only that the matrix is rectangular, so an
    `[arm][design]` input with as many arms as designs passes and produces a
    number for every row. This is the defect `_term_matrix` in select_panel.py
    exists to prevent, so pin the correct orientation against a hand-computed
    mean rather than against the function's own output.
    """
    helpers, _ = kernel
    per_design_ipsae = [[0.71, 0.66, 0.69], [0.58, 0.55, 0.61], [0.49, 0.52, 0.47]]
    per_design_dockq = [[0.41, 0.38, 0.35], [0.29, 0.31, 0.27], [0.22, 0.24, 0.20]]
    scores = helpers.final_score_from_terms(per_design_ipsae, per_design_dockq)
    assert scores[0] == pytest.approx((0.71 + 0.66 + 0.69 + 0.41 + 0.38 + 0.35) / 6)

    transposed = helpers.final_score_from_terms(
        [list(col) for col in zip(*per_design_ipsae)],
        [list(col) for col in zip(*per_design_dockq)],
    )
    assert transposed[0] != pytest.approx(scores[0]), (
        "a square transposed matrix must still be caught by _term_matrix, not by the kernel"
    )


def test_a_missing_term_is_never_averaged_in_as_zero(kernel) -> None:
    helpers, _ = kernel
    scores = helpers.final_score_from_terms([[0.7, None, 0.6]], [[0.4, 0.3, 0.2]])
    assert scores == [None], "a design missing a term is NaN-rejected, never a mean over survivors"


def test_liability_gate_rejects_a_low_complexity_sequence(kernel) -> None:
    helpers, _ = kernel
    flags = helpers.composition_liability_flags("MKKKKKKKKKKKKWWWWWWWWWWCA")
    assert flags["flagged"] is True
    assert flags["homopolymer"]["longest_run"] >= 5
    assert flags["cys_parity"]["parity"] == "odd"


def test_select_panel_refuses_without_a_passing_gate(tmp_path: Path) -> None:
    """Production ranking is blocked until the validation check PASSes."""
    candidates = tmp_path / "c.json"
    candidates.write_text(json.dumps([{"design_id": "d1", "ipsae_a": 0.5}]))

    missing = subprocess.run(
        [sys.executable, str(MCP_SCRIPTS / "select_panel.py"), str(candidates)],
        capture_output=True, text=True,
    )
    assert missing.returncode != 0
    assert "--gate is required" in missing.stderr

    failed = tmp_path / "gate.json"
    failed.write_text(json.dumps({"status": "FAIL"}))
    refused = subprocess.run(
        [sys.executable, str(MCP_SCRIPTS / "select_panel.py"), str(candidates),
         "--gate", str(failed)],
        capture_output=True, text=True,
    )
    assert refused.returncode != 0
    assert "not PASS" in refused.stderr


def test_a_row_with_no_mimic_verdict_is_refused_not_admitted(kernel) -> None:
    """Absence is not a pass -- the ban is enforced before the relaxation ladder."""
    _, selection = kernel
    rows = [
        {
            "design_id": f"d{i}", "sequence": "MKQLEDKVEELLSKNYHLENEVARLKKLV" + "A" * i,
            "root_backbone_id": f"b{i}", "structure_method": m, "seq_method": "solublempnn",
        }
        for i, m in enumerate(("boltzgen", "rfdiffusion3", "genie3"))
    ]
    result = selection.select_with_diversity_caps(rows, panel_size=3)
    assert not (result.get("selected") or [])
    assert result["rejection_counts"].get("missing_provenance_field") == 3


@pytest.mark.parametrize("script", ENTRY_POINTS)
@pytest.mark.parametrize("scripts_dir", [MCP_SCRIPTS, CLI_SCRIPTS], ids=["mcp", "cli"])
def test_entry_points_run_from_an_unrelated_directory(
    script: str, scripts_dir: Path, tmp_path: Path
) -> None:
    done = subprocess.run(
        [sys.executable, str(scripts_dir / script), "--help"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr


def test_vendor_rewriter_does_not_corrupt_relative_imports() -> None:
    """The rewriter must not eat the leading underscore off its own output.

    An earlier version ran a global `replace("from ._", "from .")`, which turns
    `from ._rubric_constants import` -- the import that function itself writes --
    into `from .rubric_constants import`. Nothing upstream imports relatively
    today, so it never fired; a rewriter that breaks the moment upstream adds one
    is a trap worth pinning.
    """
    spec = importlib.util.spec_from_file_location(
        "vendor_tool", ROOT / "tools/vendor_campaign_kernel.py"
    )
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    assert tool.rewrite("from campaign.cda.subagents.novelty_gate import (") == (
        "from .novelty_gate import ("
    )
    assert tool.rewrite("from campaign.cda.prompts.qa_rubrics import X") == (
        "from ._rubric_constants import X"
    )
    # Untouched: unrelated imports, and any relative import already present.
    for line in ("from dataclasses import dataclass", "import numpy as np",
                 "from ._rubric_constants import X", "from ._foo import Y"):
        assert tool.rewrite(line) == line, line


# ── round 1 codex findings, each pinned by the failure it caused ────────────

def _run(script: str, *args: str, scripts=MCP_SCRIPTS):
    return subprocess.run(
        [sys.executable, str(scripts / script), *args], capture_output=True, text=True
    )


def _gate(tmp_path: Path, **over) -> Path:
    body = {"status": "PASS", "separation": 0.31,
            "controls": ["pos_ctrl", "neg_1", "target_selfpair"]}
    body.update(over)
    p = tmp_path / "gate.json"
    p.write_text(json.dumps(body))
    return p


_METHODS = ("boltzgen", "rfdiffusion3", "genie3", "pxdesign")
# The seq_method cap is two-thirds of the panel, so a population that shares
# one sequence designer cannot fill a panel and then trips the method floor.
_SEQ_METHODS = ("solublempnn", "solublecaliby", "proteinmpnn", "solublempnn")
_SEQUENCES = (
    "MSTQPWVKNGDFIRYTLEACHKMQDPNVFGSRYLAWDNKVIPCEQTMFHGRLSDAYVKNPEWQIFTRDGH",
    "MRYKDLFVQNPWHSAECGITMKDLNVFRQYPAWSGKDVHTLECMFNRQIPDGYVKSAEWLTFQRNDHGVM",
    "MDWKQNAFLRSHVGYTIPCEMKQDRNVFLAWSGHKTVIPDCEQMFNRYLSDAGVKNPEWQAFTIRDGHVM",
    "MEHKRWDQVSANFLYTGIPCMKDQNRVFLWASGHKTVIPDCEQMFNRYLSDAGVKNPEWQAFTIRDGHVM",
)


def _population(n: int = 3) -> list[dict]:
    """A pool with real spread and enough methods to clear the absolute floor.

    rank_zscore is transductive, so a single-row pool has no spread and the
    algebra correctly returns None -- every panel fixture needs a population.
    """
    return [_candidate(f"p{i}", float(i), _index=i) for i in range(n)]


def _candidate(design_id: str, z: float, _index: int = 0, **over) -> dict:
    row = {
        "design_id": design_id, "sequence": _SEQUENCES[_index % len(_SEQUENCES)],
        "root_backbone_id": f"b-{design_id}", "structure_method": _METHODS[_index % len(_METHODS)],
        "seq_method": _SEQ_METHODS[_index % len(_SEQ_METHODS)],
        "tm_cluster": f"c-{design_id}",
        "target_mimic": "PASS", "opt_round": 0, "n_seeds": 5,
        "liability_verdict": "PASS", "structural_plausibility_verdict": "PASS",
        # novelty PASS at the FINAL tier: this fixture is a design that IS
        # clearable. It read NOT_RUN while the gate could not run at all; now
        # that it runs, the sheet writer requires the full-UniRef90 tier, and a
        # fixture carrying the old value would be asserting the gap is fine.
        "target_mimic_verdict": "PASS", "novelty_verdict": "PASS",
        "novelty_tier": "final",
        "monomer_foldability_verdict": "NOT_RUN",
        "ipsae_ef2full": 0.5 + z / 100, "sc_DockQ_ef2full": 0.3 + z / 100,
    }
    row.update(over)
    return row


def test_the_ipsae_mask_stamp_is_not_treated_as_a_score_term(tmp_path: Path) -> None:
    """Every scored row is REQUIRED to carry `ipsae_mask`, and it is a string.

    Swept into the algebra it parses to None and makes the whole row ineligible,
    so a correctly-stamped campaign scores nothing at all.
    """
    rows = _population(3)
    for row in rows:
        row["ipsae_mask"] = "PER_PROTOMER_MAX(not UNION)"
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "s.csv"), "--json")
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert summary["panel_size_shipped"] == 3, summary
    assert "ipsae_mask" not in summary["realized_terms"]


def test_candidates_are_sorted_before_the_caps_not_after(tmp_path: Path) -> None:
    """The selector admits greedily in input order.

    Both rows share a root backbone, so the 5% cap admits exactly one. Sorting
    only the finished panel cannot recover the better row the caps excluded.
    """
    shared = {"root_backbone_id": "b1", "tm_cluster": "c1"}
    rows = [
        _candidate("low", -9.0, rank_zscore=-9.0, **shared),
        _candidate("high", 9.0, rank_zscore=9.0, **shared),
    ]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    out = tmp_path / "s.csv"
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "1", "--out", str(out), "--allow-campaign-failure")
    assert done.returncode == 0, done.stderr
    shipped = [line.split(",")[0] for line in out.read_text().splitlines()[1:]]
    assert shipped == ["high"], f"input-order selection admitted {shipped}"


def test_a_null_score_row_is_never_ranked(tmp_path: Path) -> None:
    """final_score non-null is never relaxed; such rows are unranked, not shipped."""
    rows = _population(3) + [_candidate("broken", 1.0, _index=3, ipsae_ef2full=None)]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "5", "--json")
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert summary["unranked"] == 1
    assert summary["panel_size_shipped"] == 3, summary


def test_a_status_only_gate_artifact_is_refused(tmp_path: Path) -> None:
    """PASS has to say what separated the controls, not merely that something did."""
    src = tmp_path / "c.json"
    src.write_text(json.dumps([_candidate("d1", 1.0)]))

    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps({"status": "PASS"}))
    assert "no numeric `separation`" in _run(
        "select_panel.py", str(src), "--gate", str(bare)
    ).stderr

    thin = _gate(tmp_path, controls=["only_one"])
    assert "fewer than two `controls`" in _run(
        "select_panel.py", str(src), "--gate", str(thin)
    ).stderr


def test_a_path_in_the_sequence_field_is_refused_not_salvaged(tmp_path: Path) -> None:
    """The kernel's normalizer would turn `results/design1.pdb` into a protein.

    Fixed at this boundary rather than in the vendored kernel, which must stay
    byte-identical to upstream.
    """
    rows = _population(3) + [
        _candidate("bad", 1.0, _index=3, sequence="results/design1.pdb")
    ]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "5", "--json")
    summary = json.loads(done.stdout)
    assert summary["unranked"] == 1
    assert any("non-residue" in r for r in summary["unranked_reasons"])


@pytest.mark.parametrize(
    "over,expected",
    [
        ({"opt_round": 0, "parent_design_id": "p1"}, "round-0 design claims a parent"),
        ({"opt_round": 3}, "carries no parent_design_id"),
        ({"opt_round": ""}, "opt_round is blank"),
        ({"opt_round": 2, "parent_design_id": "self"}, "its own parent"),
    ],
)
def test_broken_optimization_lineage_is_refused(tmp_path: Path, over, expected) -> None:
    """A child that mints a fresh root escapes the per-root cap looking ordinary."""
    rows = _population(3) + [_candidate("self", 1.0, _index=3, **over)]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "5", "--json")
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert summary["unranked"] == 1
    assert any(expected in r for r in summary["unranked_reasons"]), summary["unranked_reasons"]


def test_gates_refuse_a_pool_row_with_no_durable_identifier(tmp_path: Path) -> None:
    """A silently dropped row is an ungated design with no ledger entry."""
    pool = tmp_path / "p.json"
    pool.write_text(json.dumps([{"design_id": "d1", "sequence": _SEQUENCES[0]}, {"sequence": _SEQUENCES[0]}]))
    done = _run("campaign_gates.py", str(pool))
    assert done.returncode != 0
    assert "no design_id or id" in done.stderr

    dupes = tmp_path / "d.json"
    dupes.write_text(json.dumps([{"design_id": "d1", "sequence": _SEQUENCES[0]},
                                 {"design_id": "d1", "sequence": _SEQUENCES[0]}]))
    assert "duplicate design_id" in _run("campaign_gates.py", str(dupes)).stderr


def test_gates_mark_the_job_borne_checks_not_run_rather_than_omitting_them(
    tmp_path: Path,
) -> None:
    """An absent column reads downstream like a gate that ran and found nothing."""
    pool = tmp_path / "p.json"
    pool.write_text(json.dumps([{"design_id": "d1", "sequence": _SEQUENCES[1]}]))
    out = tmp_path / "gates.csv"
    done = _run("campaign_gates.py", str(pool), "--out", str(out), "--json")
    assert done.returncode == 0, done.stderr
    header = out.read_text().splitlines()[0]
    for column in ("monomer_foldability_verdict", "novelty_verdict", "fold_class"):
        assert column in header, column
    counts = json.loads(done.stdout)["verdict_counts"]
    assert counts["monomer_foldability"] == {"NOT_RUN": 1}
    assert counts["novelty"] == {"NOT_RUN": 1}


# ── round 2 codex findings ─────────────────────────────────────────────────

def test_a_row_a_gate_already_rejected_is_never_ranked(tmp_path: Path) -> None:
    """The selector enforces only the target-mimic ban.

    Without this check a design the liability or plausibility gate REJECTed
    ranks on its score, and the recompute does not catch it: correctly-carried
    REJECT evidence reproduces, so it is not a mismatch.
    """
    rows = _population(3) + [
        _candidate("rejected", 99.0, _index=3, liability_verdict="REJECT")
    ]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "5", "--json")
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert any("liability_verdict is REJECT" in r for r in summary["unranked_reasons"])
    assert summary["panel_size_shipped"] == 3


def test_a_boolean_score_cell_is_not_read_as_a_number(tmp_path: Path) -> None:
    """float(True) is 1.0 -- a fabricated perfect score that tops the panel."""
    rows = _population(3) + [_candidate("boolish", 1.0, _index=3, ipsae_ef2full=True)]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "5", "--json")
    summary = json.loads(done.stdout)
    assert summary["unranked"] == 1
    assert summary["panel_size_shipped"] == 3


def test_an_ineligible_row_cannot_move_the_transductive_z_scores(tmp_path: Path) -> None:
    """rank_zscore's mean and spread come from the scored pool.

    A malformed row with extreme terms must not be in that population, or it
    changes the relative ordering of rows that do ship even though it never
    does.
    """
    def ranks_for(rows):
        src = tmp_path / f"c{len(rows)}.json"
        src.write_text(json.dumps(rows))
        out = tmp_path / f"s{len(rows)}.csv"
        done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                    "--panel-size", "3", "--out", str(out))
        assert done.returncode == 0, done.stderr
        import csv as _csv
        with out.open() as fh:
            return {r["design_id"]: r["rank_zscore"] for r in _csv.DictReader(fh)}

    clean = _population(3)
    # Same population, plus an extreme row that is dropped for a bad sequence.
    poisoned = _population(3) + [
        _candidate("extreme", 0.0, _index=3, sequence="not/a/sequence.pdb",
                   ipsae_ef2full=99.0, sc_DockQ_ef2full=99.0)
    ]
    assert ranks_for(clean) == ranks_for(poisoned)


def test_a_panel_below_the_structure_method_floor_is_refused(tmp_path: Path) -> None:
    """The floor is absolute; no rung of the ladder goes below it."""
    rows = [_candidate(f"m{i}", float(i), _index=0) for i in range(3)]
    for i, row in enumerate(rows):  # one method, distinct sequences and roots
        row["sequence"] = _SEQUENCES[i]
        row["root_backbone_id"] = f"b{i}"
        row["tm_cluster"] = f"c{i}"
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "s.csv"))
    assert done.returncode != 0
    assert "structure method(s), and the floor is" in done.stderr
    assert not (tmp_path / "s.csv").exists(), "refused runs must not write a sheet"


def test_a_short_panel_that_meets_the_floor_still_ships(tmp_path: Path) -> None:
    """"Ship the actual N" is the protocol's instruction, not a failure.

    campaign_failure is composite -- it is set for any underfilled panel -- so
    gating on it would block the case the protocol explicitly sanctions.
    """
    src = tmp_path / "c.json"
    src.write_text(json.dumps(_population(3)))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "30", "--json")
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert summary["panel_size_shipped"] == 3
    assert summary["short_of_request"] == 27


def test_gates_refuse_a_pool_row_with_no_sequence(tmp_path: Path) -> None:
    """Liability cannot run on it, and the ledger records only REJECT."""
    pool = tmp_path / "p.json"
    pool.write_text(json.dumps([{"design_id": "d1", "sequence": _SEQUENCES[0]},
                                {"design_id": "d2"}]))
    done = _run("campaign_gates.py", str(pool))
    assert done.returncode != 0
    assert "carries no sequence" in done.stderr


def test_gates_warn_when_a_gate_is_constant_across_the_pool(tmp_path: Path) -> None:
    """All-pass and all-reject are broken until investigated, same as all-NOT_RUN."""
    pool = tmp_path / "p.json"
    # Distinct sequences on purpose: a pool of one repeated sequence is itself
    # refused (it is the signature of a mis-split binder/target field), and a
    # constant VERDICT does not need identical rows to reproduce.
    pool.write_text(json.dumps([
        {"design_id": f"d{i}", "sequence": seq} for i, seq in enumerate((
            "MKKKKKKKKKKKKWWWWWWWWWWCAAAAAAAAAAAAAAAAAAAAAAAA",
            "MEEEEEEEEEEEEWWWWWWWWWWCAAAAAAAAAAAAAAAAAAAAAAAA",
            "MQQQQQQQQQQQQWWWWWWWWWWCAAAAAAAAAAAAAAAAAAAAAAAA",
        ))
    ]))
    done = _run("campaign_gates.py", str(pool), "--out", str(tmp_path / "g.csv"))
    assert done.returncode == 0, done.stderr
    assert "rejected every one of 3 designs" in done.stderr, done.stderr


def test_gates_report_structural_execution_separately_from_availability(
    tmp_path: Path,
) -> None:
    """numpy importing says nothing about whether any row had a structure."""
    pool = tmp_path / "p.json"
    pool.write_text(json.dumps([
        {"design_id": "d1", "sequence": _SEQUENCES[1]}
    ]))
    done = _run("campaign_gates.py", str(pool), "--json")
    summary = json.loads(done.stdout)
    assert summary["structural_gates_available"] is True
    assert summary["structural_gates_evaluated"] == {
        "structural_plausibility": 0, "target_mimic": 0
    }


# ── round 3 codex findings: four shapes of "absence is a pass" ─────────────

@pytest.mark.parametrize(
    "column", ["liability_verdict", "novelty_verdict",
               "structural_plausibility_verdict", "monomer_foldability_verdict"]
)
def test_a_missing_gate_verdict_is_not_a_pass(tmp_path: Path, column: str) -> None:
    """An absent verdict is indistinguishable from a gate that ran and passed."""
    bad = _candidate("nogate", 1.0, _index=3)
    del bad[column]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(_population(3) + [bad]))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "5", "--json")
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert any(f"{column} is absent" in r for r in summary["unranked_reasons"])
    assert summary["panel_size_shipped"] == 3


@pytest.mark.parametrize("value", [None, "", "many", -1])
def test_an_unusable_seed_count_is_not_a_shallow_tier(tmp_path: Path, value) -> None:
    """Coerced to 0 it reads as a deliberately shallow result, not a lost join."""
    src = tmp_path / "c.json"
    src.write_text(json.dumps(_population(3) + [_candidate("noseed", 1.0, _index=3, n_seeds=value)]))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "5", "--json")
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert any("n_seeds" in r for r in summary["unranked_reasons"]), summary["unranked_reasons"]


def test_two_targets_in_one_pool_are_refused(tmp_path: Path) -> None:
    """rank_zscore is per-target; pooling two changes every z-score."""
    rows = _population(3)
    for row in rows[:2]:
        row["target"] = "PD-L1"
    rows[2]["target"] = "TNF-alpha"
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)), "--panel-size", "3")
    assert done.returncode != 0
    assert "more than one target" in done.stderr

    # Partially labelled is refused too: it cannot be shown to be single-target.
    rows[2].pop("target")
    src.write_text(json.dumps(rows))
    assert "name none" in _run(
        "select_panel.py", str(src), "--gate", str(_gate(tmp_path)), "--panel-size", "3"
    ).stderr


def test_an_empty_panel_fails_instead_of_reporting_a_sheet_it_never_wrote(
    tmp_path: Path,
) -> None:
    """Exit 0 with no --out file leaves a pipeline to fail later on a missing path."""
    bad = [_candidate(f"b{i}", float(i), _index=i, sequence="not/a/sequence.pdb")
           for i in range(3)]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(bad))
    out = tmp_path / "sheet.csv"
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(out))
    assert done.returncode != 0
    assert "no candidate survived" in done.stderr
    assert not out.exists()


# ── round 4 codex findings ─────────────────────────────────────────────────

def test_method_token_variants_cannot_inflate_the_method_count(tmp_path: Path) -> None:
    """`rfdiffusion3`, `RFdiffusion3` and `rfdiffusion-3` are ONE tool.

    Counted raw they are three distinct structure methods, so one generator
    satisfies the absolute floor and slips its per-method cap.
    """
    rows = _population(3)
    for row, spelling in zip(rows, ("rfdiffusion3", "RFdiffusion3", "rfdiffusion-3")):
        row["structure_method"] = spelling
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)), "--panel-size", "3")
    assert done.returncode != 0
    assert "structure method(s), and the floor is" in done.stderr


def test_a_small_panel_size_cannot_buy_its_way_under_the_method_floor(
    tmp_path: Path,
) -> None:
    """The kernel scales its floor to the requested size; the campaign's is absolute."""
    rows = _population(2)
    for row in rows:
        row["structure_method"] = "boltzgen"
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)), "--panel-size", "2")
    assert done.returncode != 0
    assert "floor is 3" in done.stderr


def test_losing_the_whole_pose_limb_must_be_declared(tmp_path: Path) -> None:
    """Ranking on confidence alone is a disclosed reduction, not a smaller score."""
    rows = _population(3)
    for row in rows:
        del row["sc_DockQ_ef2full"]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    refused = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)), "--panel-size", "3")
    assert refused.returncode != 0
    assert "pose limb" in refused.stderr

    allowed = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                   "--panel-size", "3", "--allow-reduced-instrument", "--json")
    assert allowed.returncode == 0, allowed.stderr
    assert json.loads(allowed.stdout)["panel_size_shipped"] == 3


@pytest.mark.parametrize("length", [20, 200])
def test_a_sequence_outside_the_frozen_length_policy_is_refused(
    tmp_path: Path, length: int
) -> None:
    """A 200-residue target chain joined as the binder is valid protein text."""
    bad = _candidate("wrong_len", 1.0, _index=3, sequence="A" * length)
    src = tmp_path / "c.json"
    src.write_text(json.dumps(_population(3) + [bad]))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "5", "--json")
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert any("outside the frozen policy" in r for r in summary["unranked_reasons"])


def test_gates_refuse_an_empty_pool(tmp_path: Path) -> None:
    """An empty screen cannot be distinguished from one that rejected everything."""
    pool = tmp_path / "p.json"
    pool.write_text(json.dumps([]))
    done = _run("campaign_gates.py", str(pool), "--out", str(tmp_path / "g.csv"))
    assert done.returncode != 0
    assert "empty pool" in done.stderr
    assert not (tmp_path / "g.csv").exists()


# ── round 5 (confirming) codex findings ────────────────────────────────────

def test_pose_pass_is_derived_not_trusted(tmp_path: Path) -> None:
    """pose_PASS sits AHEAD of rank_zscore in the rank key.

    One stale or hand-authored TRUE sorts a pose-failing design above every
    honest row, and corrupts cap admission order on the way.
    """
    rows = _population(3)
    rows[0]["sc_DockQ_ef2full"] = 0.05      # well below the 0.23 floor
    rows[0]["pose_PASS"] = "TRUE"
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)), "--panel-size", "3")
    assert done.returncode != 0
    assert "carried pose verdicts disagree" in done.stderr

    # Derived honestly, the same row ranks below the pose-passing ones.
    rows[0].pop("pose_PASS")
    src.write_text(json.dumps(rows))
    out = tmp_path / "s.csv"
    ok = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
              "--panel-size", "3", "--out", str(out))
    assert ok.returncode == 0, ok.stderr
    import csv as _csv
    with out.open() as fh:
        ranked = [(r["design_id"], r["pose_PASS"]) for r in _csv.DictReader(fh)]
    assert ranked[-1] == ("p0", "FALSE"), ranked


def test_a_missing_arm_makes_the_pose_term_not_run_never_a_partial_min(
    tmp_path: Path,
) -> None:
    """Two arms of three read systematically HIGHER than three."""
    rows = _population(4)
    for i, row in enumerate(rows):
        row["sc_DockQ_ptxv2"] = 0.40 + i / 50
    rows[0]["sc_DockQ_ptxv2"] = None
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    out = tmp_path / "s.csv"
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "4", "--out", str(out))
    assert done.returncode == 0, done.stderr
    import csv as _csv
    with out.open() as fh:
        by_id = {r["design_id"]: r for r in _csv.DictReader(fh)}
    # p0 lost a term, so it never reaches the panel at all -- which is the
    # stronger form of "never a partial min".
    assert "p0" not in by_id
    assert all(row["pose_PASS"] in ("TRUE", "FALSE") for row in by_id.values())


def test_gates_refuse_a_malformed_sequence_before_paid_compute(tmp_path: Path) -> None:
    """The ledger records only literal REJECTs.

    A malformed design is otherwise reported as SCREENED with no entry keeping
    it out, and reaches paid folding before the selector ever sees it.
    """
    pool = tmp_path / "p.json"
    pool.write_text(json.dumps([
        {"design_id": "d1", "sequence": _SEQUENCES[0]},
        {"design_id": "bad", "sequence": "results/design1.pdb"},
    ]))
    done = _run("campaign_gates.py", str(pool))
    assert done.returncode != 0
    assert "non-residue characters" in done.stderr

    pool.write_text(json.dumps([{"design_id": "long", "sequence": "A" * 200}]))
    assert "outside the frozen" in _run("campaign_gates.py", str(pool)).stderr


def test_a_misjoined_aggregate_is_caught_by_the_companion(tmp_path: Path) -> None:
    """Recomputing a cell from itself cannot catch a stale-but-numeric cell."""
    rows = _population(3)
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))

    companion = tmp_path / "per_seed.csv"
    lines = ["design_id,arm,seed,ipsae_min"]
    for row in rows:
        for seed in (1, 2):
            lines.append(f"{row['design_id']},ef2full,{seed},{row['ipsae_ef2full']}")
    companion.write_text("\n".join(lines) + "\n")
    ok = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
              "--panel-size", "3", "--companion", str(companion), "--json")
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["companion"]["ran"] is True

    # One sheet cell drifts from what the companion's seeds actually recorded.
    rows[0]["ipsae_ef2full"] = 0.99
    src.write_text(json.dumps(rows))
    bad = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
               "--panel-size", "3", "--companion", str(companion))
    assert bad.returncode != 0
    assert "disagree with the companion" in bad.stderr

    # A companion missing a ranked design is a coverage failure.
    partial = tmp_path / "partial.csv"
    partial.write_text("design_id,arm,seed,ipsae_min\np0,ef2full,1,0.5\n")
    src.write_text(json.dumps(_population(3)))
    assert "absent from the" in _run(
        "select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
        "--panel-size", "3", "--companion", str(partial)
    ).stderr


def test_a_degenerate_term_halts_with_its_cause_named(tmp_path: Path) -> None:
    """One constant term nulls rank_zscore for EVERY row, not just its own.

    Unranking them all would empty the panel and report "no candidate survived",
    which names the symptom and hides the cause.
    """
    rows = _population(3)
    for row in rows:
        row["sc_DockQ_ef2full"] = 0.40      # no spread
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)), "--panel-size", "3")
    assert done.returncode != 0
    assert "rank_zscore is undefined for every eligible row" in done.stderr
    assert "sc_DockQ_ef2full" in done.stderr


# ── Fixes found by running the skill end to end against live prod ────────────
# Every test below reproduced a defect that shipped in the merged skill. The
# first one is the worst kind: a refusal that was written, documented, tested
# by nothing, and dead.


def test_a_recompute_mismatch_names_the_row_instead_of_crashing(tmp_path: Path) -> None:
    """The halt in §7 must PRINT the row whose gates did not reproduce.

    The kernel declares `mismatches` as a list of design-id STRINGS, but this
    branch read them as mappings -- so the halt raised AttributeError and the
    operator got a traceback instead of the id and the gate. It fired on every
    mismatch, i.e. exactly whenever the check actually caught something.
    """
    rows = _population(4)
    # Carry a liability number that cannot reproduce from this row's own sequence.
    rows[1]["liability_max_homopolymer_run"] = 999
    rows[1]["liability_min_window_entropy_bits"] = 0.001
    pool = tmp_path / "candidates.json"
    pool.write_text(json.dumps(rows))

    done = _run("select_panel.py", str(pool), "--gate", str(_gate(tmp_path)),
                "--panel-size", "4", "--out", str(tmp_path / "sheet.csv"))

    assert "Traceback" not in done.stderr, done.stderr
    assert "AttributeError" not in done.stderr
    out = done.stdout + done.stderr
    if "HALTED" in out:
        assert "p1" in out, f"the halt must name the row: {out}"
        assert "liability" in out


def test_a_duplicate_design_id_is_refused_cleanly(tmp_path: Path) -> None:
    """A repeated id makes the caps, the ledger and the trace ambiguous.

    campaign_gates.py already refused this in a clean paragraph one stage
    earlier; the selector let the kernel's bare ValueError escape instead.
    """
    rows = _population(3)
    rows[2]["design_id"] = rows[0]["design_id"]
    pool = tmp_path / "dupe.json"
    pool.write_text(json.dumps(rows))

    done = _run("select_panel.py", str(pool), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "sheet.csv"))

    assert done.returncode != 0
    assert "Traceback" not in done.stderr, done.stderr
    assert "duplicate design_id" in done.stdout + done.stderr


def test_an_empty_panel_names_why_the_rows_were_unranked(tmp_path: Path) -> None:
    """The row-intrinsic checks drop rows BEFORE selection.

    So a pool emptied entirely that way has empty `rejection_counts`, and the
    refusal used to print no reason at all -- on precisely the run where the
    operator has nothing else to go on.
    """
    rows = _population(3)
    for row in rows:
        row["opt_round"] = ""
    pool = tmp_path / "allbad.json"
    pool.write_text(json.dumps(rows))

    done = _run("select_panel.py", str(pool), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "sheet.csv"))

    out = done.stdout + done.stderr
    assert "no candidate survived" in out
    assert "unranked because" in out, f"the refusal must name a reason: {out}"
    assert "opt_round" in out


def _gated(tmp_path: Path, rows: list[dict]) -> list[dict]:
    pool = tmp_path / "pool.json"
    pool.write_text(json.dumps(rows))
    out = tmp_path / "gates.csv"
    done = _run("campaign_gates.py", str(pool), "--out", str(out))
    assert out.exists(), done.stdout + done.stderr
    import csv
    with out.open() as fh:
        return list(csv.DictReader(fh))


def test_a_reject_reason_is_not_written_into_the_not_run_column(tmp_path: Path) -> None:
    """The kernel returns a `reason` for ANY verdict, not only NOT_RUN.

    Folding them together wrote REJECT rationales into a column named
    `gate_not_run_reason`, so a consumer filtering on it counted refused
    designs as gates that never ran -- the exact confusion every NOT_RUN in
    this script exists to prevent.
    """
    rows = _gated(tmp_path, [
        {"design_id": f"d{i}", "sequence": seq}
        for i, seq in enumerate(_SEQUENCES)
    ])
    for row in rows:
        if row.get("gate_not_run_reason"):
            for gate in ("structural_plausibility_verdict", "target_mimic_verdict"):
                assert row.get(gate) != "REJECT" or row.get("gate_reject_reason"), (
                    f"{row['design_id']}: a REJECT rationale landed in the "
                    f"not-run column: {row['gate_not_run_reason']!r}"
                )


def test_an_unclassifiable_fold_is_not_a_fourth_verdict_token(tmp_path: Path) -> None:
    """`selection.md` allows PASS / REJECT / NOT_RUN and nothing else.

    The fold classifier does not RAISE when it cannot classify -- it returns a
    value whose str() is "unknown" -- so the except branch never fired and a
    reasonless fourth token reached the sheet.
    """
    rows = _gated(tmp_path, [
        {"design_id": f"d{i}", "sequence": seq}
        for i, seq in enumerate(_SEQUENCES)
    ])
    for row in rows:
        fold = (row.get("fold_class") or "").strip()
        assert fold.lower() != "unknown", "an unclassifiable fold must be NOT_RUN, not 'unknown'"
        if fold == "NOT_RUN":
            assert row.get("fold_class_not_run_reason"), (
                f"{row['design_id']}: NOT_RUN with no reason"
            )


def test_the_drift_check_defaults_to_the_ref_it_was_vendored_from() -> None:
    """`--ref` defaulted to `main`, where the source package does not exist.

    So the drift detector the manifest exists to enable was inoperable out of
    the box, and failed as an unhandled CalledProcessError rather than a
    diagnosis. The default is now read back from the manifest itself.
    """
    tool = ROOT / "tools/vendor_campaign_kernel.py"
    spec = importlib.util.spec_from_file_location("vendor_tool", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    manifest = (MCP_SCRIPTS / "_kernel/VENDORED.md").read_text()
    assert f"- ref: `{module.recorded_ref()}`" in manifest
    assert module.recorded_ref() != "main"


def test_a_pool_of_one_repeated_sequence_is_refused(tmp_path: Path) -> None:
    """Measured on live prod, not hypothesised.

    RFdiffusion's `seq` column joins binder and target, and its own schema
    documents them in the OPPOSITE order from the one it delivers -- a real
    PD-L1 run returned target-first while the description said binder-first.
    Following the documentation therefore yields a pool in which every row is
    the target: legal length, ordinary composition, and it passes every other
    check in this script.
    """
    target = "FTVTVPKDLYVVEYGSNMTIECKFPVEKQLDLAALIVYWEMEDKNIIQFVHGEEDLKVQHSSYRQ"
    pool = tmp_path / "wrong_half.json"
    pool.write_text(json.dumps(
        [{"design_id": f"d{i}", "sequence": target} for i in range(8)]
    ))

    done = _run("campaign_gates.py", str(pool), "--out", str(tmp_path / "g.csv"))

    assert done.returncode != 0, "a pool of one repeated sequence must fail closed"
    out = done.stdout + done.stderr
    assert "identical" in out
    assert "TARGET" in out, f"the refusal must name the cause: {out}"


def test_a_legitimately_varied_pool_is_not_caught_by_that_check(tmp_path: Path) -> None:
    """The guard must not fire on a real pool that happens to share some rows."""
    rows = [{"design_id": f"d{i}", "sequence": seq}
            for i, seq in enumerate(_SEQUENCES)]
    rows.append({"design_id": "dup", "sequence": _SEQUENCES[0]})  # a legitimate repeat
    pool = tmp_path / "varied.json"
    pool.write_text(json.dumps(rows))

    done = _run("campaign_gates.py", str(pool), "--out", str(tmp_path / "g.csv"))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "identical" not in done.stdout


def test_a_row_scored_on_a_different_sequence_halts(tmp_path: Path) -> None:
    """The one defect no gate can catch, reproduced for real during verification.

    Every gate recomputes against the row's OWN sequence, so a row whose SCORES
    came from a different molecule reproduces perfectly and ranks on numbers
    that are not its own. Hand-building a scoring submission produced exactly
    this twice in one small run: one row mislabelled, and one whose submitted
    sequence matched no design anywhere.
    """
    rows = _population(3)
    rows[1]["scored_sequence"] = _SEQUENCES[2]          # folded a different design
    rows[0]["scored_sequence"] = rows[0]["sequence"]
    rows[2]["scored_sequence"] = rows[2]["sequence"]
    pool = tmp_path / "swapped.json"
    pool.write_text(json.dumps(rows))

    done = _run("select_panel.py", str(pool), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "sheet.csv"))

    assert done.returncode != 0
    out = done.stdout + done.stderr
    assert "not among the chains" in out
    assert "p1" in out, f"the halt must name the row: {out}"


def test_matching_scored_sequences_pass_and_absence_warns(tmp_path: Path) -> None:
    """Present-and-equal must not trip; absent must not be silent."""
    ok = _population(3)
    for r in ok:
        r["scored_sequence"] = r["sequence"]
    good = tmp_path / "ok.json"
    good.write_text(json.dumps(ok))
    done = _run("select_panel.py", str(good), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "a.csv"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "not among the chains" not in done.stdout + done.stderr

    silent = tmp_path / "nocol.json"
    silent.write_text(json.dumps(_population(3)))
    done = _run("select_panel.py", str(silent), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "b.csv"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "no row carries scored_sequence" in done.stderr


def test_a_0_100_plddt_against_a_0_1_floor_halts(tmp_path: Path) -> None:
    """The vacuous-gate case: a Protenix pLDDT judged by an ESMFold2 floor.

    Measured on real rows for the same construct -- ESMFold2 reports mean pLDDT
    on 0-1 (0.7884) and Protenix on 0-100 (86.75). Against the frozen 0.70
    floor every 0-100 value clears, so the foldability gate reports PASS on
    every design while rejecting nothing. Refuse rather than rescale: only the
    campaign knows which arm produced the column.
    """
    rows = _population(3)
    for row, value in zip(rows, (86.75, 91.2, 78.4)):
        row["monomer_plddt"] = value
    src = tmp_path / "hundreds.json"
    src.write_text(json.dumps(rows))

    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "sheet.csv"))

    assert done.returncode != 0
    out = done.stdout + done.stderr
    assert "monomer_plddt exceeds 1.0" in out, out
    assert "p0" in out, f"the halt must name the rows: {out}"


def test_the_plddt_scale_halt_leaves_a_consistent_pool_alone(tmp_path: Path) -> None:
    """It must fire on the MISMATCH, not on either scale used consistently."""
    on_0_1 = _population(3)
    for row, value in zip(on_0_1, (0.7884, 0.81, 0.74)):
        row["monomer_plddt"] = value
    src = tmp_path / "unit.json"
    src.write_text(json.dumps(on_0_1))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "a.csv"))
    assert done.returncode == 0, done.stdout + done.stderr

    # The same 0-100 values are fine once the floor is declared on that scale.
    on_0_100 = _population(3)
    for row, value in zip(on_0_100, (86.75, 91.2, 78.4)):
        row["monomer_plddt"] = value
    src = tmp_path / "hundreds-ok.json"
    src.write_text(json.dumps(on_0_100))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--monomer-floor", "70",
                "--out", str(tmp_path / "b.csv"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "monomer_plddt exceeds 1.0" not in done.stdout + done.stderr


def test_a_missing_ref_is_diagnosed_not_a_traceback(tmp_path: Path) -> None:
    """The ordinary failure -- the kernel lives on a branch a checkout may lack.

    It used to surface as an unhandled CalledProcessError, which named neither
    the ref nor the path, on the one command whose job is detecting drift.
    """
    repo = tmp_path / "agent"
    repo.mkdir()
    for cmd in (("init", "-q"), ("config", "user.email", "t@t"),
                ("config", "user.name", "t"), ("commit", "-q", "--allow-empty", "-m", "x")):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True, capture_output=True)

    done = subprocess.run(
        [sys.executable, str(ROOT / "tools/vendor_campaign_kernel.py"),
         "--agent-repo", str(repo), "--check"],
        capture_output=True, text=True,
    )
    assert done.returncode != 0
    out = done.stdout + done.stderr
    assert "Traceback" not in out, out
    assert "campaign/cda/subagents" in out, out
    assert "--ref" in out, out


def _helix_pdb(path: Path, n: int = 30, chain: str = "B", annotated: bool = True) -> Path:
    """A minimal CA-only chain, optionally carrying its own HELIX record.

    The kernel resolves secondary structure from HELIX/SHEET records when the
    file has them and returns "unknown" when nothing resolves, so this builds
    both the classifiable and the unclassifiable case without any structure
    dependency.
    """
    lines = []
    if annotated:
        lines.append(f"HELIX    1   1 ALA {chain}   1  ALA {chain}  {n:>3}  1{' ':>36}{n:>5}")
    for i in range(1, n + 1):
        lines.append(
            f"ATOM  {i:>5}  CA  ALA {chain}{i:>4}    "
            f"{i * 1.5:>8.3f}{0.0:>8.3f}{0.0:>8.3f}  1.00 50.00           C"
        )
    lines.append("END")
    path.write_text("\n".join(lines) + "\n")
    return path


def test_a_classified_fold_keeps_its_label(tmp_path: Path) -> None:
    """`dssp_fold_class` returns a STRING, not an object.

    Reading it through `getattr(fold, "fold_class", ...)` yields None for every
    real classification, so the whole column collapsed to NOT_RUN and took the
    evidence for the >=10% non-all-alpha diversity target with it.
    """
    pdb = _helix_pdb(tmp_path / "design.pdb")
    rows = _gated(tmp_path, [
        {"design_id": f"d{i}", "sequence": seq,
         "designed_structure_path": str(pdb), "binder_chain": "B"}
        for i, seq in enumerate(_SEQUENCES)
    ])
    assert rows, "the gate wrote no rows"
    for row in rows:
        assert row["fold_class"] == "all_alpha", (
            f"{row['design_id']}: a classified fold must keep its label, got "
            f"{row['fold_class']!r}"
        )
        assert not row.get("fold_class_not_run_reason"), row


def test_an_unclassifiable_structure_is_still_not_run(tmp_path: Path) -> None:
    """The other half: "unknown" is a non-classification and must say so.

    The kernel returns it rather than raising, so the except branch never fires
    and a reasonless fourth token would otherwise reach the sheet.

    The unclassifiable input has to be unclassifiable for EVERY resolver. An
    earlier version used a helix with its HELIX record stripped, which is only
    unreadable when biotite is absent -- so it passed in CI (which installs
    numpy but not biotite) and failed the moment biotite was installed. That
    is a test pinned to a missing dependency rather than to behaviour. Naming
    a chain the file does not contain leaves nothing to resolve either way.
    """
    pdb = _helix_pdb(tmp_path / "flat.pdb", annotated=False, chain="B")
    rows = _gated(tmp_path, [
        {"design_id": f"d{i}", "sequence": seq,
         "designed_structure_path": str(pdb), "binder_chain": "Z"}   # no chain Z in the file
        for i, seq in enumerate(_SEQUENCES)
    ])
    assert rows
    for row in rows:
        assert row["fold_class"] == "NOT_RUN", row
        assert row["fold_class_not_run_reason"], f"{row['design_id']}: NOT_RUN with no reason"


def test_a_complex_scored_sequence_matches_its_binder_chain(tmp_path: Path) -> None:
    """The recommended scoring route folds `TARGET:BINDER` as one record.

    So the stored input read back from the platform carries both chains while
    the row carries the binder alone. A plain equality check calls every
    correctly scored complex a mismatch and halts on the good case.
    """
    target = "FTVTVPKDLYVVEYGSNMTIECKFPVEKQLDLAALIVYWEMEDKNIIQFVHGEEDLKVQHSSYRQ"
    rows = _population(3)
    for row in rows:
        row["scored_sequence"] = f"{target}:{row['sequence']}"
    src = tmp_path / "complex.json"
    src.write_text(json.dumps(rows))

    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "sheet.csv"))
    assert done.returncode == 0, done.stdout + done.stderr

    # ...and a binder that is in NO chain of what was folded still halts.
    wrong = _population(3)
    for row in wrong:
        row["scored_sequence"] = f"{target}:{_SEQUENCES[0]}"
    bad = tmp_path / "wrong.json"
    bad.write_text(json.dumps(wrong))
    done = _run("select_panel.py", str(bad), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "b.csv"))
    assert done.returncode != 0
    assert "not among the chains" in done.stdout + done.stderr


def test_the_plddt_scale_halt_does_not_need_numpy(tmp_path: Path) -> None:
    """It compares two numbers, so it must not sit behind the kernel import.

    Sited beside the recompute it was inside `if sr is not None`, which is
    False on exactly the stock machine with no numpy that SKILL.md calls the
    common case -- absent from every run that most needed it.
    """
    rows = _population(3)
    for row, value in zip(rows, (86.75, 91.2, 78.4)):
        row["monomer_plddt"] = value
    src = tmp_path / "hundreds.json"
    src.write_text(json.dumps(rows))

    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--skip-recompute",
                "--out", str(tmp_path / "sheet.csv"))
    assert done.returncode != 0, done.stdout + done.stderr
    assert "monomer_plddt exceeds 1.0" in done.stdout + done.stderr


def test_partial_scored_sequence_coverage_is_disclosed(tmp_path: Path) -> None:
    """A non-empty `scored` silenced the "nothing verifies this" warning.

    Partial coverage is MORE suspicious than none -- the read-back ran and
    these rows escaped it -- so it must not be quieter than an unannotated
    pool.
    """
    rows = _population(3)
    rows[0]["scored_sequence"] = rows[0]["sequence"]
    src = tmp_path / "partial.json"
    src.write_text(json.dumps(rows))

    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "sheet.csv"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "2 of 3 row(s) carry no scored_sequence" in done.stderr, done.stderr
    for did in ("p1", "p2"):
        assert did in done.stderr, f"the warning must name {did}: {done.stderr}"


def test_a_0_1_plddt_against_a_0_100_floor_also_halts(tmp_path: Path) -> None:
    """The mirror of the units halt.

    It fails loudly rather than silently -- every design lands under the floor
    -- so it is the less dangerous direction. But with `--skip-recompute`, or
    no numpy, nothing recomputes the floor at all and the rows ship on carried
    verdicts with the declared floor never reconciled against the column.
    """
    rows = _population(3)
    for row, value in zip(rows, (0.7884, 0.81, 0.74)):
        row["monomer_plddt"] = value
    src = tmp_path / "units.json"
    src.write_text(json.dumps(rows))

    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--monomer-floor", "70",
                "--skip-recompute", "--out", str(tmp_path / "sheet.csv"))
    assert done.returncode != 0, done.stdout + done.stderr
    out = done.stdout + done.stderr
    assert "at or below 1.0" in out, out
    assert "p0" in out, out


def test_ids_that_differ_only_in_type_are_still_duplicates(tmp_path: Path) -> None:
    """Reproduced, not reasoned about.

    The kernel stringifies before its own duplicate check, so numeric 1 beside
    string "1" walked past a raw-value set here and hit
    `ValueError: duplicate design_id '1'` inside selection -- a bare traceback
    out of the one path this refusal exists to keep clean.
    """
    rows = _population(3)
    rows[0]["design_id"] = 1
    rows[1]["design_id"] = "1"
    src = tmp_path / "mixed_ids.json"
    src.write_text(json.dumps(rows))

    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--out", str(tmp_path / "sheet.csv"))
    assert done.returncode != 0
    out = done.stdout + done.stderr
    assert "Traceback" not in out, out
    assert "duplicate design_id 1" in out, out


def test_one_catastrophic_prediction_is_not_a_units_mismatch(tmp_path: Path) -> None:
    """The reverse units check is an INFERENCE, so it demands unanimity.

    A value above 1.0 is impossible on a 0-1 scale, so one proves a mismatch.
    A value at or below 1.0 is only astonishing on a 0-100 scale, so refusing
    the run over a single catastrophic prediction would abort a correctly
    declared campaign instead of letting the monomer gate reject that row.
    """
    rows = _population(3)
    for row, value in zip(rows, (86.75, 91.2, 0.9)):   # one hopeless design
        row["monomer_plddt"] = value
    src = tmp_path / "one_bad.json"
    src.write_text(json.dumps(rows))

    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "3", "--monomer-floor", "70",
                "--skip-recompute", "--out", str(tmp_path / "sheet.csv"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "at or below 1.0" not in done.stdout + done.stderr


def test_an_unsplit_pool_gets_the_alphabet_refusal_not_the_split_one(tmp_path: Path) -> None:
    """The sharper refusal has to win, exactly as the guard's comment claims.

    An UN-SPLIT `TARGET/BINDER` string is identical on every row and of legal
    length, so the identical-sequence check (which runs first) would diagnose a
    chain split -- true in spirit, but it names the wrong repair and hides the
    stray `/` that says what actually happened.
    """
    unsplit = "MKQLEDKVEELLSKNYHLENEVARLKKLVGERG/FTVTVPKDLYVVEYGSNMTIECKFPVEKQ"
    pool = tmp_path / "unsplit.json"
    pool.write_text(json.dumps(
        [{"design_id": f"d{i}", "sequence": unsplit} for i in range(4)]
    ))
    done = _run("campaign_gates.py", str(pool), "--out", str(tmp_path / "g.csv"))
    assert done.returncode != 0
    out = done.stdout + done.stderr
    assert "non-residue characters" in out, out
    assert "identical" not in out, f"the sharper refusal must win: {out}"


def test_a_not_run_mimic_verdict_cannot_reach_the_panel(tmp_path: Path) -> None:
    """The absolute gate was bypassed by a column-name mismatch.

    `select_with_diversity_caps` resolves the ban from `row["target_mimic"]`,
    falling back to the bare `target_mimic_tm_max` number. The port wrote the
    verdict as `target_mimic_verdict` -- a name the ban never reads -- so a row
    whose mimic screen explicitly did NOT run shipped on the strength of its
    number, and the summary counted zero NOT_RUN mimic rows.

    Measured before the fix, against the PASS control below: both arms shipped
    3 of 3. The control is what makes this a test and not a coincidence.
    """
    def arm(verdict):
        rows = _population(3)
        for row in rows:
            row["target_mimic"] = verdict
            row["target_mimic_verdict"] = verdict
            row["target_mimic_tm_max"] = 0.31        # below the ban threshold
        src = tmp_path / f"{verdict}.json"
        src.write_text(json.dumps(rows))
        return _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                    "--panel-size", "3", "--out", str(tmp_path / f"{verdict}.csv"),
                    "--json")

    control = arm("PASS")
    assert control.returncode == 0, control.stdout + control.stderr
    assert json.loads(control.stdout)["panel_size_shipped"] == 3

    done = arm("NOT_RUN")
    assert done.returncode != 0, (
        "a NOT_RUN mimic gate must not ship: " + done.stdout + done.stderr
    )
    assert "NOT_RUN" in done.stdout + done.stderr


def test_the_gate_writes_the_mimic_verdict_where_the_kernel_reads_it(tmp_path: Path) -> None:
    """The other half: the gate has to emit the kernel's own column name."""
    rows = _gated(tmp_path, [
        {"design_id": f"d{i}", "sequence": seq}
        for i, seq in enumerate(_SEQUENCES)
    ])
    assert rows
    for row in rows:
        carried = str(row.get("target_mimic") or "")
        assert carried, f"{row['design_id']}: the kernel reads `target_mimic` and it is absent"
        # No reference chains in this fixture, so the screen did not run and the
        # verdict word -- not a number -- has to be what the ban sees.
        assert carried == "NOT_RUN" == row["target_mimic_verdict"], (
            f"{row['design_id']}: an un-run screen must carry NOT_RUN, got {carried!r}"
        )


def _helix_3d_pdb(path: Path, n: int = 40, chain: str = "B") -> Path:
    """A real 3-D helix, so TM-align has something to superpose."""
    import math
    lines = [f"HELIX    1   1 ALA {chain}   1  ALA {chain}  {n:>3}  1{' ':>36}{n:>5}"]
    for i in range(1, n + 1):
        t = i * 100.0 * math.pi / 180.0
        x, y, z = 2.3 * math.cos(t), 2.3 * math.sin(t), 1.5 * i
        lines.append(
            f"ATOM  {i:>5}  CA  ALA {chain}{i:>4}    "
            f"{x:>8.3f}{y:>8.3f}{z:>8.3f}  1.00 50.00           C"
        )
    lines.append("END")
    path.write_text("\n".join(lines) + "\n")
    return path


def test_the_measurement_not_the_word_goes_where_the_ban_reads(tmp_path: Path) -> None:
    """The regression the previous fix introduced, pinned at the GATE.

    The kernel prefers a verdict WORD in `target_mimic` over the numeric
    fallback, so writing the word there let a stale or misjoined PASS outrank a
    measured TM at or above the ban threshold -- and nothing downstream re-runs
    the mimic screen to catch it. Where the screen produced a measurement, that
    measurement is what must reach the ban.

    Scoring a design against ITSELF is the cheap way to force a real number:
    TM = 1.0, verdict REJECT, so the two candidate values are distinguishable.
    """
    pdb = _helix_3d_pdb(tmp_path / "design.pdb")
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps([[str(pdb), "B"]]))
    pool = tmp_path / "pool.json"
    pool.write_text(json.dumps([{
        "design_id": "d0", "sequence": _SEQUENCES[0],
        "designed_structure_path": str(pdb), "binder_chain": "B",
    }]))
    out = tmp_path / "gates.csv"
    done = _run("campaign_gates.py", str(pool), "--reference-chains", str(refs),
                "--out", str(out))
    assert out.exists(), done.stdout + done.stderr

    import csv as _csv

    def number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    row = next(iter(_csv.DictReader(out.open())))
    assert row["target_mimic_verdict"] == "REJECT", row
    assert number(row["target_mimic_tm_max"]) is not None, row
    carried = row["target_mimic"]
    assert number(carried) is not None, (
        "the ban must receive the MEASUREMENT, not the verdict word: "
        f"target_mimic={carried!r}"
    )
    assert number(carried) == number(row["target_mimic_tm_max"]), row


def test_supplied_dssp_codes_reach_the_fold_classifier(tmp_path: Path) -> None:
    """The canonical path has to be reachable from the gate, not just the kernel.

    The target is defined "not-all-alpha under DSSP", but the classifier's only
    dependency-free fallback is P-SEA -- a different assignment. Generator PDBs
    carry no HELIX/SHEET records, so without forwarding `ss_codes` the run fell
    to P-SEA or to NOT_RUN no matter what DSSP the campaign had in hand.
    """
    pdb = _helix_pdb(tmp_path / "plain.pdb", n=40, annotated=False, chain="B")
    # BOTH shapes a pool can carry. A DSSP tool -- and biotite's own
    # annotate_sse -- emits per-residue codes as a LIST, and str() on that
    # yields "['E', 'E', ...]", whose punctuation the kernel reads as coil:
    # measured, 40 strand residues give all_beta as a list and `other` once
    # coerced. The scalar string is what a CSV pool carries.
    for tag, codes in (("scalar", "E" * 40), ("list", ["E"] * 40)):
        rows = _gated(tmp_path, [
            {"design_id": f"{tag}-d{i}", "sequence": seq,
             "designed_structure_path": str(pdb), "binder_chain": "B", "ss_codes": codes}
            for i, seq in enumerate(_SEQUENCES)
        ])
        assert rows, tag
        for row in rows:
            assert row["fold_class"] == "all_beta", (
                f"{tag} {row['design_id']}: supplied DSSP codes must decide the class, "
                f"got {row['fold_class']!r}"
            )
            assert row.get("fold_ss_method") == "supplied", row


def test_every_classified_row_names_the_method_that_resolved_it(tmp_path: Path) -> None:
    """A diversity figure with no method beside it is not evidence.

    The target is defined under DSSP; the classifier's last resort is P-SEA.
    Stamping the method only when the pool supplied codes left the fallback
    cases unlabelled, so a P-SEA class could be reported as DSSP-derived.
    """
    annotated = _helix_pdb(tmp_path / "withrecords.pdb", chain="B")          # HELIX present
    rows = _gated(tmp_path, [
        {"design_id": f"r{i}", "sequence": seq,
         "designed_structure_path": str(annotated), "binder_chain": "B"}
        for i, seq in enumerate(_SEQUENCES)
    ])
    assert rows
    for row in rows:
        assert row["fold_class"] == "all_alpha", row
        assert row["fold_ss_method"] == "pdb-records", (
            f"{row['design_id']}: a class resolved from the file's own records must say so, "
            f"got {row.get('fold_ss_method')!r}"
        )


# ── Anthropic L81: the novelty gate the port had nailed shut ────────────────
#
# `campaign_gates.py` wrote `novelty_verdict = NOT_RUN` unconditionally, so the
# campaign's most consequential pre-scoring filter never ran on any design --
# while a complete implementation sat vendored in `_kernel/novelty_gate.py`.
# Three of L81's four arms need no external search at all.

# Human ubiquitin (UniProt P0CG47/P0CG48). L81 calls it out by name because it
# "often emerges with short terminal extensions", which is why the gate detects
# it by local alignment rather than exact match.
_UBIQUITIN = (
    "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
)
_TARGET_PDL1 = (
    "AFTVTVPKDLYVVEYGSNMTIECKFPVEKQLDLAALIVYWEMEDKNIIQFVHGEEDLKVQHSSYRQRARLLKDQ"
    "LSLGNAALQITDVKLQDAGVYRCMISYGGADYKRITVKVNAPY"
)


def _gates_rows(tmp_path: Path, pool: list[dict], *args: str):
    """Run campaign_gates over a pool and return (completed_process, rows)."""
    pool_path = tmp_path / "pool.json"
    pool_path.write_text(json.dumps(pool))
    out = tmp_path / "gates.csv"
    done = _run("campaign_gates.py", str(pool_path), "--out", str(out), *args)
    rows = []
    if out.exists():
        import csv

        rows = list(csv.DictReader(out.read_text().splitlines()))
    return done, rows


def test_a_design_that_is_really_ubiquitin_is_rejected_with_no_search_job(
    tmp_path: Path,
) -> None:
    """The measured escape, now caught locally.

    A generator returned a 75-residue "de novo design" whose first 40 residues
    were ubiquitin's exactly. It passed liability cleanly -- ubiquitin is a
    perfectly well-behaved protein -- and the port marked novelty NOT_RUN, so
    nothing kept it out. No UniRef90, no corpus and no network is needed to
    catch it: the kernel carries the ubiquitin subject itself.
    """
    design = _UBIQUITIN[:40] + "GSGSEEALKKAEELLKKAEELLKKGSG"
    done, rows = _gates_rows(tmp_path, [{"design_id": "d_ubq", "sequence": design}])
    assert done.returncode == 0, done.stderr
    assert rows[0]["novelty_verdict"] == "REJECT"
    assert rows[0]["novelty_top_subject_kind"] == "ubiquitin"
    # The numbers that decided it, not just the word. A verdict with an empty
    # evidence cell beside it is unfalsifiable -- and this column WAS empty
    # first time round, because it was read under a key the kernel never writes.
    assert float(rows[0]["novelty_top_identity"]) == 1.0
    assert int(rows[0]["novelty_top_aligned_columns"]) == 40


def test_a_design_that_is_a_slice_of_the_campaigns_own_target_is_rejected(
    tmp_path: Path,
) -> None:
    """L81's self-similarity arm, against the target the campaign froze.

    This is the arm that catches a target-fold mimic at the SEQUENCE level,
    before any co-folding spend and independently of the structural TM screen.
    It runs off the reference chains the pool already supplies.
    """
    refs = tmp_path / "refs.json"
    refs.write_text(
        json.dumps(
            [{"pdb": "ref.pdb", "chain": "A", "sequence": _TARGET_PDL1,
              "role": "target"}]
        )
    )
    done, rows = _gates_rows(
        tmp_path,
        [{"design_id": "d_mimic", "sequence": _TARGET_PDL1[10:80]}],
        "--reference-chains", str(refs),
    )
    assert done.returncode == 0, done.stderr
    assert rows[0]["novelty_verdict"] == "REJECT"
    assert rows[0]["novelty_top_subject_kind"] == "target_chain"


def test_a_reference_with_no_sequence_leaves_the_self_similarity_arm_not_run(
    tmp_path: Path,
) -> None:
    """The pair form feeds the structural screen only, and says so.

    A `[pdb, chain]` reference carries no sequence, and the sequence is NOT
    inferred from the PDB -- a silently mis-parsed reference is a gate pointed
    at the wrong molecule. The arm is disclosed as un-run rather than passing.
    """
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps([["ref.pdb", "A"]]))
    done, rows = _gates_rows(
        tmp_path,
        [{"design_id": "d1", "sequence": _TARGET_PDL1[10:80]}],
        "--reference-chains", str(refs),
    )
    assert done.returncode == 0, done.stderr
    assert "target_chain" in rows[0]["novelty_arms_not_run"]
    assert rows[0]["novelty_verdict"] != "PASS"


def test_a_clean_design_is_not_run_rather_than_passed_without_the_corpus(
    tmp_path: Path,
) -> None:
    """The combination rule: clean-but-incomplete is NOT_RUN, never PASS.

    L79 stages the known-binder corpus in the first hour. Until it is, a design
    that tripped no arm has still not been screened against a required subject
    set, and calling that PASS would report a gate as run while filtering
    against nothing.
    """
    done, rows = _gates_rows(
        tmp_path, [{"design_id": "d_clean", "sequence": _SEQUENCES[1]}]
    )
    assert done.returncode == 0, done.stderr
    assert rows[0]["novelty_verdict"] == "NOT_RUN"
    assert "known_binder_corpus" in rows[0]["novelty_arms_not_run"]


def test_a_malformed_uniref90_hits_file_is_refused_not_downgraded_to_not_run(
    tmp_path: Path,
) -> None:
    """A bad input file must never be able to discard a rejection already made.

    Measured while wiring this up: a hits file whose columns were named
    `gapped_identity`/`query_coverage` instead of MMseqs2's own made the kernel
    raise INSIDE the verdict, after the known-binder arm had already rejected
    the design. The per-row catch turned that raise into NOT_RUN and the
    standing REJECT went with it -- a bad file silently loosening the gate.
    So the file is judged once, at startup, and an unusable hit refuses the run.
    """
    hits = tmp_path / "hits.json"
    hits.write_text(
        json.dumps({"d1": [{"subject_id": "U1", "gapped_identity": 0.92,
                            "query_coverage": 0.88}]})
    )
    done, _ = _gates_rows(
        tmp_path,
        [{"design_id": "d1", "sequence": _SEQUENCES[1]}],
        "--uniref90-hits", str(hits),
    )
    assert done.returncode != 0
    combined = done.stdout + done.stderr
    assert "unusable hit" in combined
    # Name the repair, not just the fault.
    assert "fident" in combined and "qcov" in combined


def test_precomputed_uniref90_hits_reach_the_verdict(tmp_path: Path) -> None:
    """The one limb that cannot run locally, joined back in from a search job."""
    hits = tmp_path / "hits.json"
    hits.write_text(
        json.dumps({"d1": [{"target": "UniRef90_Q9XYZ1", "fident": 0.92,
                            "qcov": 0.88}]})
    )
    done, rows = _gates_rows(
        tmp_path,
        [{"design_id": "d1", "sequence": _SEQUENCES[1]}],
        "--uniref90-hits", str(hits), "--novelty-tier", "final",
    )
    assert done.returncode == 0, done.stderr
    assert rows[0]["novelty_verdict"] == "REJECT"
    assert rows[0]["novelty_top_subject"] == "UniRef90_Q9XYZ1"


def test_the_final_novelty_tier_refuses_without_uniref90_hits(
    tmp_path: Path,
) -> None:
    """L79 requires the full-UniRef90 check before any row reaches the sheet.

    Asking for the final tier with nothing to judge would mark every design
    NOT_RUN and rank none -- a campaign that looks gated and ships no panel.
    """
    done, _ = _gates_rows(
        tmp_path,
        [{"design_id": "d1", "sequence": _SEQUENCES[1]}],
        "--novelty-tier", "final",
    )
    assert done.returncode != 0
    assert "--novelty-tier final requires --uniref90-hits" in (
        done.stdout + done.stderr
    )


def test_lcp_score_is_recorded_and_penalises_low_complexity(
    tmp_path: Path,
) -> None:
    """L73's mandatory sequence restraint, recorded per design.

    Reported, never a gate: the protocol makes LCP a restraint on sequence
    design and a recorded metric, not a rejection threshold. Higher is worse.
    """
    done, rows = _gates_rows(
        tmp_path,
        [
            {"design_id": "d_clean", "sequence": _SEQUENCES[1]},
            {"design_id": "d_repeat", "sequence": "EK" * 35},
        ],
    )
    assert done.returncode == 0, done.stderr
    by_id = {r["design_id"]: r for r in rows}
    clean = float(by_id["d_clean"]["lcp_score"])
    repeat = float(by_id["d_repeat"]["lcp_score"])
    assert repeat > clean, (repeat, clean)


def test_novelty_faces_the_constant_gate_warning_like_every_other_gate(
    tmp_path: Path,
) -> None:
    """It was exempt while it could not run. It can run now, so the exemption goes.

    "A gate that passes everything, fails everything, or returns a constant is
    broken until investigated" has to cover novelty too, or the one gate whose
    whole job is rejecting copies is also the one nothing checks.
    """
    src = (MCP_SCRIPTS / "campaign_gates.py").read_text()
    assert 'always_not_run = {"monomer_foldability"}' in src
    assert '"novelty"' not in src.split("always_not_run =")[1].split("\n")[0]


# ── round 4: the fold_ss_method label had to be ASKED, not guessed ──────────


def _gates_module():
    """Import campaign_gates so its helpers can be unit-tested directly."""
    sys.path.insert(0, str(MCP_SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "campaign_gates_under_test", MCP_SCRIPTS / "campaign_gates.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _two_chain_pdb(records_on: str = "T", t_res: int = 40, b_res: int = 60) -> str:
    """A two-chain complex whose HELIX record annotates only `records_on`."""
    lines = [
        f"HELIX    1   1 ALA {records_on}    2  ALA {records_on}   14  1"
        f"{'':34}13"
    ]
    serial = 0

    def cas(chain: str, count: int) -> list[str]:
        nonlocal serial
        out = []
        for i in range(count):
            serial += 1
            x, y, z = i * 1.5, (i % 3) * 1.2, (i % 2) * 0.9
            out.append(
                f"ATOM  {serial:5d}  CA  ALA {chain}{i + 1:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 50.00           C"
            )
        return out

    lines += cas("T", t_res) + cas("B", b_res)
    return "\n".join(lines) + "\nEND\n"


def test_records_on_another_chain_are_not_reported_as_this_chains_method(
    kernel,
) -> None:
    """P-SEA output must never be labelled record-derived.

    The first version of this check grepped the whole file for a line starting
    HELIX or SHEET. The kernel keeps only records whose chain matches the one
    being classified, so on a complex whose records annotate the TARGET chain
    the binder falls through to P-SEA -- while the file-wide grep still said
    `pdb-records`. The diversity target is defined under DSSP and P-SEA is a
    different assignment, so that label is the whole evidentiary claim.

    Unit-tested on the helper rather than end to end: the fallback only really
    runs when biotite is installed, and CI does not install it.
    """
    helpers, _ = kernel
    gates = _gates_module()
    body = _two_chain_pdb(records_on="T")

    # Ground truth from the kernel's own resolver.
    assert helpers._ss_from_pdb_records(body, "T") != ""
    assert helpers._ss_from_pdb_records(body, "B") == ""

    assert gates._resolved_ss_method(helpers, body, "T", None) == "pdb-records"
    assert gates._resolved_ss_method(helpers, body, "B", None) == "biotite-psea"
    # Supplied codes short-circuit both, on either chain.
    assert gates._resolved_ss_method(helpers, body, "B", ["H"] * 60) == "supplied"


def _ss_pool(tmp_path: Path, codes, chain: str = "B", res: int = 60):
    pdb = tmp_path / "complex.pdb"
    pdb.write_text(_two_chain_pdb(records_on="T", b_res=res))
    pool = tmp_path / "pool.json"
    pool.write_text(
        json.dumps(
            [
                {
                    "design_id": "d1",
                    "sequence": _SEQUENCES[1][:res].ljust(res, "A"),
                    "designed_structure_path": str(pdb),
                    "binder_chain": chain,
                    "ss_codes": codes,
                }
            ]
        )
    )
    return _run("campaign_gates.py", str(pool), "--out", str(tmp_path / "g.csv"))


def test_ss_codes_of_the_wrong_length_refuse_the_pool(tmp_path: Path) -> None:
    """A stale array still classifies -- it just classifies something else.

    `_normalize_ss_codes` maps every unrecognized character to coil and checks
    no length, and `_fold_class_from_ss` takes fractions over whatever it is
    handed. So a 40-code array joined onto a 60-residue design returns a
    plausible class rather than failing, and it lands in the diversity evidence.
    """
    done = _ss_pool(tmp_path, ["E"] * 40, res=60)
    assert done.returncode != 0
    combined = done.stdout + done.stderr
    assert "supplies 40 ss_codes" in combined and "60 residues" in combined


def test_ss_codes_for_a_chain_that_does_not_exist_refuse_the_pool(
    tmp_path: Path,
) -> None:
    """Codes describing a chain the structure does not have describe nothing."""
    done = _ss_pool(tmp_path, ["H"] * 60, chain="Z")
    assert done.returncode != 0
    assert "has no residues in its structure" in (done.stdout + done.stderr)


def test_a_stringified_ss_code_list_is_refused_by_the_alphabet_check(
    tmp_path: Path,
) -> None:
    """A second, independent guard on the trap round 3 introduced.

    Preserving iterables fixed the one path that produced `"['E', 'E', ...]"`.
    This refuses the shape wherever it arrives from, because the brackets,
    quotes and commas are read as coil -- and an all-coil design is `other`,
    which COUNTS toward the non-all-alpha diversity target. The misjoin does
    not destroy the evidence, it manufactures it.
    """
    done = _ss_pool(tmp_path, str(["E"] * 60))
    assert done.returncode != 0
    assert "not secondary-structure codes" in (done.stdout + done.stderr)


def test_well_formed_ss_codes_still_reach_the_classifier(tmp_path: Path) -> None:
    """The control: the validation must not refuse the canonical path."""
    done = _ss_pool(tmp_path, ["H"] * 60)
    assert done.returncode == 0, done.stderr
    import csv

    row = list(csv.DictReader((tmp_path / "g.csv").read_text().splitlines()))[0]
    assert row["fold_class"] == "all_alpha"
    assert row["fold_ss_method"] == "supplied"


# ── PR-22 round 1: the novelty gate runs, but nothing downstream enforced it ─


def test_a_malformed_reference_cannot_discard_a_rejection_already_made(
    tmp_path: Path,
) -> None:
    """The same failure as a malformed hits file, one call site over.

    The kernel converts target/control chains AFTER running the ubiquitin and
    known-binder arms, so a reference like "123" raises on top of an
    ALREADY-ESTABLISHED REJECT -- and a per-row `except Exception` reports the
    whole verdict as NOT_RUN, which the sheet writer used to admit. A design
    that IS a copy would keep its rejection nowhere.
    """
    refs = tmp_path / "refs.json"
    refs.write_text(
        json.dumps([{"pdb": "r.pdb", "chain": "A", "sequence": "123",
                     "role": "target"}])
    )
    design = _UBIQUITIN[:40] + "GSGSEEALKKAEELLKKAEELLKKGSG"
    done, _ = _gates_rows(
        tmp_path, [{"design_id": "d1", "sequence": design}],
        "--reference-chains", str(refs),
    )
    assert done.returncode != 0
    assert "is unusable" in (done.stdout + done.stderr)


def test_a_not_run_novelty_verdict_states_which_subject_was_missing(
    tmp_path: Path,
) -> None:
    """The kernel routes its explanation by outcome; read the right key.

    A REJECT fills `reason`; a NOT_RUN fills `not_run_reason` and leaves
    `reason` None. Reading only `reason` left the actionable half -- WHICH
    required subject set was unavailable -- out of the artifact entirely.
    """
    done, rows = _gates_rows(
        tmp_path, [{"design_id": "d1", "sequence": _SEQUENCES[1]}]
    )
    assert done.returncode == 0, done.stderr
    assert rows[0]["novelty_verdict"] == "NOT_RUN"
    assert "known-binder corpus" in rows[0]["gate_not_run_reason"]


def test_lcp_says_why_it_is_absent_rather_than_going_blank(
    tmp_path: Path,
) -> None:
    """The pool validator accepts X/B/Z/J/U/O; the LCP port accepts only AA20.

    A blanket catch returning None dropped a MANDATORY recorded metric on every
    design carrying an ambiguity code, with nothing on the row to say so.
    """
    done, rows = _gates_rows(
        tmp_path, [{"design_id": "d1", "sequence": _SEQUENCES[1][:-1] + "X"}]
    )
    assert done.returncode == 0, done.stderr
    assert not rows[0]["lcp_score"]
    assert "LcpInputError" in rows[0]["lcp_not_run_reason"]


def test_the_rejects_ledger_carries_the_numbers_that_decided_each_rejection(
    tmp_path: Path,
) -> None:
    """An entry of {design_id, gate} gives a reader no way to audit the removal."""
    rejects = tmp_path / "rejects.json"
    pool = tmp_path / "pool.json"
    pool.write_text(
        json.dumps([{"design_id": "d_ubq",
                     "sequence": _UBIQUITIN[:40] + "GSGSEEALKKAEELLKKAEELLKKGSG"}])
    )
    done = _run("campaign_gates.py", str(pool), "--rejects", str(rejects),
                "--out", str(tmp_path / "g.csv"))
    assert done.returncode == 0, done.stderr
    entry = next(e for e in json.loads(rejects.read_text())["rejected"]
                 if e["gate"] == "novelty")
    assert entry["novelty_top_subject_kind"] == "ubiquitin"
    assert float(entry["novelty_top_identity"]) == 1.0
    assert int(entry["novelty_top_aligned_columns"]) == 40


def test_dispatch_tier_novelty_evidence_cannot_reach_the_ranked_sheet(
    tmp_path: Path,
) -> None:
    """The protocol exempts UniRef90 before dispatch and requires it before the sheet.

    Without the tier column a dispatch clearance and a final one are
    indistinguishable to the writer, so dispatch evidence shipped as final
    evidence. NOT_RUN is likewise not a pass here -- this is the same rule the
    mimic screen already gets, applied at the stage the protocol names.
    """
    gate = _gate(tmp_path)
    for over, expected in (
        ({"novelty_verdict": "NOT_RUN"}, "novelty_verdict is NOT_RUN"),
        ({"novelty_tier": "dispatch"}, "not 'final'"),
        ({"novelty_tier": ""}, "not 'final'"),
    ):
        pool = tmp_path / "c.json"
        pool.write_text(json.dumps([_candidate(f"p{i}", float(i), _index=i, **over)
                                    for i in range(3)]))
        done = _run("select_panel.py", str(pool), "--gate", str(gate),
                    "--panel-size", "3", "--out", str(tmp_path / "s.csv"))
        assert expected in (done.stdout + done.stderr), (over, done.stdout[-400:])

    # And the disclosed escape still ships, because a campaign that genuinely
    # cannot run the search must be able to say so rather than be stuck.
    pool = tmp_path / "c2.json"
    pool.write_text(json.dumps([_candidate(f"p{i}", float(i), _index=i,
                                           novelty_tier="dispatch")
                                for i in range(3)]))
    done = _run("select_panel.py", str(pool), "--gate", str(gate),
                "--panel-size", "3", "--allow-novelty-not-final",
                "--out", str(tmp_path / "s2.csv"))
    assert done.returncode == 0, done.stderr


def test_terminal_coil_survives_a_scalar_dssp_string(tmp_path: Path) -> None:
    """`.strip()` on a scalar deletes per-residue codes DSSP actually wrote.

    DSSP writes SPACE for coil and the kernel accepts it -- ` ` is in
    `_SS_ANY_CODES` and normalises to C. So a real assignment with coil at
    either terminus loses two codes to a strip. That was harmless while the
    codes were merely forwarded; once the count is checked against the chain it
    turns a VALID canonical input into a refused pool, on exactly the path this
    wiring exists to make reachable.

    Incidental CSV padding is not a reason to trim: the length check tells them
    apart, because padding makes the count wrong and a true DSSP string matches.
    """
    res = 60
    pdb = tmp_path / "b.pdb"
    pdb.write_text(_two_chain_pdb(records_on="T", b_res=res))
    pool = tmp_path / "pool.json"
    pool.write_text(
        json.dumps([{
            "design_id": "d1",
            "sequence": _SEQUENCES[1][:res].ljust(res, "A"),
            "designed_structure_path": str(pdb),
            "binder_chain": "B",
            "ss_codes": " " + "H" * (res - 2) + " ",
        }])
    )
    out = tmp_path / "g.csv"
    done = _run("campaign_gates.py", str(pool), "--out", str(out))
    assert done.returncode == 0, done.stdout + done.stderr
    import csv

    row = list(csv.DictReader(out.read_text().splitlines()))[0]
    assert row["fold_class"] == "all_alpha"
    assert row["fold_ss_method"] == "supplied"


def _ca_line(serial: int, chain: str, resseq: int, x: float, alt: str = " ") -> str:
    """One CA record at the real PDB columns (name[12:16], altLoc[16])."""
    s = list(" " * 80)
    s[0:6] = list("ATOM  ")
    s[6:11] = list(f"{serial:5d}")
    s[12:16] = list(" CA ")
    s[16] = alt
    s[17:20] = list("ALA")
    s[21] = chain
    s[22:26] = list(f"{resseq:4d}")
    s[30:38] = list(f"{x:8.3f}")
    s[38:46] = list(f"{0.0:8.3f}")
    s[46:54] = list(f"{0.0:8.3f}")
    return "".join(s).rstrip()


@pytest.mark.parametrize(
    "shape", ["two_models", "altloc"],
)
def test_repeated_ca_records_do_not_inflate_the_expected_code_count(
    tmp_path: Path, shape: str
) -> None:
    """DSSP emits one code per RESIDUE, not per CA record.

    The kernel's CA scan appends an entry per record, and two realistic shapes
    emit more than one per residue -- measured on a 30-residue chain, a
    two-MODEL file counts 60 and alternate-location CAs count 60. Comparing the
    supplied code count against the raw record count refuses valid input, the
    same false-refusal class as stripping terminal coil.
    """
    res = 40                      # inside the frozen 35-160 length policy
    rows, serial = [], 0
    if shape == "two_models":
        for model in (1, 2):
            rows.append(f"MODEL     {model:>4}")
            for i in range(res):
                serial += 1
                rows.append(_ca_line(serial, "B", i + 1, i * 1.5))
            rows.append("ENDMDL")
    else:
        for alt in ("A", "B"):
            for i in range(res):
                serial += 1
                rows.append(_ca_line(serial, "B", i + 1, i * 1.5, alt=alt))
    pdb = tmp_path / "s.pdb"
    pdb.write_text("\n".join(rows) + "\nEND\n")

    pool = tmp_path / "pool.json"
    pool.write_text(
        json.dumps([{
            "design_id": "d1",
            "sequence": _SEQUENCES[1][:res].ljust(res, "A"),
            "designed_structure_path": str(pdb),
            "binder_chain": "B",
            "ss_codes": "H" * res,
        }])
    )
    done = _run("campaign_gates.py", str(pool), "--out", str(tmp_path / "g.csv"))
    assert done.returncode == 0, done.stdout + done.stderr


def test_an_entirely_coil_assignment_is_data_not_an_empty_field(
    tmp_path: Path,
) -> None:
    """DSSP writes coil as a space, so an all-coil assignment is all spaces.

    Stripping discarded it whole and the row came back NOT_RUN -- throwing away
    the evidence, because an all-coil design classifies as `other` and `other`
    is exactly what counts toward the non-all-alpha diversity target. Only a
    genuinely empty field means "no codes supplied"; a stray whitespace cell now
    fails the count check loudly instead of vanishing.
    """
    res = 40                      # inside the frozen 35-160 length policy
    pdb = tmp_path / "s.pdb"
    pdb.write_text(
        "\n".join(_ca_line(i + 1, "B", i + 1, i * 1.5) for i in range(res))
        + "\nEND\n"
    )

    def run(ss_codes):
        pool = tmp_path / "pool.json"
        pool.write_text(
            json.dumps([{
                "design_id": "d1",
                "sequence": _SEQUENCES[1][:res].ljust(res, "A"),
                "designed_structure_path": str(pdb),
                "binder_chain": "B",
                "ss_codes": ss_codes,
            }])
        )
        return _run("campaign_gates.py", str(pool), "--out", str(tmp_path / "g.csv"))

    import csv

    done = run(" " * res)
    assert done.returncode == 0, done.stdout + done.stderr
    row = list(csv.DictReader((tmp_path / "g.csv").read_text().splitlines()))[0]
    assert row["fold_class"] == "other"
    assert row["fold_ss_method"] == "supplied"

    # A stray one-space cell is not a 1-residue assignment: it is refused, by name.
    done = run(" ")
    assert done.returncode != 0
    assert "supplies 1 ss_codes" in (done.stdout + done.stderr)
