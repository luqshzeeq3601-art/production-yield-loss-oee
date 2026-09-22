import json

import numpy as np
import pandas as pd
import pytest
import yaml

from src.spc_backtest import _excursions, compute_metrics, group_excursions, manual_detection_timestamp, run


SELECTED = [
    "sensor_021", "sensor_000", "sensor_064", "sensor_122", "sensor_022",
    "sensor_090", "sensor_076", "sensor_562", "sensor_033", "sensor_125",
]
UCL = 24.815413111657534


def test_metrics_baseline_and_excursion_boundaries():
    metrics = compute_metrics(8, 2, 2, 88)
    assert metrics["precision"] == pytest.approx(0.8)
    assert metrics["recall"] == pytest.approx(0.8)
    assert metrics["specificity"] == pytest.approx(88 / 90)
    assert metrics["false_alarms_per_100_lots"] == pytest.approx(2.0)
    assert compute_metrics(0, 0, 0, 0)["F1"] is None
    assert manual_detection_timestamp(pd.Timestamp("2026-01-10 08:00")) == pd.Timestamp("2026-01-11 08:00")
    assert manual_detection_timestamp(pd.Timestamp("2026-12-31 23:59")) == pd.Timestamp("2027-01-01 08:00")
    assert group_excursions([5, 6, 8, 12]) == [[5, 6, 8], [12]]
    assert group_excursions([5, 9]) == [[5], [9]]


def test_excursion_window_alert_does_not_count_as_failing_lot_catch():
    lots = pd.DataFrame({
        "source_row": [10, 11, 12],
        "timestamp": pd.date_range("2026-01-10 10:00", periods=3, freq="h"),
        "target": [1, 0, 1],
    })
    alerts = {method: {} for method in ("WE", "EWMA", "T2", "WE+EWMA", "WE+EWMA+T2")}
    alerts["T2"] = {11: pd.Timestamp("2026-01-10 11:00")}
    result = pd.DataFrame(_excursions(lots, alerts)).query("method == 'T2'").iloc[0]
    assert result.first_window_alert_row == 11
    assert pd.isna(result.first_failing_alert_row)
    assert bool(result.window_alert_before_manual)
    assert not bool(result.caught_before_manual)
    assert pd.isna(result.hours_saved)


def _write_config(tmp_path):
    output_paths = {name: str(tmp_path / f"{name}.csv") for name in ("lots", "failures", "methods", "excursions")}
    output_paths["summary"] = str(tmp_path / "summary.json")
    config = {
        "paths": {"raw": str(tmp_path / "raw"), "interim": str(tmp_path / "interim"), "processed": str(tmp_path / "processed"), "reports": str(tmp_path / "reports")},
        "database": {},
        "cost_assumptions": {},
        "random_seed": 42,
        "spc": {
            "phase_i_fraction": 0.30,
            "ewma_lambda": 0.2,
            "ewma_L": 3.0,
            "hotelling_t2_alpha": 0.01,
            "outputs": {
                "limits": str(tmp_path / "limits.csv"),
                "violations": str(tmp_path / "we.csv"),
                "ewma_violations": str(tmp_path / "ewma.csv"),
                "summary": str(tmp_path / "spc_summary.json"),
                "ewma_summary": str(tmp_path / "ewma_summary.json"),
                "hotelling_t2_series": str(tmp_path / "t2series.csv"),
                "hotelling_t2_violations": str(tmp_path / "t2viol.csv"),
                "hotelling_t2_summary": str(tmp_path / "t2_summary.json"),
            },
        },
        "secom": {"outputs": {"cleaned_data": str(tmp_path / "cleaned.csv")}},
        "screening": {"window_fraction": 0.30, "outputs": {"summary": str(tmp_path / "screening.json")}},
        "backtest": {"excursion_max_gap_lots": 2, "outputs": output_paths},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _write_fixture(tmp_path):
    stamps = pd.date_range("2026-01-10", periods=12, freq="h")
    targets = [0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0]
    pd.DataFrame({"timestamp": stamps, "target": targets}).to_csv(tmp_path / "cleaned.csv", index=False, lineterminator="\n")
    boundary = 3
    common = {"selected_sensors": SELECTED, "phase1_boundary_timestamp": str(stamps[2])}
    (tmp_path / "screening.json").write_text(json.dumps({"selected_sensors": SELECTED, "screening_rows": boundary, "window_boundary_timestamp": str(stamps[2])}), encoding="utf-8")
    (tmp_path / "spc_summary.json").write_text(json.dumps({**common, "phase1_lots": boundary}), encoding="utf-8")
    (tmp_path / "ewma_summary.json").write_text(json.dumps({**common, "lambda": 0.2, "L": 3.0}), encoding="utf-8")
    (tmp_path / "t2_summary.json").write_text(json.dumps({**common, "phase1_lots": boundary, "phase2_lots": 9, "alpha": 0.01, "ucl": UCL}), encoding="utf-8")
    pd.DataFrame({"sensor": SELECTED}).to_csv(tmp_path / "limits.csv", index=False, lineterminator="\n")
    phase = lambda row: "Phase I" if row < boundary else "Phase II"
    pd.DataFrame({"sensor": [SELECTED[0]] * 4, "source_row": [5, 5, 9, 4], "timestamp": [stamps[5], stamps[5], stamps[9], stamps[4]], "phase": [phase(row) for row in [5, 5, 9, 4]], "rule": ["WE1", "WE4", "WE2", "WE1"]}).to_csv(tmp_path / "we.csv", index=False, lineterminator="\n")
    pd.DataFrame({"sensor": [SELECTED[1]], "source_row": [10], "timestamp": [stamps[10]], "phase": [phase(10)], "lambda": [0.2], "L": [3.0]}).to_csv(tmp_path / "ewma.csv", index=False, lineterminator="\n")
    pd.DataFrame({"source_row": range(12), "timestamp": stamps, "phase": [phase(row) for row in range(12)], "complete_case": [row not in {5, 8} for row in range(12)], "ucl": [UCL] * 12, "violation": [row == 10 for row in range(12)]}).to_csv(tmp_path / "t2series.csv", index=False, lineterminator="\n")
    pd.DataFrame({"source_row": [10], "timestamp": [stamps[10]], "phase": [phase(10)], "ucl": [UCL]}).to_csv(tmp_path / "t2viol.csv", index=False, lineterminator="\n")
    return stamps


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    import src.spc_backtest as backtest

    monkeypatch.setattr(backtest, "FROZEN_PHASE1_LOTS", 3)
    monkeypatch.setattr(backtest, "FROZEN_PHASE2_LOTS", 9)
    monkeypatch.setattr(backtest, "FROZEN_T2_COMPLETE_PHASE2_LOTS", 7)
    config = _write_config(tmp_path)
    return config, _write_fixture(tmp_path)


def test_dedup_coverage_confusion_latency_target_and_incremental(fixture):
    config, stamps = fixture
    paths = run(config)
    lots = pd.read_csv(paths["lots"]).set_index("source_row")
    assert len(lots) == 9
    assert bool(lots.loc[5, "we_alert"])
    assert not bool(lots.loc[5, "t2_available"])
    methods = pd.read_csv(paths["methods"]).set_index("method")
    assert methods.loc["WE", ["TP", "FP", "FN", "TN"]].tolist() == [2, 1, 1, 5]
    assert methods.loc["T2", ["eligible_lots", "unavailable_lots"]].tolist() == [7, 2]
    assert methods.loc["T2", ["eligible_only_TP", "eligible_only_FP", "eligible_only_FN", "eligible_only_TN"]].tolist() == [1, 0, 1, 5]
    assert methods.loc["WE+EWMA", "median_detection_latency_hours"] == pytest.approx(0)
    assert methods.loc["WE+EWMA", "pct_failures_before_manual"] == pytest.approx(100)
    failures = pd.read_csv(paths["failures"])
    assert not failures.duplicated(["source_row", "method"]).any()
    missed = failures.query("source_row == 10 and method == 'WE'").iloc[0]
    assert pd.isna(missed.hours_saved) and pd.isna(missed.new_latency_hours)
    observed = failures.query("source_row == 5 and method == 'WE'").iloc[0]
    assert pd.Timestamp(observed.alert_timestamp) == pd.Timestamp(stamps[5])
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert summary["target_assessment"]["WE"]["overall_target_status"] == "not_achieved"
    assert summary["target_assessment"]["WE+EWMA"]["overall_target_status"] == "achieved"
    assert summary["incremental_method_value"]["T2_extra_vs_WE"]["extra_TP"] == 1
    assert summary["same_lot_alert_availability_assumption"]
    assert all(not str(value).startswith(str(config.parent)) for value in summary["configured_output_filenames"].values())


@pytest.mark.parametrize(
    ("artifact", "mutate", "match"),
    [
        ("we.csv", lambda frame: frame.assign(timestamp="2025-01-01"), "timestamps"),
        ("ewma.csv", lambda frame: frame.assign(source_row=2), "stale|phase"),
        ("t2viol.csv", lambda frame: pd.concat([frame, frame], ignore_index=True), "unique"),
        ("t2viol.csv", lambda frame: frame.iloc[0:0], "row set"),
    ],
)
def test_rejects_misaligned_out_of_range_and_duplicate_artifacts(fixture, artifact, mutate, match):
    config, _ = fixture
    path = config.parent / artifact
    mutate(pd.read_csv(path)).to_csv(path, index=False, lineterminator="\n")
    with pytest.raises(ValueError, match=match):
        run(config)


def test_rejects_parameter_boundary_and_series_coverage_mismatch(fixture):
    config, _ = fixture
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    payload["spc"]["ewma_lambda"] = 0.3
    config.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="EWMA"):
        run(config)
    payload["spc"]["ewma_lambda"] = 0.2
    config.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    pd.read_csv(config.parent / "t2series.csv").iloc[:-1].to_csv(config.parent / "t2series.csv", index=False, lineterminator="\n")
    with pytest.raises(ValueError, match="every cleaned"):
        run(config)


def test_label_changes_do_not_move_alerts_and_reports_are_deterministic(fixture):
    config, _ = fixture
    first = run(config)
    before = pd.read_csv(first["lots"])[["source_row", "we_alert", "ewma_alert", "t2_alert"]]
    initial = {name: path.read_bytes() for name, path in first.items()}
    second = run(config)
    assert {name: path.read_bytes() for name, path in second.items()} == initial
    cleaned = pd.read_csv(config.parent / "cleaned.csv")
    cleaned.loc[7, "target"] = 1
    cleaned.to_csv(config.parent / "cleaned.csv", index=False, lineterminator="\n")
    after = pd.read_csv(run(config)["lots"])[["source_row", "we_alert", "ewma_alert", "t2_alert"]]
    pd.testing.assert_frame_equal(before, after)
