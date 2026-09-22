import json

import numpy as np
import pandas as pd
import pytest
import yaml
from scipy.stats import f as f_dist

from src.spc_engine import (
    CovarianceError,
    estimate_t2_reference,
    run,
    t2_statistic,
    t2_ucl,
)

EXPECTED_T2_SERIES_COLUMNS = [
    "source_row", "timestamp", "phase", "complete_case", "t2", "ucl", "violation",
]
EXPECTED_T2_VIOLATION_COLUMNS = [
    "source_row", "timestamp", "t2", "ucl", "exceedance_ratio", "phase",
]

REF_2D = np.array([[-1.0, 0.0], [1.0, 0.0], [0.0, -1.0], [0.0, 1.0]])


def test_reference_matches_conventional_statistics():
    reference = estimate_t2_reference(REF_2D, ["a", "b"])
    assert reference["n"] == 4
    assert reference["p"] == 2
    assert reference["mean"] == pytest.approx([0.0, 0.0])
    standardized = (REF_2D - REF_2D.mean(axis=0)) / REF_2D.std(axis=0, ddof=1)
    assert reference["covariance"] == pytest.approx(np.cov(standardized, rowvar=False))
    assert reference["rank"] == 2
    assert reference["condition_number"] == pytest.approx(np.linalg.cond(reference["covariance"]))


def test_t2_hand_computed_center_and_distance():
    reference = estimate_t2_reference(REF_2D, ["a", "b"])
    assert t2_statistic(np.array([[0.0, 0.0]]), reference) == pytest.approx([0.0])
    assert t2_statistic(np.array([[3.0, 0.0]]), reference) == pytest.approx([13.5])
    near = t2_statistic(np.array([[0.5, 0.0]]), reference)[0]
    far = t2_statistic(np.array([[3.0, 0.0]]), reference)[0]
    assert far > near > 0


def test_ucl_formula_degrees_and_alpha():
    expected = 2 * 101 * 99 / (100 * 98) * float(f_dist.ppf(0.99, 2, 98))
    assert t2_ucl(2, 100, 0.01) == pytest.approx(expected)
    assert t2_ucl(2, 100, 0.001) > t2_ucl(2, 100, 0.01) > t2_ucl(2, 100, 0.05)
    with pytest.raises(ValueError, match="alpha"):
        t2_ucl(2, 100, 0.0)
    with pytest.raises(ValueError, match="alpha"):
        t2_ucl(2, 100, 1.0)
    with pytest.raises(ValueError, match="p < n"):
        t2_ucl(4, 4, 0.01)


def test_reference_requires_more_rows_than_dims():
    with pytest.raises(CovarianceError, match="n > p"):
        estimate_t2_reference(np.array([[1.0, 2.0], [3.0, 4.0]]), ["a", "b"])


def test_zero_variance_dimension_rejected():
    values = np.array([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0], [4.0, 5.0]])
    with pytest.raises(CovarianceError, match="b"):
        estimate_t2_reference(values, ["a", "b"])


def test_singular_covariance_detected_not_inverted():
    values = np.array([[1.0, 2.0], [2.0, 4.0], [3.0, 6.0], [4.0, 8.0], [5.0, 10.0]])
    with pytest.raises(CovarianceError, match="[Ss]ingular"):
        estimate_t2_reference(values, ["a", "b"])


def test_phase_two_transform_reuses_phase_one():
    reference = estimate_t2_reference(REF_2D, ["a", "b"])
    raw = np.array([[3.0, 0.0]])
    manual_z = (raw - reference["mean"]) / reference["std"]
    manual = float((manual_z @ np.linalg.solve(reference["covariance"], manual_z.T))[0, 0])
    assert t2_statistic(raw, reference)[0] == pytest.approx(manual)


def _write_run_config(tmp_path, **spc_overrides):
    spc = {
        "phase_i_fraction": 0.30,
        "phase1_fraction": 0.30,
        "mr_d2": 1.128,
        "mr_d3": 0.0,
        "mr_d4": 3.267,
        "sigma_levels": [1, 2, 3],
        "min_phase1_observations": 2,
        "p_chart_min_daily_n": 10,
        "ewma_lambda": 0.20,
        "ewma_L": 3.0,
        "ewma_use_time_varying_limits": True,
        "hotelling_t2_alpha": 0.01,
        "outputs": {
            "limits": str(tmp_path / "limits.csv"),
            "violations": str(tmp_path / "violations.csv"),
            "p_chart": str(tmp_path / "pchart.csv"),
            "summary": str(tmp_path / "summary.json"),
            "ewma_violations": str(tmp_path / "ewma_violations.csv"),
            "ewma_series": str(tmp_path / "ewma_series.csv"),
            "ewma_summary": str(tmp_path / "ewma_summary.json"),
            "hotelling_t2_series": str(tmp_path / "t2_series.csv"),
            "hotelling_t2_violations": str(tmp_path / "t2_violations.csv"),
            "hotelling_t2_summary": str(tmp_path / "t2_summary.json"),
        },
    }
    spc.update(spc_overrides)
    config = {
        "paths": {
            "raw": str(tmp_path / "raw"),
            "interim": str(tmp_path / "interim"),
            "processed": str(tmp_path / "processed"),
            "reports": str(tmp_path / "reports"),
        },
        "database": {},
        "cost_assumptions": {},
        "spc": spc,
        "random_seed": 42,
        "secom": {"outputs": {"cleaned_data": str(tmp_path / "cleaned.csv")}},
        "screening": {
            "outputs": {
                "ranking": str(tmp_path / "ranking.csv"),
                "summary": str(tmp_path / "screening.json"),
            }
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def _write_run_fixture(tmp_path):
    stamps = pd.date_range("2008-07-19", periods=30, freq="D")
    target = [0] * 9 + [0] * 21
    target[4] = 1
    target[15] = 1
    pass_block = [
        [0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0],
        [-1.0, 0.0], [0.0, -1.0], [2.0, 0.0], [0.0, 2.0],
    ]
    rows = []
    for position in range(30):
        if position < 9 and position != 4:
            rows.append(pass_block.pop(0))
        elif position == 4:
            rows.append([50.0, 50.0])
        elif position == 15:
            rows.append([10.0, 10.0])
        elif position == 18:
            rows.append([float("nan"), 0.0])
        else:
            rows.append([0.1, -0.1])
    frame = pd.DataFrame(
        {
            "timestamp": stamps,
            "target": target,
            "sensor_a": [row[0] for row in rows],
            "sensor_b": [row[1] for row in rows],
        }
    )
    frame.to_csv(tmp_path / "cleaned.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        {"sensor": ["sensor_a", "sensor_b"], "selected": [True, True],
         "aggregate_rank": [1.0, 2.0]}
    ).to_csv(tmp_path / "ranking.csv", index=False, lineterminator="\n")
    (tmp_path / "screening.json").write_text(
        json.dumps({"screening_rows": 9, "window_boundary_timestamp": str(stamps[8])}),
        encoding="utf-8",
    )
    return pass_block


def test_run_reference_excludes_fails_and_phase_two(tmp_path):
    config_path = _write_run_config(tmp_path)
    _write_run_fixture(tmp_path)
    output_paths = run(config_path)
    summary = json.loads(output_paths["hotelling_t2_summary"].read_text(encoding="utf-8"))
    assert summary["p"] == 2
    assert summary["phase1_pass_lots"] == 8
    assert summary["phase1_complete_n"] == 8
    assert summary["covariance_rank"] == 2
    series = pd.read_csv(output_paths["hotelling_t2_series"])
    assert series.columns.tolist() == EXPECTED_T2_SERIES_COLUMNS
    assert len(series) == 30
    assert series["complete_case"].sum() == 29
    assert not series.loc[series["source_row"] == 18, "complete_case"].iloc[0]
    assert series.loc[series["phase"] == "Phase I", "violation"].sum() == 0
    violations = pd.read_csv(output_paths["hotelling_t2_violations"])
    assert violations.columns.tolist() == EXPECTED_T2_VIOLATION_COLUMNS
    assert 15 in violations["source_row"].tolist()
    assert violations["source_row"].is_unique
    assert (violations["exceedance_ratio"] > 1).all()
    assert summary["violation_count"] == len(violations)
    assert summary["f_degrees_of_freedom"] == [2, 6]
    assert summary["alpha"] == pytest.approx(0.01)
    for key in ("ucl", "covariance_condition_number", "max_t2",
                "first_violation_timestamp", "overlap", "methodology", "limitations",
                "contribution_diagnostics", "paths"):
        assert key in summary


def test_single_sensor_reference_is_two_dimensional():
    values = np.array([[1.0], [2.0], [3.0], [4.0]])
    reference = estimate_t2_reference(values, ["a"])
    assert reference["covariance"].shape == (1, 1)
    assert reference["rank"] == 1
    assert t2_statistic(np.array([[4.5]]), reference)[0] > 0


def test_run_degraded_reference_keeps_univariate_outputs(tmp_path):
    config_path = _write_run_config(tmp_path)
    stamps = pd.date_range("2008-07-19", periods=30, freq="D")
    target = [0] * 30
    target[4] = 1
    pd.DataFrame(
        {
            "timestamp": stamps,
            "target": target,
            "sensor_a": [float(i) for i in range(30)],
            "sensor_b": 5.0,
        }
    ).to_csv(tmp_path / "cleaned.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        {"sensor": ["sensor_a", "sensor_b"], "selected": [True, True],
         "aggregate_rank": [1.0, 2.0]}
    ).to_csv(tmp_path / "ranking.csv", index=False, lineterminator="\n")
    (tmp_path / "screening.json").write_text(
        json.dumps({"screening_rows": 9, "window_boundary_timestamp": str(stamps[8])}),
        encoding="utf-8",
    )
    output_paths = run(config_path)
    summary = json.loads(output_paths["hotelling_t2_summary"].read_text(encoding="utf-8"))
    assert summary["reference_error"] is not None
    assert summary["violation_count"] == 0
    assert summary["phase1_complete_n"] is None
    series = pd.read_csv(output_paths["hotelling_t2_series"])
    assert series.columns.tolist() == EXPECTED_T2_SERIES_COLUMNS
    assert len(series) == 30
    assert series["complete_case"].sum() == 30
    assert series["t2"].isna().all()
    violations = pd.read_csv(output_paths["hotelling_t2_violations"])
    assert violations.columns.tolist() == EXPECTED_T2_VIOLATION_COLUMNS
    assert len(violations) == 0
    limits = pd.read_csv(output_paths["limits"])
    assert limits.loc[limits["sensor"] == "sensor_a", "status"].iloc[0] == "ok"


def test_run_rejects_bad_alpha(tmp_path):
    config_path = _write_run_config(tmp_path, hotelling_t2_alpha=0.0)
    _write_run_fixture(tmp_path)
    with pytest.raises(ValueError, match="hotelling_t2_alpha"):
        run(config_path)


def test_run_t2_deterministic(tmp_path):
    config_path = _write_run_config(tmp_path)
    _write_run_fixture(tmp_path)
    first = run(config_path)
    first_bytes = {key: path.read_bytes() for key, path in first.items()}
    assert run(config_path) is not None
    assert {key: path.read_bytes() for key, path in first.items()} == first_bytes
