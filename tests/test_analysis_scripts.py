from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(script: Path):
    sys.path.insert(0, str(script.parent))
    try:
        spec = importlib.util.spec_from_file_location(script.stem, script)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def _pdb_atom(
    serial: int,
    residue_number: int,
    x: float | str,
    *,
    atom: str = "CA",
    record: str = "ATOM",
    residue: str = "ALA",
    chain: str = "A",
    insertion: str = " ",
) -> str:
    def coord(value: float | str) -> str:
        return f"{value:>8}" if isinstance(value, str) else f"{value:8.3f}"

    return (
        f"{record:<6}{serial:5d} {atom:^4} {residue:>3} {chain}"
        f"{residue_number:4d}{insertion}   {coord(x)}{coord(0.0)}{coord(0.0)}"
        "  1.00 80.00           C\n"
    )


def test_rank_batch_only_ranks_completed_rows() -> None:
    script = ROOT / "plugins/tamarind/skills/tamarind-batch/scripts/rank_batch.py"
    module = _load(script)
    batch = {
        "batch_status": "Running",
        "statuses": {"Complete": 1, "Running": 1},
        "subjobs": [
            {"name": "still-running", "status": "Running", "score": {"iptm": 0.99}},
            {"name": "done", "status": "Complete", "score": {"iptm": 0.5}},
        ],
    }
    result = module.summarize(batch, metric="iptm")
    assert result["n_ranked"] == 1
    assert [row["name"] for row in result["ranked"]] == ["done"]
    assert result["n_unranked"] == 1
    assert result["unranked"] == [
        {
            "name": "still-running",
            "status": "Running",
            "metric_value": 0.99,
            "score": {"iptm": 0.99},
            "rank": None,
            "unranked_reason": "status-not-complete",
        }
    ]


def test_confidence_ranking_uses_finite_metric_shared_by_all_models() -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    models = [
        {
            "label": "aggregate",
            "confidence_score": 0.7,
            "iptm": 0.2,
            "interface_applicable": True,
        },
        {
            "label": "missing-aggregate",
            "confidence_score": None,
            "iptm": 0.99,
            "interface_applicable": True,
        },
    ]
    result = module.summarize(models)
    assert result["selection_metric"] == "iptm"
    assert [row["label"] for row in result["ranked"]] == [
        "missing-aggregate",
        "aggregate",
    ]


def test_confidence_does_not_rank_without_finite_common_metric() -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    models = [
        {"label": "aggregate-only", "confidence_score": 0.7, "ptm": float("nan")},
        {"label": "ptm-only", "confidence_score": float("inf"), "ptm": 0.8},
    ]

    result = module.summarize(models)

    assert result["selection_metric"] is None
    assert result["n_ranked"] == 0
    assert [row["rank"] for row in result["ranked"]] == [None, None]
    assert result["ranked"][0]["ptm"] is None
    assert result["ranked"][1]["confidence_score"] is None
    json.dumps(result, allow_nan=False)


def test_confidence_does_not_label_unknown_applicability_as_weak_interface() -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    models = [
        {
            "label": "unknown-complex",
            "ptm": 0.8,
            "iptm": 0.2,
            "interface_applicable": None,
        }
    ]

    result = module.summarize(models)

    assert result["selection_metric"] == "iptm"
    assert result["low_confidence_interfaces"] == []
    assert result["interface_unchecked"] == [
        {"label": "unknown-complex", "rank": 1, "iptm": 0.2}
    ]


def test_confidence_csv_only_iptm_ranks_but_requires_interface_verification(
    tmp_path: Path,
) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    scores = tmp_path / "scores.csv"
    scores.write_text("model,iptm\nlow,0.2\nhigh,0.9\n")

    models = module.load_models(str(scores))
    result = module.summarize(models)

    assert [model["interface_applicable"] for model in models] == [None, None]
    assert result["selection_metric"] == "iptm"
    assert [model["label"] for model in result["ranked"]] == ["high", "low"]
    assert result["low_confidence_interfaces"] == []
    assert result["interface_unchecked"] == [
        {"label": "high", "rank": 1, "iptm": 0.9},
        {"label": "low", "rank": 2, "iptm": 0.2},
    ]


def test_confidence_loads_best_only_scores_csv(tmp_path: Path) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    scores = tmp_path / "boltz-scores-best.csv"
    scores.write_text("model,confidence_score,ptm\nbest,0.81,0.72\n")
    (tmp_path / "inputs.csv").write_text("sequence\nAAAA\n")

    result = module.summarize(module.load_models(tmp_path))

    assert result["selection_metric"] == "confidence_score"
    assert result["n_ranked"] == 1
    assert result["ranked"][0]["label"] == "best"
    assert result["ranked"][0]["source_csv"] == scores.name
    assert result["ranked"][0]["rank"] == 1


def test_confidence_deduplicates_generic_metrics_and_ignores_monomer_iptm(
    tmp_path: Path,
) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    (tmp_path / "metrics.csv").write_text(
        "model,plddt,ptm,iptm\nraw,0.2,0.1,0.0\n"
    )
    (tmp_path / "metrics-processed.csv").write_text(
        "model,plddt,ptm,iptm\nbest,0.7,0.6,0.0\n"
    )
    (tmp_path / "result_0.pdb").write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 70.00           C\n"
        "ATOM      2  CA  GLY A   2       3.800   0.000   0.000  1.00 70.00           C\n"
    )

    models = module.load_models(tmp_path)
    result = module.summarize(models)

    assert len(models) == 1
    assert models[0]["source_csv"] == "metrics-processed.csv"
    assert models[0]["chain_count"] == 1
    assert models[0]["interface_applicable"] is False
    assert models[0]["geometry_ok"] is True
    assert models[0]["ca_pair_count"] == 1
    assert result["selection_metric"] == "ptm"
    assert result["low_confidence_interfaces"] == []
    assert result["geometry_failures"] == []


def test_confidence_flags_implausible_adjacent_ca_geometry(tmp_path: Path) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    (tmp_path / "metrics-processed.csv").write_text(
        "model,plddt,ptm\nbest,0.8,0.7\n"
    )
    (tmp_path / "result_0.pdb").write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 80.00           C\n"
        "ATOM      2  CA  GLY A   2       1.000   0.000   0.000  1.00 80.00           C\n"
        "ATOM      3  CA  SER A   3      11.000   0.000   0.000  1.00 80.00           C\n"
    )

    result = module.summarize(module.load_models(tmp_path))

    model = result["ranked"][0]
    assert model["geometry_ok"] is False
    assert model["ca_pair_count"] == 2
    assert model["implausible_ca_pairs"] == 2
    assert model["min_ca_distance"] == 1.0
    assert model["max_ca_distance"] == 10.0
    assert result["geometry_failures"] == [
        {
            "label": "best",
            "rank": 1,
            "ca_pair_count": 2,
            "implausible_ca_pairs": 2,
            "nonfinite_ca_pairs": 0,
            "min_ca_distance": 1.0,
            "max_ca_distance": 10.0,
        }
    ]


def test_confidence_keeps_raw_only_candidates_beside_processed_candidates(
    tmp_path: Path,
) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    processed = tmp_path / "candidate-a"
    raw_only = tmp_path / "candidate-b"
    processed.mkdir()
    raw_only.mkdir()
    (processed / "metrics-processed.csv").write_text("model,ptm\na,0.8\n")
    (processed / "metrics.csv").write_text("model,ptm\na-raw,0.1\n")
    (raw_only / "metrics.csv").write_text("model,ptm\nb,0.9\n")

    csvs = module._find_scores_csv(tmp_path)
    models = module.load_models(tmp_path)

    assert [Path(path).relative_to(tmp_path).as_posix() for path in csvs] == [
        "candidate-a/metrics-processed.csv",
        "candidate-b/metrics.csv",
    ]
    assert {model["label"] for model in models} == {
        "candidate-a:a",
        "candidate-b:b",
    }


def test_confidence_uses_one_conventional_score_source_per_directory(
    tmp_path: Path,
) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    (tmp_path / "scores.csv").write_text("model,ptm\nscore-row,0.8\n")
    (tmp_path / "confidence.csv").write_text(
        "model,ptm\nduplicate-confidence-row,0.8\n"
    )

    csvs = module._find_scores_csv(tmp_path)
    models = module.load_models(tmp_path)

    assert [Path(path).name for path in csvs] == ["scores.csv"]
    assert [model["label"] for model in models] == ["score-row"]


def test_confidence_flags_nonfinite_ca_coordinates(tmp_path: Path) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    (tmp_path / "metrics.csv").write_text("model,ptm\nbad,0.7\n")
    (tmp_path / "bad.pdb").write_text(
        _pdb_atom(1, 1, 0.0) + _pdb_atom(2, 2, "nan")
    )

    result = module.summarize(module.load_models(tmp_path))
    model = result["ranked"][0]

    assert model["geometry_ok"] is False
    assert model["ca_pair_count"] == 1
    assert model["implausible_ca_pairs"] == 1
    assert model["nonfinite_ca_pairs"] == 1
    assert model["min_ca_distance"] is None
    assert result["geometry_failures"][0]["nonfinite_ca_pairs"] == 1


def test_confidence_checks_insertion_code_adjacency(tmp_path: Path) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    (tmp_path / "metrics.csv").write_text("model,ptm\ninserted,0.7\n")
    (tmp_path / "inserted.pdb").write_text(
        _pdb_atom(1, 10, 0.0)
        + _pdb_atom(2, 10, 20.0, insertion="A")
        + _pdb_atom(3, 11, 23.8)
    )

    model = module.load_models(tmp_path)[0]

    assert model["geometry_ok"] is False
    assert model["ca_pair_count"] == 2
    assert model["implausible_ca_pairs"] == 1


def test_confidence_ignores_water_only_hetero_chains(tmp_path: Path) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    (tmp_path / "metrics.csv").write_text("model,ptm,iptm\nwet,0.7,0.9\n")
    (tmp_path / "wet.pdb").write_text(
        _pdb_atom(1, 1, 0.0)
        + _pdb_atom(2, 2, 3.8)
        + _pdb_atom(
            3,
            1,
            8.0,
            atom="O",
            record="HETATM",
            residue="HOH",
            chain="B",
        )
    )

    model = module.load_models(tmp_path)[0]

    assert model["chain_count"] == 1
    assert model["interface_applicable"] is False


def test_confidence_surfaces_unchecked_cif_geometry(tmp_path: Path) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    (tmp_path / "metrics.csv").write_text("model,ptm\ncif-only,0.7\n")
    (tmp_path / "result.cif").write_text("data_result\n#\n")

    result = module.summarize(module.load_models(tmp_path))

    assert result["ranked"][0]["geometry_ok"] is None
    assert result["geometry_failures"] == []
    assert result["geometry_unchecked"] == [
        {"label": "cif-only", "rank": 1}
    ]


def test_confidence_does_not_attach_one_pdb_to_multiple_rows(tmp_path: Path) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    (tmp_path / "scores.csv").write_text(
        "model,ptm\nfirst,0.8\nsecond,0.7\n"
    )
    (tmp_path / "only.pdb").write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 80.00           C\n"
        "ATOM      2  CA  GLY A   2       1.000   0.000   0.000  1.00 80.00           C\n"
    )

    models = module.load_models(tmp_path)

    assert [model["geometry_ok"] for model in models] == [None, None]
    assert [model["chain_count"] for model in models] == [None, None]


def test_confidence_maps_explicit_structure_files_not_lexical_order(
    tmp_path: Path,
) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    (tmp_path / "scores.csv").write_text(
        "model,structure_file,ptm\n"
        "good,result_2.pdb,0.8\n"
        "bad,result_10.pdb,0.7\n"
    )
    (tmp_path / "result_2.pdb").write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 80.00           C\n"
        "ATOM      2  CA  GLY A   2       3.800   0.000   0.000  1.00 80.00           C\n"
    )
    (tmp_path / "result_10.pdb").write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 80.00           C\n"
        "ATOM      2  CA  GLY A   2       1.000   0.000   0.000  1.00 80.00           C\n"
    )

    models = module.load_models(tmp_path)

    assert [(model["label"], model["geometry_ok"]) for model in models] == [
        ("good", True),
        ("bad", False),
    ]


def test_confidence_counts_nonprotein_atom_chains_for_interface_context(
    tmp_path: Path,
) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    (tmp_path / "metrics.csv").write_text("model,ptm,iptm\ncomplex,0.6,0.7\n")
    (tmp_path / "complex.pdb").write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 80.00           C\n"
        "ATOM      2  CA  GLY A   2       3.800   0.000   0.000  1.00 80.00           C\n"
        "ATOM      3  P     A B   1       7.000   0.000   0.000  1.00 80.00           P\n"
    )

    model = module.load_models(tmp_path)[0]

    assert model["chain_count"] == 2
    assert model["interface_applicable"] is True
    assert model["geometry_ok"] is True


def test_confidence_mixed_monomer_multimer_set_does_not_rank_on_iptm() -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    models = [
        {
            "label": "monomer",
            "ptm": 0.8,
            "iptm": 0.0,
            "interface_applicable": False,
        },
        {
            "label": "multimer",
            "ptm": 0.7,
            "iptm": 0.9,
            "interface_applicable": True,
        },
    ]

    result = module.summarize(models)

    assert result["selection_metric"] == "ptm"
    assert [model["label"] for model in result["ranked"]] == [
        "monomer",
        "multimer",
    ]


def test_confidence_labels_multiple_generic_metric_files_by_parent(
    tmp_path: Path,
) -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-structure-prediction/scripts/parse_boltz_confidence.py"
    )
    module = _load(script)
    for name, ptm in (("candidate-a", 0.4), ("candidate-b", 0.7)):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "metrics-processed.csv").write_text(
            f"sample,plddt,ptm,iptm\n0,0.8,{ptm},0.0\n"
        )
        (directory / "result_0.pdb").write_text(
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 80.00           C\n"
        )

    models = module.load_models(tmp_path)
    result = module.summarize(models)

    assert {model["label"] for model in models} == {
        "candidate-a:0.0",
        "candidate-b:0.0",
    }
    assert [model["label"] for model in result["ranked"]] == [
        "candidate-b:0.0",
        "candidate-a:0.0",
    ]


def test_rank_batch_parses_json_score_strings(tmp_path: Path) -> None:
    script = ROOT / "plugins/tamarind/skills/tamarind-batch/scripts/rank_batch.py"
    module = _load(script)
    rows = [
        {"JobName": "a", "JobStatus": "Complete", "Score": json.dumps({"iptm": 0.8})},
        {"JobName": "b", "JobStatus": "Complete", "Score": json.dumps({"iptm": 0.6})},
    ]
    path = tmp_path / "rows.json"
    path.write_text(json.dumps(rows))
    result = module.summarize(module.load_batch(path), metric="iptm")
    assert [row["name"] for row in result["ranked"]] == ["a", "b"]


@pytest.mark.parametrize(
    "metric",
    [
        "pae",
        "pAE",
        "i_pAE",
        "ipAE",
        "pAEValue",
        "interface_pAE",
        "i_pAEScore",
        "bindingAffinity",
        "bindingEnergy",
        "deltaG",
        "dG",
        "ddG",
        "binding_ddG",
        "dGValue",
        "DGValue",
        "dG_score",
        "deltaGValue",
        "ddGValue",
        "ddG_score",
        "affinityPredValue",
        "RMSDValue",
        "predictedKd",
        "Kd",
        "Ki",
        "IC50",
        "predictedKi",
        "predictedIC50",
        "expKd",
        "expKi",
        "expIC50",
        "appKd",
        "appKi",
        "appIC50",
        "topKd",
        "topKi",
        "topIC50",
        "deepKd",
        "deepKi",
        "deepIC50",
        "groupKd",
        "mapKi",
        "stepIC50",
        "sweepKd",
        "interpKi",
        "tempIC50",
        "compKd",
        "prepKd",
        "samplePrepKi",
        "followupIC50",
        "followUpKd",
        "subgroupKi",
        "dupIC50",
        "tripKd",
        "heatmapKi",
        "ATPKd",
        "ADPKi",
        "GTPIC50",
        "CTPKd",
        "UTPKi",
        "AMPIC50",
        "cAMPKd",
        "cGMPKi",
        "NADPIC50",
        "RNPKd",
        "effluxPumpKi",
        "ligandTrapIC50",
        "rampKd",
        "clampKi",
        "ChIPIC50",
        "coIPKd",
    ],
)
def test_rank_batch_infers_lower_better_metric_direction(metric: str) -> None:
    script = ROOT / "plugins/tamarind/skills/tamarind-batch/scripts/rank_batch.py"
    module = _load(script)
    batch = {
        "batch_status": "Complete",
        "statuses": {"Complete": 2},
        "subjobs": [
            {"name": "worse", "status": "Complete", "score": {metric: 10.0}},
            {"name": "better", "status": "Complete", "score": {metric: 2.0}},
        ],
    }

    result = module.summarize(batch)

    assert result["selection_metric"] == metric
    assert result["ascending"] is True
    assert result["direction_source"] == "inferred"
    assert [row["name"] for row in result["ranked"]] == ["better", "worse"]

    overridden = module.summarize(batch, ascending=False)
    assert overridden["direction_source"] == "explicit"
    assert [row["name"] for row in overridden["ranked"]] == ["worse", "better"]


@pytest.mark.parametrize(
    "metric",
    [
        "ipTM",
        "confidence",
        "pLDDT",
        "pKd",
        "pKi",
        "pIC50",
        "pKdValue",
        "pKi_score",
        "pIC50PredValue",
        "predictedPKd",
        "predictedpKd",
        "estimatedpKi",
        "apparentpIC50",
        "measuredpKd",
        "observedpKi",
        "fittedpIC50",
        "assaypKd",
        "meanpKi",
        "medianpIC50",
        "avgpKd",
        "averagepKi",
        "reportedpIC50",
        "predpKd",
        "calcpKi",
        "measpIC50",
        "obspKd",
        "fitpKi",
        "modelpIC50",
        "computedpKd",
        "simulatedpKd",
        "inferredpKi",
        "consensuspIC50",
    ],
)
def test_rank_batch_keeps_higher_better_metrics_descending(metric: str) -> None:
    script = ROOT / "plugins/tamarind/skills/tamarind-batch/scripts/rank_batch.py"
    module = _load(script)
    batch = {
        "batch_status": "Complete",
        "statuses": {"Complete": 2},
        "subjobs": [
            {"name": "better", "status": "Complete", "score": {metric: 0.9}},
            {"name": "worse", "status": "Complete", "score": {metric: 0.2}},
        ],
    }

    result = module.summarize(batch)

    assert result["ascending"] is False
    assert [row["name"] for row in result["ranked"]] == ["better", "worse"]


def test_rank_batch_requires_explicit_direction_for_ambiguous_glued_p_scale() -> None:
    script = ROOT / "plugins/tamarind/skills/tamarind-batch/scripts/rank_batch.py"
    module = _load(script)
    metric = "novelpKd"
    batch = {
        "batch_status": "Complete",
        "statuses": {"Complete": 2},
        "subjobs": [
            {"name": "high", "status": "Complete", "score": {metric: 9.0}},
            {"name": "low", "status": "Complete", "score": {metric: 2.0}},
        ],
    }

    inferred = module.summarize(batch)
    explicit = module.summarize(batch, ascending=False)

    assert inferred["ascending"] is True
    assert inferred["direction_source"] == "inferred"
    assert [row["name"] for row in inferred["ranked"]] == ["low", "high"]
    assert explicit["ascending"] is False
    assert explicit["direction_source"] == "explicit"
    assert [row["name"] for row in explicit["ranked"]] == ["high", "low"]


def test_rank_batch_accepts_native_cli_jobs_envelope(tmp_path: Path) -> None:
    script = ROOT / "plugins/tamarind/skills/tamarind-batch/scripts/rank_batch.py"
    module = _load(script)
    path = tmp_path / "jobs.json"
    path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "JobName": "done",
                        "JobStatus": "Complete",
                        "Score": json.dumps({"iptm": 0.8}),
                    },
                    {
                        "JobName": "failed",
                        "JobStatus": "Stopped",
                        "Score": json.dumps({"iptm": 0.99}),
                    },
                ],
                "count": 2,
                "statuses": {"Complete": 1, "Stopped": 1},
            }
        )
    )

    batch = module.load_batch(path)
    result = module.summarize(batch, metric="iptm")

    assert batch["statuses"] == {"Complete": 1, "Stopped": 1}
    assert [row["name"] for row in result["ranked"]] == ["done"]
    assert [row["name"] for row in result["unranked"]] == ["failed"]
    assert result["unranked"][0]["rank"] is None


def test_rank_batch_does_not_invent_completion_from_artifacts(tmp_path: Path) -> None:
    script = ROOT / "plugins/tamarind/skills/tamarind-batch/scripts/rank_batch.py"
    module = _load(script)
    subjob = tmp_path / "batch-candidate"
    subjob.mkdir()
    (subjob / "metrics.csv").write_text("iptm\n0.99\n")

    result = module.summarize(module.load_batch(tmp_path), metric="iptm")

    assert result["ranked"] == []
    assert result["unranked"][0]["status"] == "Unknown"
    assert result["unranked"][0]["unranked_reason"] == "status-not-complete"


def test_completed_row_without_selected_metric_is_explicitly_unranked() -> None:
    script = ROOT / "plugins/tamarind/skills/tamarind-batch/scripts/rank_batch.py"
    module = _load(script)
    batch = {
        "batch_status": "Complete",
        "statuses": {"Complete": 1},
        "subjobs": [
            {"name": "no-iptm", "status": "Complete", "score": {"ptm": 0.7}}
        ],
    }

    result = module.summarize(batch, metric="iptm")

    assert result["ranked"] == []
    assert result["unranked"][0]["unranked_reason"] == "missing-metric"


def test_non_finite_values_are_missing_and_never_ranked(tmp_path: Path) -> None:
    common_script = (
        ROOT / "plugins/tamarind/skills/tamarind-batch/scripts/_common.py"
    )
    common = _load(common_script)
    scores = tmp_path / "scores.csv"
    scores.write_text("name,nan_value,pos_inf,neg_inf,finite\na,NaN,Inf,-Infinity,0.5\n")

    parsed = common.parse_scores_csv(scores)[0]
    assert parsed == {
        "name": "a",
        "nan_value": None,
        "pos_inf": None,
        "neg_inf": None,
        "finite": 0.5,
    }
    assert common.read_score_field(
        {"Score": '{"nan": NaN, "inf": Infinity, "finite": 1.0}'}
    ) == {"nan": None, "inf": None, "finite": 1.0}

    rank_script = ROOT / "plugins/tamarind/skills/tamarind-batch/scripts/rank_batch.py"
    rank_module = _load(rank_script)
    batch = {
        "batch_status": "Complete",
        "statuses": {"Complete": 3},
        "subjobs": [
            {"name": "nan", "status": "Complete", "score": {"iptm": float("nan")}},
            {"name": "inf", "status": "Complete", "score": {"iptm": float("inf")}},
            {"name": "finite", "status": "Complete", "score": {"iptm": 0.6}},
        ],
    }
    ranked = rank_module.summarize(batch, metric="iptm")
    assert [row["name"] for row in ranked["ranked"]] == ["finite"]
    assert [row["metric_value"] for row in ranked["unranked"]] == [None, None]
    json.dumps(ranked, allow_nan=False)

    binder_script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-binder-design/scripts/summarize_binder_metrics.py"
    )
    binder = _load(binder_script)
    binder_result = binder.summarize(
        [
            {"label": "nan", "ipsae": float("nan")},
            {"label": "finite", "ipsae": 0.75},
            {"label": "inf", "ipsae": float("inf")},
        ],
        metric="ipsae",
    )
    assert binder_result["n_scored"] == 1
    assert [row["label"] for row in binder_result["ranked"]] == ["finite"]
    json.dumps(binder_result, allow_nan=False)


def test_binder_auto_metric_maximizes_candidate_coverage() -> None:
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-binder-design/scripts/summarize_binder_metrics.py"
    )
    module = _load(script)
    designs = [
        {"label": "a", "ipsae": 0.9, "iptm": 0.7},
        {"label": "b", "ipsae": None, "iptm": 0.8},
        {"label": "c", "ipsae": None, "iptm": 0.6},
    ]

    result = module.summarize(designs)

    assert result["selection_metric"] == "iptm"
    assert result["n_scored"] == 3
    assert result["unranked"] == []

    forced = module.summarize(designs, metric="ipsae")
    assert forced["n_scored"] == 1
    assert [row["label"] for row in forced["unranked"]] == ["b", "c"]
    assert all(row["unranked_reason"] == "missing-metric" for row in forced["unranked"])


def _sdf_record(name: str, **properties: float) -> str:
    fields = "".join(
        f">  <{key}>\n{value}\n\n" for key, value in properties.items()
    )
    return f"{name}\n  test\n\n{fields}$$$$\n"


def test_gnina_uses_sdf_cnnscore_not_vina_energy_column(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "result.sdf").write_text(
        _sdf_record("pose-one", CNNscore=0.2, CNNaffinity=8.0)
        + _sdf_record("pose-two", CNNscore=0.9, CNNaffinity=4.0)
    )
    (tmp_path / "log.txt").write_text(
        "gnina docking\n"
        "mode | affinity | CNN pose score | CNN affinity\n"
        "   1     -9.000      0.200      8.000\n"
        "   2     -5.000      0.900      4.000\n"
    )

    metric, poses = module.load_poses(tmp_path)
    result = module.summarize(metric, poses)

    assert metric == "cnnscore"
    assert [row["source_rank"] for row in result["ranked"]] == [2, 1]
    assert [row["cnnscore"] for row in result["ranked"]] == [0.9, 0.2]


def test_docking_rejects_truncated_multimodel_file_before_pairing_scores(
    tmp_path: Path,
) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "ligand_out.pdbqt").write_text(
        "MODEL 1\nATOM first\nENDMDL\nMODEL 2\nATOM truncated\n"
    )
    (tmp_path / "log.txt").write_text(
        "   1     -8.000      0.000      0.000\n"
        "   2     -7.000      0.000      0.000\n"
    )

    with pytest.raises(SystemExit, match="truncated MODEL without ENDMDL"):
        module.load_poses(tmp_path)


def test_docking_rejects_pose_score_count_mismatch(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "ligand_out.pdbqt").write_text(
        "MODEL 2\nATOM second\nENDMDL\n"
    )
    (tmp_path / "log.txt").write_text(
        "   1     -8.000      0.000      0.000\n"
        "   2     -7.000      0.000      0.000\n"
    )

    with pytest.raises(SystemExit, match="pose/score count mismatch"):
        module.load_poses(tmp_path)


def test_docking_rejects_pose_score_model_rank_mismatch(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "ligand_out.pdbqt").write_text(
        "MODEL 2\nATOM second\nENDMDL\n"
        "MODEL 3\nATOM third\nENDMDL\n"
    )
    (tmp_path / "log.txt").write_text(
        "   1     -8.000      0.000      0.000\n"
        "   2     -7.000      0.000      0.000\n"
    )

    with pytest.raises(SystemExit, match="pose/score rank mismatch"):
        module.load_poses(tmp_path)


@pytest.mark.parametrize(
    ("filename", "ensemble"),
    [
        (
            "ligand_out.pdbqt",
            "MODEL 1\nATOM first\nENDMDL\nMODEL 2\nATOM second\nENDMDL\n",
        ),
        (
            "ligand_out.sdf",
            _sdf_record("pose-one") + _sdf_record("pose-two"),
        ),
    ],
)
def test_docking_ranks_valid_aligned_vina_ensembles(
    tmp_path: Path, filename: str, ensemble: str
) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / filename).write_text(ensemble)
    (tmp_path / "log.txt").write_text(
        "   1     -7.000      0.000      0.000\n"
        "   2     -9.000      0.000      0.000\n"
    )

    metric, poses = module.load_poses(tmp_path)
    result = module.summarize(metric, poses)

    assert metric == "affinity"
    assert [row["source_rank"] for row in result["ranked"]] == [2, 1]
    assert [row["affinity"] for row in result["ranked"]] == [-9.0, -7.0]


def test_docking_rejects_reordered_or_duplicate_score_ranks(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "ligand_out.sdf").write_text(
        _sdf_record("pose-one") + _sdf_record("pose-two")
    )

    for score_ranks in ((2, 1), (1, 1)):
        (tmp_path / "log.txt").write_text(
            "".join(
                f"   {rank}     {-8.0 + index:.3f}      0.000      0.000\n"
                for index, rank in enumerate(score_ranks)
            )
        )
        with pytest.raises(SystemExit, match="pose/score rank mismatch"):
            module.load_poses(tmp_path)


def test_docking_rejects_malformed_model_number(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "ligand_out.pdbqt").write_text(
        "MODEL one\nATOM first\nENDMDL\n"
    )
    (tmp_path / "log.txt").write_text(
        "   1     -8.000      0.000      0.000\n"
    )

    with pytest.raises(SystemExit, match="malformed MODEL number"):
        module.load_poses(tmp_path)


def test_docking_rejects_decimal_model_number(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "ligand_out.pdbqt").write_text(
        "MODEL 1.5\nATOM first\nENDMDL\n"
    )
    (tmp_path / "log.txt").write_text(
        "   1     -8.000      0.000      0.000\n"
    )

    with pytest.raises(SystemExit, match="malformed MODEL number"):
        module.load_poses(tmp_path)


def test_docking_rejects_empty_pose_file(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "ligand_out.pdbqt").write_text("")
    (tmp_path / "log.txt").write_text(
        "   1     -8.000      0.000      0.000\n"
    )

    with pytest.raises(SystemExit, match="empty pose file"):
        module.load_poses(tmp_path)


def test_docking_rejects_unterminated_sdf_record(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "ligand_out.sdf").write_text("pose-one\n  test\n")
    (tmp_path / "log.txt").write_text(
        "   1     -8.000      0.000      0.000\n"
    )

    with pytest.raises(SystemExit, match="missing \\$\\$\\$\\$ terminator"):
        module.load_poses(tmp_path)


def test_docking_rejects_sdf_without_pose_records(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "ligand_out.sdf").write_text("$$$$\n")

    with pytest.raises(SystemExit, match="no pose records"):
        module.load_poses(tmp_path)


def test_docking_rejects_pdbqt_without_atom_records(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "ligand_out.pdbqt").write_text(
        "MODEL 1\nREMARK no coordinates\nENDMDL\n"
    )

    with pytest.raises(SystemExit, match="contains no atom records"):
        module.load_poses(tmp_path)


def test_docking_rejects_cross_directory_affinity_pairing(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    pose_dir = tmp_path / "pose-run"
    log_dir = tmp_path / "score-run"
    pose_dir.mkdir()
    log_dir.mkdir()
    (pose_dir / "ligand_out.pdbqt").write_text(
        "MODEL 1\nATOM first\nENDMDL\n"
    )
    (log_dir / "log.txt").write_text(
        "   1     -8.000      0.000      0.000\n"
    )

    with pytest.raises(SystemExit, match="affinity log is not colocated"):
        module.load_poses(tmp_path)


def test_docking_rejects_multiple_ensemble_directories(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    for name in ("run-a", "run-b"):
        run_dir = tmp_path / name
        run_dir.mkdir()
        (run_dir / "ligand_out.pdbqt").write_text(
            "MODEL 1\nATOM first\nENDMDL\n"
        )

    with pytest.raises(SystemExit, match="multiple docking ensemble candidates"):
        module.load_poses(tmp_path)


def test_docking_rejects_multiple_local_affinity_logs(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "ligand_out.pdbqt").write_text(
        "MODEL 1\nATOM first\nENDMDL\n"
    )
    score_row = "   1     -8.000      0.000      0.000\n"
    (tmp_path / "log.txt").write_text(score_row)
    (tmp_path / "alternate.log").write_text(score_row)

    with pytest.raises(SystemExit, match="multiple affinity logs found"):
        module.load_poses(tmp_path)


def test_docking_rejects_diffdock_poses_from_multiple_directories(
    tmp_path: Path,
) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    for directory, rank in (("run-a", 1), ("run-b", 2)):
        run_dir = tmp_path / directory
        run_dir.mkdir()
        (run_dir / f"rank{rank}_confidence0.8.sdf").write_text("pose\n$$$$\n")

    with pytest.raises(SystemExit, match="span multiple directories"):
        module.load_poses(tmp_path)


def test_docking_rejects_mixed_diffdock_extensions(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "rank1_confidence0.8.sdf").write_text("pose\n$$$$\n")
    (tmp_path / "rank2_confidence0.7.pdb").write_text("ATOM pose\n")

    with pytest.raises(SystemExit, match="mixed file extensions"):
        module.load_poses(tmp_path)


@pytest.mark.parametrize("ranks", [(1, 3), (1, 1)])
def test_docking_rejects_incomplete_or_duplicate_diffdock_ranks(
    tmp_path: Path, ranks: tuple[int, int]
) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    for index, rank in enumerate(ranks):
        (tmp_path / f"sample{index}_rank{rank}_confidence0.8.sdf").write_text(
            "pose\n$$$$\n"
        )

    with pytest.raises(SystemExit, match="incomplete or duplicate DiffDock ranks"):
        module.load_poses(tmp_path)


def test_gnina_with_incomplete_cnn_scores_preserves_source_rank(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "result.sdf").write_text(
        _sdf_record("pose-one", CNNscore=0.2)
        + _sdf_record("pose-two")
    )
    (tmp_path / "log.txt").write_text(
        "gnina docking\n   1     -9.000      0.000      0.000\n"
        "   2     -5.000      0.000      0.000\n"
    )

    metric, poses = module.load_poses(tmp_path)
    result = module.summarize(metric, poses)

    assert metric == "source_rank"
    assert [row["source_rank"] for row in result["ranked"]] == [1, 2]


def test_docking_rerun_ignores_its_own_top_pose_outputs(tmp_path: Path) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    (tmp_path / "rank1_confidence0.8.sdf").write_text("pose 1\n$$$$\n")
    (tmp_path / "rank2_confidence0.4.sdf").write_text("pose 2\n$$$$\n")

    metric, poses = module.load_poses(tmp_path)
    first = module.summarize(metric, poses, top=2)
    module.write_top(first, tmp_path / "top_poses")
    rerun_metric, rerun_poses = module.load_poses(tmp_path)

    assert rerun_metric == "confidence"
    assert len(rerun_poses) == 2
    assert {Path(row["file"]).parent for row in rerun_poses} == {tmp_path}


def test_docking_human_summary_preserves_source_rank(capsys) -> None:
    script = (
        ROOT / "plugins/tamarind/skills/tamarind-docking/scripts/extract_docking_poses.py"
    )
    module = _load(script)
    summary = {
        "selection_metric": "source_rank",
        "n_poses": 1,
        "top": 1,
        "ranked": [
            {
                "rank": 1,
                "source_rank": 2,
                "content": "MODEL 2\nENDMDL\n",
            }
        ],
    }

    module.print_summary(summary, [])

    rendered = capsys.readouterr().out
    assert "2.000" in rendered
    assert "model 2" in rendered


def test_copied_analysis_helpers_remain_identical() -> None:
    skills = ROOT / "plugins" / "tamarind" / "skills"
    groups = [
        [
            skills / "tamarind-structure-prediction/scripts/parse_boltz_confidence.py",
            skills / "tamarind-results-analysis/scripts/parse_boltz_confidence.py",
        ],
        [
            skills / "tamarind-docking/scripts/extract_docking_poses.py",
            skills / "tamarind-results-analysis/scripts/extract_docking_poses.py",
        ],
        [
            skills / "tamarind-batch/scripts/rank_batch.py",
            skills / "tamarind-results-analysis/scripts/rank_batch.py",
        ],
        [
            skills / "tamarind-antibody/scripts/summarize_binder_metrics.py",
            skills / "tamarind-binder-design/scripts/summarize_binder_metrics.py",
            skills / "tamarind-results-analysis/scripts/summarize_binder_metrics.py",
        ],
        [
            skills / "tamarind-antibody/scripts/_common.py",
            skills / "tamarind-batch/scripts/_common.py",
            skills / "tamarind-binder-design/scripts/_common.py",
            skills / "tamarind-results-analysis/scripts/_common.py",
            skills / "tamarind-structure-prediction/scripts/_common.py",
        ],
    ]
    for group in groups:
        contents = {path.read_bytes() for path in group}
        assert len(contents) == 1, group


def test_retained_helpers_run_from_an_unrelated_cwd(tmp_path: Path) -> None:
    scripts = sorted(
        path
        for path in (ROOT / "plugins/tamarind/skills").glob("*/scripts/*.py")
        if path.name != "_common.py"
    )
    assert scripts
    for script in scripts:
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, (script, result.stderr)


def test_binder_summary_reads_every_subdirectory_csv(tmp_path: Path) -> None:
    # Regression: a results tree that splits designs across sibling directories
    # (RFdiffusion / rfantibody / igdesign layouts) must aggregate every metrics
    # CSV, not silently read only the first match and drop the rest.
    script = (
        ROOT
        / "plugins/tamarind/skills/tamarind-results-analysis/scripts/summarize_binder_metrics.py"
    )
    module = _load(script)
    (tmp_path / "design_A").mkdir()
    (tmp_path / "design_B").mkdir()
    (tmp_path / "design_A" / "scores.csv").write_text("design,iptm\nA1,0.55\nA2,0.60\n")
    (tmp_path / "design_B" / "scores.csv").write_text("design,iptm\nB1,0.92\n")

    result = module.summarize(module.load_designs(str(tmp_path)), metric="iptm")

    # Before the fix this reported n_designs=2, max=0.60 (design_B silently dropped).
    assert result["n_designs"] == 3
    assert result["max"] == 0.92
    assert any(row["label"].endswith("B1") for row in result["ranked"])


def test_analysis_csv_reader_survives_row_wider_than_header(tmp_path: Path) -> None:
    # Regression: a data row with more fields than the header (e.g. an unquoted
    # comma in a value) must not crash the scripts with None.strip(); the overflow
    # column is dropped and the known columns are preserved.
    wide = tmp_path / "wide.csv"
    wide.write_text("design,iptm\nd1,0.80,EXTRACOL\n")

    common = _load(
        ROOT / "plugins/tamarind/skills/tamarind-results-analysis/scripts/_common.py"
    )
    assert common.parse_scores_csv(str(wide)) == [{"design": "d1", "iptm": 0.80}]

    summarize = _load(
        ROOT
        / "plugins/tamarind/skills/tamarind-results-analysis/scripts/summarize_binder_metrics.py"
    )
    result = summarize.summarize(summarize.load_designs(str(wide)), metric="iptm")
    assert result["n_scored"] == 1
    assert result["max"] == 0.80
