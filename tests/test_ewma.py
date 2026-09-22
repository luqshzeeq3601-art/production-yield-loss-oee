import json

import numpy as np
import pandas as pd
import pytest
import yaml

from src.spc_engine import compute_ewma, run

EXPECTED_EWMA_VIOLATION_COLUMNS = [
    "sensor", "source_row", "timestamp", "raw_value", "ewma_value",
    "centerline", "sigma_reference", "lambda", "L", "ewma_lcl", "ewma_ucl",
    "direction", "phase", "valid_observation_index",
]
EXPECTED_EWMA_SERIES_COLUMNS = [
    "sensor", "source_row", "timestamp", "raw_value", "ewma_value",
    "ewma_lcl", "ewma_ucl", "violation",
]


def test_recursion_hand_computed():
    result = compute_ewma(np.array([1.0, 1.0, 1.0]), 0.0, 1.0, 0.2, 3.0)
    assert result["ewma"] == pytest.approx([0.2, 0.36, 0.488])
    faster = compute_ewma(np.array([1.0, 1.0, 1.0]), 0.0, 1.0, 0.5, 3.0)
    assert faster["ewma"] == pytest.approx([0.5, 0.75, 0.875])
    assert faster["ewma"][1] != pytest.approx(result["ewma"][1])


def test_startup_limits_and_steady_state():
    result = compute_ewma(np.zeros(1000), 0.0, 1.0, 0.2, 3.0)
    assert result["ucl"][0] == pytest.approx(0.6)
    assert result["lcl"][0] == pytest.approx(-0.6)
    assert result["ucl"][-1] == pytest.approx(1.0)
    assert result["lcl"][-1] == pytest.approx(-1.0)
    assert np.all(result["ucl"] == -result["lcl"])
    assert bool(np.all(np.diff(result["ucl"]) >= 0))
    steady = compute_ewma(np.zeros(5), 0.0, 2.0, 0.2, 2.0, time_varying=False)
    assert np.all(steady["ucl"] == pytest.approx(2.0 * 2.0 / 3.0))


def test_invalid_parameters_and_degenerate_sigma():
    with pytest.raises(ValueError, match="lambda"):
        compute_ewma(np.array([1.0]), 0.0, 1.0, 0.0, 3.0)
    with pytest.raises(ValueError, match="lambda"):
        compute_ewma(np.array([1.0]), 0.0, 1.0, 1.5, 3.0)
    with pytest.raises(ValueError, match="[Ll]imit width"):
        compute_ewma(np.array([1.0]), 0.0, 1.0, 0.2, 0.0)
    empty = compute_ewma(np.array([5.0, 6.0]), 0.0, 0.0, 0.2, 3.0)
    assert empty["violation"].size == 0
    assert compute_ewma(np.empty(0), 0.0, 1.0, 0.2, 3.0)["violation"].size == 0


def test_sustained_shifts_trigger_directionally():
    up = compute_ewma(np.full(30, 1.5), 0.0, 1.0, 0.2, 3.0)
    assert bool(up["violation"].any())
    first = int(np.argmax(up["violation"]))
    assert bool((up["ewma"][first:] > up["ucl"][first:]).all())
    down = compute_ewma(np.full(30, -1.5), 0.0, 1.0, 0.2, 3.0)
    assert bool(down["violation"].any())
    assert not bool((down["ewma"] > down["ucl"]).any())
    calm = compute_ewma(np.zeros(200), 0.0, 1.0, 0.2, 3.0)
    assert not bool(calm["violation"].any())


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
    stamps = pd.date_range("2008-07-19", periods=20, freq="D")
    target = [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]
    sensor_e = [
        10.0, 11.0, 100.0, 9.0, 10.5, 9.5,
        10.0, 10.1, 9.9, 10.0, 13.0, 13.0, 13.0, float("nan"),
        13.0, 13.0, 13.0, 13.0, 13.0, 13.0,
    ]
    pd.DataFrame(
        {"timestamp": stamps, "target": target, "sensor_e": sensor_e}
    ).to_csv(tmp_path / "cleaned.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        {"sensor": ["sensor_e"], "selected": [True], "aggregate_rank": [1.0]}
    ).to_csv(tmp_path / "ranking.csv", index=False, lineterminator="\n")
    (tmp_path / "screening.json").write_text(
        json.dumps({"screening_rows": 6, "window_boundary_timestamp": str(stamps[5])}),
        encoding="utf-8",
    )


def test_run_ewma_shift_nan_and_identity(tmp_path):
    config_path = _write_run_config(tmp_path)
    _write_run_fixture(tmp_path)
    output_paths = run(config_path)
    violations = pd.read_csv(output_paths["ewma_violations"])
    assert violations.columns.tolist() == EXPECTED_EWMA_VIOLATION_COLUMNS
    assert (violations["sensor"] == "sensor_e").all()
    assert (violations["direction"] == "up").all()
    assert (violations["phase"] == "Phase II").all()
    assert violations["lambda"].eq(0.20).all()
    assert violations["L"].eq(3.0).all()
    assert 13 not in violations["source_row"].tolist()
    assert violations["valid_observation_index"].is_unique
    assert violations["valid_observation_index"].max() == 13
    series = pd.read_csv(output_paths["ewma_series"])
    assert series.columns.tolist() == EXPECTED_EWMA_SERIES_COLUMNS
    assert len(series) == 13
    assert series["source_row"].tolist() == [6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19]
    assert series["violation"].sum() == len(violations)
    summary = json.loads(output_paths["ewma_summary"].read_text(encoding="utf-8"))
    assert summary["lambda"] == pytest.approx(0.20)
    assert summary["L"] == pytest.approx(3.0)
    assert summary["total_violations"] == len(violations)
    assert summary["direction_counts"]["up"] == len(violations)
    assert summary["valid_observations_per_sensor"] == {"sensor_e": 13}
    assert summary["we_ewma_overlap_lots"]["sensor_e"]["ewma_lots"] == len(
        violations["source_row"].unique()
    )
    for key in ("methodology", "limitations", "initialization",
                "sigma_source", "paths"):
        assert key in summary


def test_run_rejects_bad_ewma_config(tmp_path):
    config_path = _write_run_config(tmp_path, ewma_lambda=1.5)
    _write_run_fixture(tmp_path)
    with pytest.raises(ValueError, match="ewma_lambda"):
        run(config_path)
    config_path = _write_run_config(tmp_path, ewma_L=0.0)
    with pytest.raises(ValueError, match="ewma_L"):
        run(config_path)


def test_run_ewma_deterministic(tmp_path):
    config_path = _write_run_config(tmp_path)
    _write_run_fixture(tmp_path)
    first = run(config_path)
    first_bytes = {key: path.read_bytes() for key, path in first.items()}
    assert run(config_path) is not None
    assert {key: path.read_bytes() for key, path in first.items()} == first_bytes
