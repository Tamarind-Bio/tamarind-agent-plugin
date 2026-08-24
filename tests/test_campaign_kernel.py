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


def _candidate(design_id: str, z: float, **over) -> dict:
    row = {
        "design_id": design_id, "sequence": "MKQLEDKVEELLSKNYHLENEVARLKKLVGERGS",
        "root_backbone_id": f"b-{design_id}", "structure_method": "boltzgen",
        "seq_method": "solublempnn", "tm_cluster": f"c-{design_id}",
        "target_mimic": "PASS", "opt_round": 0, "n_seeds": 5,
        "ipsae_ef2full": 0.5 + z / 100, "sc_DockQ_ef2full": 0.3 + z / 100,
    }
    row.update(over)
    return row


def test_the_ipsae_mask_stamp_is_not_treated_as_a_score_term(tmp_path: Path) -> None:
    """Every scored row is REQUIRED to carry `ipsae_mask`, and it is a string.

    Swept into the algebra it parses to None and makes the whole row ineligible,
    so a correctly-stamped campaign scores nothing at all.
    """
    rows = [_candidate("d1", 5.0, ipsae_mask="PER_PROTOMER_MAX(not UNION)")]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "1", "--out", str(tmp_path / "s.csv"), "--json")
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert summary["panel_size_shipped"] == 1
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
                "--panel-size", "1", "--out", str(out))
    assert done.returncode == 0, done.stderr
    shipped = [line.split(",")[0] for line in out.read_text().splitlines()[1:]]
    assert shipped == ["high"], f"input-order selection admitted {shipped}"


def test_a_null_score_row_is_never_ranked(tmp_path: Path) -> None:
    """final_score non-null is never relaxed; such rows are unranked, not shipped."""
    rows = [_candidate("ok", 1.0), _candidate("broken", 1.0, ipsae_ef2full=None)]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "5", "--json")
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert summary["unranked"] == 1
    assert summary["panel_size_shipped"] == 1


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
    rows = [_candidate("d1", 1.0), _candidate("bad", 1.0, sequence="results/design1.pdb")]
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
    row = _candidate("self", 1.0, **over)
    src = tmp_path / "c.json"
    src.write_text(json.dumps([row]))
    done = _run("select_panel.py", str(src), "--gate", str(_gate(tmp_path)),
                "--panel-size", "5", "--json")
    summary = json.loads(done.stdout)
    assert summary["unranked"] == 1
    assert any(expected in r for r in summary["unranked_reasons"]), summary["unranked_reasons"]


def test_gates_refuse_a_pool_row_with_no_durable_identifier(tmp_path: Path) -> None:
    """A silently dropped row is an ungated design with no ledger entry."""
    pool = tmp_path / "p.json"
    pool.write_text(json.dumps([{"design_id": "d1", "sequence": "MKQL"}, {"sequence": "MKQL"}]))
    done = _run("campaign_gates.py", str(pool))
    assert done.returncode != 0
    assert "no design_id or id" in done.stderr

    dupes = tmp_path / "d.json"
    dupes.write_text(json.dumps([{"design_id": "d1"}, {"design_id": "d1"}]))
    assert "duplicate design_id" in _run("campaign_gates.py", str(dupes)).stderr


def test_gates_mark_the_job_borne_checks_not_run_rather_than_omitting_them(
    tmp_path: Path,
) -> None:
    """An absent column reads downstream like a gate that ran and found nothing."""
    pool = tmp_path / "p.json"
    pool.write_text(json.dumps([{"design_id": "d1", "sequence": "MKQLEDKVEELLSKNYHLENEVARLKK"}]))
    out = tmp_path / "gates.csv"
    done = _run("campaign_gates.py", str(pool), "--out", str(out), "--json")
    assert done.returncode == 0, done.stderr
    header = out.read_text().splitlines()[0]
    for column in ("monomer_foldability_verdict", "novelty_verdict", "fold_class"):
        assert column in header, column
    counts = json.loads(done.stdout)["verdict_counts"]
    assert counts["monomer_foldability"] == {"NOT_RUN": 1}
    assert counts["novelty"] == {"NOT_RUN": 1}
