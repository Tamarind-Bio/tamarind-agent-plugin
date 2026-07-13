from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


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
        {"label": "aggregate", "confidence_score": 0.7, "iptm": 0.2},
        {"label": "missing-aggregate", "confidence_score": None, "iptm": 0.99},
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
        [
            skills / "tamarind-batch/scripts/safe_status.py",
            skills / "tamarind-developability/scripts/safe_status.py",
            skills / "tamarind-finetune/scripts/safe_status.py",
            skills / "tamarind-results-analysis/scripts/safe_status.py",
            skills / "tamarind-submit-and-poll/scripts/safe_status.py",
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
