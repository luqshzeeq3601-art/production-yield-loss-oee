import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.spc_engine import compute_imr_limits, evaluate_we_rules, run

D2, D3, D4 = 1.128, 0.0, 3.267

EXPECTED_LIMIT_COLUMNS = [
    "sensor", "phase1_valid_n", "phase1_mean", "mrbar", "sigma_estimate",
    "i_lcl", "i_ucl", "mr_lcl", "mr_ucl", "status",
]
EXPECTED_VIOLATION_COLUMNS = [
    "sensor", "source_row", "timestamp", "value", "rule", "centerline",
    "sigma", "z_score", "phase", "window_start_row", "window_end_row",
]
EXPECTED_PCHART_COLUMNS = [
    "date", "total_lots", "fail_lots", "defect_rate", "pbar", "lcl",
    "ucl", "low_volume", "violation",
]


def _we(values, mean=0.0, sigma=1.0):
    values = np.asarray(values, dtype=float)
    rows = np.arange(values.size)
    stamps = np.array([f"2024-01-01 00:00:{i:02d}" for i in range(values.size)])
    return evaluate_we_rules(values, rows, stamps, mean, sigma, "s")


def test_imr_known_values():
    limits = compute_imr_limits(np.array([2.0, 4.0, 6.0, 8.0, 10.0]), 2, D2, D3, D4)
    assert limits["status"] == "ok"
    assert limits["n"] == 5
    assert limits["mean"] == pytest.approx(6.0)
    assert limits["mrbar"] == pytest.approx(2.0)
    assert limits["sigma"] == pytest.approx(2.0 / D2)
    assert limits["i_ucl"] == pytest.approx(6.0 + 3.0 * 2.0 / D2)
    assert limits["i_lcl"] == pytest.approx(6.0 - 3.0 * 2.0 / D2)
    assert limits["mr_ucl"] == pytest.approx(3.267 * 2.0)
    assert limits["mr_lcl"] == pytest.approx(0.0)


def test_imr_insufficient_zero_nan():
    short = compute_imr_limits(np.array([1.0]), 2, D2, D3, D4)
    assert short["status"] == "insufficient_data"
    assert np.isnan(short["sigma"])
    zero = compute_imr_limits(np.array([5.0, 5.0, 5.0, 5.0]), 2, D2, D3, D4)
    assert zero["status"] == "zero_variation"
    assert zero["sigma"] == pytest.approx(0.0)
    gappy = compute_imr_limits(np.array([1.0, np.nan, 3.0]), 2, D2, D3, D4)
    assert gappy["status"] == "ok"
    assert gappy["n"] == 2
    assert gappy["mean"] == pytest.approx(2.0)


def test_we1_known_violation():
    records = _we([0.0, 0.0, 3.5, 0.0])
    assert [(r["rule"], r["source_row"]) for r in records] == [("WE1", 2)]
    assert records[0]["z_score"] == pytest.approx(3.5)
    assert records[0]["phase"] == "Phase II"


def test_we2_same_side_and_opposite():
    records = _we([0.0, 2.5, 2.5])
    assert [(r["rule"], r["source_row"]) for r in records] == [("WE2", 2)]
    assert _we([2.5, -2.5, 0.5]) == []
    assert [(r["rule"], r["source_row"]) for r in _we([0.0, -2.1, -2.2])] == [("WE2", 2)]


def test_we3_same_side_and_opposite():
    records = _we([0.0, 1.5, 1.5, 1.5, 1.5])
    assert [(r["rule"], r["source_row"]) for r in records] == [("WE3", 4)]
    assert _we([1.5, 1.5, 1.5, -1.5, 0.2]) == []


def test_we4_runs_and_overlaps():
    assert [(r["rule"], r["source_row"]) for r in _we([0.5] * 8)] == [("WE4", 7)]
    assert [(r["rule"], r["source_row"]) for r in _we([0.5] * 9)] == [
        ("WE4", 7), ("WE4", 8),
    ]
    assert _we([0.5] * 7 + [-0.5]) == []
    assert _we([0.0] * 8) == []


def test_we_preserves_lot_identity_and_multi_rule():
    values = np.array([1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 5.0])
    rows = np.array([100, 101, 102, 103, 104, 105, 106, 107, 108])
    stamps = np.array(["t"] * 9)
    records = evaluate_we_rules(values, rows, stamps, 0.0, 1.0, "s")
    by_rule = {}
    for record in records:
        by_rule.setdefault(record["rule"], []).append(record["source_row"])
    assert by_rule["WE4"] == [107, 108]
    assert by_rule["WE1"] == [108]
    assert by_rule["WE3"] == [104, 105, 106, 107, 108]
    assert "WE2" not in by_rule
    first_we4 = next(r for r in records if r["rule"] == "WE4")
    assert (first_we4["window_start_row"], first_we4["window_end_row"]) == (100, 107)


def _write_run_config(tmp_path):
    config = {
        "paths": {
            "raw": str(tmp_path / "raw"),
            "interim": str(tmp_path / "interim"),
            "processed": str(tmp_path / "processed"),
            "reports": str(tmp_path / "reports"),
        },
        "database": {},
        "cost_assumptions": {},
        "spc": {
            "phase_i_fraction": 0.30,
            "phase1_fraction": 0.30,
            "mr_d2": D2,
            "mr_d3": D3,
            "mr_d4": D4,
            "sigma_levels": [1, 2, 3],
            "min_phase1_observations": 2,
            "p_chart_min_daily_n": 10,
            "ewma_lambda": 0.20,
            "outputs": {
                "limits": str(tmp_path / "limits.csv"),
                "violations": str(tmp_path / "violations.csv"),
                "p_chart": str(tmp_path / "pchart.csv"),
                "summary": str(tmp_path / "summary.json"),
            },
        },
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
    sensor_x = [
        10.0, 11.0, 100.0, 9.0, 10.5, 9.5,
        10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 30.0, 10.3,
        9.7, 10.0, 10.2, 9.8, 10.1, 10.0,
    ]
    frame = pd.DataFrame(
        {
            "timestamp": stamps,
            "target": target,
            "sensor_x": sensor_x,
            "sensor_y": 5.0,
        }
    )
    frame.to_csv(tmp_path / "cleaned.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        {"sensor": ["sensor_x", "sensor_y"], "selected": [True, True],
         "aggregate_rank": [1.0, 2.0]}
    ).to_csv(tmp_path / "ranking.csv", index=False, lineterminator="\n")
    (tmp_path / "screening.json").write_text(
        json.dumps({"screening_rows": 6, "window_boundary_timestamp": str(stamps[5])}),
        encoding="utf-8",
    )


def test_run_pass_only_limits_and_leakage(tmp_path):
    config_path = _write_run_config(tmp_path)
    _write_run_fixture(tmp_path)
    output_paths = run(config_path)
    limits = pd.read_csv(output_paths["limits"])
    assert limits.columns.tolist() == EXPECTED_LIMIT_COLUMNS
    row_x = limits.loc[limits["sensor"] == "sensor_x"].iloc[0]
    assert row_x["status"] == "ok"
    assert row_x["phase1_valid_n"] == 5
    assert row_x["phase1_mean"] == pytest.approx(10.0)
    assert row_x["mrbar"] == pytest.approx(1.375)
    assert row_x["sigma_estimate"] == pytest.approx(1.375 / D2)
    assert limits.loc[limits["sensor"] == "sensor_y"].iloc[0]["status"] == "zero_variation"
    violations = pd.read_csv(output_paths["violations"])
    assert violations.columns.tolist() == EXPECTED_VIOLATION_COLUMNS
    we1 = violations[(violations["sensor"] == "sensor_x") & (violations["rule"] == "WE1")]
    assert we1["source_row"].tolist() == [12]
    assert (violations["sensor"] != "sensor_y").all()
    assert (violations["phase"] == "Phase II").all()


def test_run_pchart_baseline_and_schema(tmp_path):
    config_path = _write_run_config(tmp_path)
    _write_run_fixture(tmp_path)
    output_paths = run(config_path)
    pchart = pd.read_csv(output_paths["p_chart"])
    assert pchart.columns.tolist() == EXPECTED_PCHART_COLUMNS
    assert pchart["pbar"].tolist() == pytest.approx([1 / 6] * len(pchart))
    assert ((pchart["lcl"] >= 0) & (pchart["ucl"] <= 1)).all()
    assert pchart["low_volume"].all()
    summary = json.loads(output_paths["summary"].read_text(encoding="utf-8"))
    assert summary["phase1_lots"] == 6
    assert summary["phase2_lots"] == 14
    assert summary["valid_charts"] == 1
    assert summary["invalid_charts"] == {"sensor_y": "zero_variation"}
    assert summary["pbar"] == pytest.approx(1 / 6)
    for key in ("methodology", "limitations", "violations_by_rule",
                "violations_by_sensor", "paths", "mr_constants"):
        assert key in summary


def test_run_boundary_mismatch_rejected(tmp_path):
    config_path = _write_run_config(tmp_path)
    _write_run_fixture(tmp_path)
    screening = json.loads((tmp_path / "screening.json").read_text(encoding="utf-8"))
    screening["screening_rows"] = 7
    (tmp_path / "screening.json").write_text(json.dumps(screening), encoding="utf-8")
    with pytest.raises(ValueError, match="boundary"):
        run(config_path)


def test_run_deterministic_outputs(tmp_path):
    config_path = _write_run_config(tmp_path)
    _write_run_fixture(tmp_path)
    first = run(config_path)
    first_bytes = {key: path.read_bytes() for key, path in first.items()}
    assert run(config_path) is not None
    assert {key: path.read_bytes() for key, path in first.items()} == first_bytes
