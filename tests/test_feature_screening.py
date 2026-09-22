import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from scipy import stats

from src.feature_screening import benjamini_hochberg, run

EXPECTED_COLUMNS = [
    "sensor",
    "valid_pass_n",
    "valid_fail_n",
    "missing_rate",
    "point_biserial_r",
    "abs_point_biserial_r",
    "ks_statistic",
    "ks_pvalue",
    "ks_qvalue",
    "mannwhitney_statistic",
    "mannwhitney_pvalue",
    "mannwhitney_qvalue",
    "effect_size",
    "aggregate_rank",
    "redundant_with",
    "selected",
]


def _write_config(tmp_path, **overrides):
    params = {
        "window_fraction": 0.5,
        "fdr_alpha": 0.05,
        "correlation_threshold": 0.90,
        "min_selected": 2,
        "max_selected": 3,
        "min_fail_n": 3,
        "effect_floor": 0.20,
    }
    params.update(overrides)
    config = {
        "paths": {
            "raw": str(tmp_path / "raw"),
            "interim": str(tmp_path / "interim"),
            "processed": str(tmp_path / "processed"),
            "reports": str(tmp_path / "reports"),
        },
        "database": {},
        "cost_assumptions": {},
        "spc": {},
        "random_seed": 42,
        "secom": {"outputs": {"cleaned_data": str(tmp_path / "cleaned.csv")}},
        "screening": {
            **params,
            "outputs": {
                "ranking": str(tmp_path / "ranking.csv"),
                "summary": str(tmp_path / "summary.json"),
            },
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def _write_fixture(tmp_path):
    rng = np.random.default_rng(7)
    stamps = pd.date_range("2008-07-19", periods=60, freq="8h")
    target = np.array([1] * 6 + [0] * 24 + [1] * 6 + [0] * 24)
    order = np.argsort(stamps)
    frame = pd.DataFrame({"timestamp": stamps, "target": target})
    strong = np.where(
        frame["target"] == 1,
        rng.normal(3.0, 1.0, 60),
        rng.normal(0.0, 1.0, 60),
    )
    frame["sensor_strong"] = strong
    frame["sensor_twin"] = strong + rng.normal(0.0, 0.05, 60)
    frame["sensor_null"] = rng.normal(0.0, 1.0, 60)
    frame["sensor_nan"] = rng.normal(0.0, 1.0, 60)
    frame.loc[[3, 9, 15, 21, 27, 33, 39, 45, 51, 57], "sensor_nan"] = np.nan
    few = rng.normal(0.0, 1.0, 60)
    fail_positions = frame.index[frame["target"] == 1].tolist()
    few[fail_positions[2:]] = np.nan
    frame["sensor_few"] = few
    late = np.full(60, 0.5)
    late[30:] = np.linspace(0.0, 10.0, 30)
    frame["sensor_late"] = late
    frame.to_csv(tmp_path / "cleaned.csv", index=False, lineterminator="\n")
    return frame


def test_bh_correction_matches_hand_computation():
    assert benjamini_hochberg([0.01, 0.04, 0.03, 0.002, 0.5]) == pytest.approx(
        [0.025, 0.05, 0.05, 0.01, 0.5]
    )
    assert benjamini_hochberg([]) == []
    with pytest.raises(ValueError, match="p-values"):
        benjamini_hochberg([0.5, float("nan")])
    with pytest.raises(ValueError, match="p-values"):
        benjamini_hochberg([1.5])


def test_statistics_match_scipy_wiring(tmp_path):
    config_path = _write_config(tmp_path)
    target = np.array([0, 0, 1] * 8)
    passing = np.array([1.0, 2.0, 3.0, 1.5, 2.5, 3.5, 1.2, 2.2,
                        1.1, 2.1, 3.1, 1.6, 2.6, 3.6, 1.3, 2.3])
    failing = np.array([4.0, 5.0, 6.0, 4.5, 5.5, 6.5, 4.2, 5.2])
    values = np.empty(24)
    values[target == 0] = passing
    values[target == 1] = failing
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2008-07-19", periods=24, freq="8h"),
            "target": target,
            "sensor_a": values,
        }
    )
    frame.to_csv(tmp_path / "cleaned.csv", index=False, lineterminator="\n")
    output_paths = run(config_path)
    ranking = pd.read_csv(output_paths["ranking"])
    row = ranking.loc[ranking["sensor"] == "sensor_a"].iloc[0]
    window_passing = values[:12][target[:12] == 0]
    window_failing = values[:12][target[:12] == 1]
    assert row["valid_pass_n"] == window_passing.size == 8
    assert row["valid_fail_n"] == window_failing.size == 4
    paired_target = target[:12].astype(float)
    assert row["point_biserial_r"] == pytest.approx(
        stats.pointbiserialr(paired_target, values[:12]).statistic
    )
    assert row["ks_statistic"] == pytest.approx(
        stats.ks_2samp(window_passing, window_failing).statistic
    )
    assert row["ks_pvalue"] == pytest.approx(
        stats.ks_2samp(window_passing, window_failing).pvalue
    )
    assert row["mannwhitney_statistic"] == pytest.approx(
        stats.mannwhitneyu(window_passing, window_failing, alternative="two-sided").statistic
    )
    pooled = np.sqrt(
        ((window_passing.size - 1) * np.var(window_passing, ddof=1)
         + (window_failing.size - 1) * np.var(window_failing, ddof=1))
        / (window_passing.size + window_failing.size - 2)
    )
    assert row["effect_size"] == pytest.approx(
        (window_failing.mean() - window_passing.mean()) / pooled
    )


def test_window_boundary_and_phase_two_exclusion(tmp_path):
    config_path = _write_config(tmp_path)
    frame = _write_fixture(tmp_path)
    output_paths = run(config_path)
    summary = json.loads(output_paths["summary"].read_text(encoding="utf-8"))
    assert summary["source_rows"] == 60
    assert summary["screening_rows"] == 30
    assert summary["window_boundary_timestamp"] == str(frame["timestamp"].iloc[29])
    late = pd.read_csv(output_paths["ranking"]).set_index("sensor").loc["sensor_late"]
    assert late["valid_fail_n"] == 6
    assert not late["selected"]
    assert pd.isna(late["ks_qvalue"]) or bool(late["ks_qvalue"] > 0.05)


def test_target_excluded_and_schema(tmp_path):
    config_path = _write_config(tmp_path)
    _write_fixture(tmp_path)
    output_paths = run(config_path)
    ranking = pd.read_csv(output_paths["ranking"])
    assert ranking.columns.tolist() == EXPECTED_COLUMNS
    assert "target" not in ranking["sensor"].tolist()
    assert (ranking["valid_pass_n"] + ranking["valid_fail_n"] > 0).all()


def test_nan_and_insufficient_groups_unavailable(tmp_path):
    config_path = _write_config(tmp_path)
    _write_fixture(tmp_path)
    output_paths = run(config_path)
    ranking = pd.read_csv(output_paths["ranking"]).set_index("sensor")
    assert ranking.loc["sensor_few", "valid_fail_n"] == 2
    assert pd.isna(ranking.loc["sensor_few", "ks_pvalue"])
    assert pd.isna(ranking.loc["sensor_few", "aggregate_rank"])
    assert not ranking.loc["sensor_few", "selected"]
    assert ranking.loc["sensor_nan", "missing_rate"] == pytest.approx(5 / 30)


def test_strong_sensor_selected_and_ranked_first(tmp_path):
    config_path = _write_config(tmp_path)
    _write_fixture(tmp_path)
    output_paths = run(config_path)
    ranking = pd.read_csv(output_paths["ranking"])
    assert ranking.iloc[0]["sensor"] == "sensor_strong"
    strong = ranking.set_index("sensor").loc["sensor_strong"]
    assert bool(strong["selected"])
    assert bool(strong["ks_qvalue"] < 0.05)
    assert bool(abs(strong["effect_size"]) > 1.0)
    assert not ranking.set_index("sensor").loc["sensor_null"]["selected"]


def test_redundancy_marksensor_twin(tmp_path):
    config_path = _write_config(tmp_path)
    _write_fixture(tmp_path)
    output_paths = run(config_path)
    ranking = pd.read_csv(output_paths["ranking"]).set_index("sensor")
    assert ranking.loc["sensor_twin", "redundant_with"] == "sensor_strong"
    assert not ranking.loc["sensor_twin", "selected"]
    summary = json.loads(output_paths["summary"].read_text(encoding="utf-8"))
    assert {"sensor": "sensor_twin", "redundant_with": "sensor_strong"} in summary["redundant_sensors"]


def test_selection_bounds_and_determinism(tmp_path):
    config_path = _write_config(tmp_path)
    _write_fixture(tmp_path)
    first = run(config_path)
    first_bytes = {key: path.read_bytes() for key, path in first.items()}
    assert run(config_path) is not None
    assert {key: path.read_bytes() for key, path in first.items()} == first_bytes
    ranking = pd.read_csv(first["ranking"])
    selected = ranking.loc[ranking["selected"], "sensor"].tolist()
    assert 2 <= len(selected) <= 3
    summary = json.loads(first["summary"].read_text(encoding="utf-8"))
    assert summary["selected_sensors"] == selected
    assert summary["selected_count"] == len(selected)
    for key in (
        "source_rows", "screening_rows", "window_pass_count", "window_fail_count",
        "candidate_sensor_count", "fdr_alpha", "correlation_threshold",
        "methodology", "top_ranked", "paths",
    ):
        assert key in summary


def test_config_validation(tmp_path):
    config_path = _write_config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    del config["screening"]["fdr_alpha"]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        run(config_path)
    _write_config(tmp_path, window_fraction=1.5)
    with pytest.raises(ValueError, match="window_fraction"):
        run(config_path)
