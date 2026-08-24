"""The campaign kernel and its two entry points.

These tests pin the things that are silently wrong when they break. Every case
below reproduced a real defect during development, or guards a rule the
protocol states in prose and only code can enforce.
"""
from __future__ import annotations

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
