import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.simulate_mes import (
    DOWNTIME_COLUMNS,
    HOURLY_COLUMNS,
    MANPOWER_COLUMNS,
    QUALITY_COLUMNS,
    STATION_COLUMNS,
    WORK_ORDER_COLUMNS,
    run,
)

CSV_KEYS = (
    "production_hourly",
    "downtime_events",
    "work_orders",
    "manpower_shifts",
    "station_operations",
    "quality_events",
)


def _write_config(tmp_path, *, days):
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "src" / "config.yaml").read_text(
            encoding="utf-8"
        )
    )
    config["mes"]["days"] = days
    for key, filename in (
        ("production_hourly", "hourly.csv"),
        ("downtime_events", "downtime.csv"),
        ("work_orders", "work_orders.csv"),
        ("manpower_shifts", "manpower.csv"),
        ("station_operations", "stations.csv"),
        ("quality_events", "quality.csv"),
        ("simulation_summary", "summary.json"),
    ):
        config["mes"]["outputs"][key] = str(tmp_path / filename)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


@pytest.fixture(scope="module")
def full_outputs(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("mes_full")
    return run(_write_config(tmp_path, days=180))


@pytest.fixture(scope="module")
def full_frames(full_outputs):
    return {
        key: pd.read_csv(full_outputs[key])
        for key in CSV_KEYS
    }


def _aggregate_oee(hourly):
    availability = hourly["run_time_min"].sum() / hourly["planned_time_min"].sum()
    performance = (hourly["ideal_cycle_time_s"] * hourly["total_count"]).sum() / (
        hourly["run_time_min"].sum() * 60.0
    )
    quality = hourly["good_count"].sum() / hourly["total_count"].sum()
    return availability, performance, quality, availability * performance * quality


def test_deterministic_repeated_runs_identical(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = run(_write_config(tmp_path / "a", days=20))
    second = run(_write_config(tmp_path / "b", days=20))
    for key in CSV_KEYS:
        assert second[key].read_bytes() == first[key].read_bytes()
    first_summary = json.loads(first["simulation_summary"].read_text(encoding="utf-8"))
    second_summary = json.loads(second["simulation_summary"].read_text(encoding="utf-8"))
    del first_summary["paths"]
    del second_summary["paths"]
    assert second_summary == first_summary


def test_factory_dimensions(full_frames):
    hourly = full_frames["production_hourly"]
    assert sorted(hourly["line"].unique().tolist()) == ["L1", "L2", "L3", "L4"]
    assert sorted(hourly["shift"].unique().tolist()) == ["A", "B", "C"]
    assert hourly["date"].nunique() == 180
    assert len(hourly) == 4 * 3 * 180 * 8
    assert len(full_frames["manpower_shifts"]) == 4 * 3 * 180
    assert len(full_frames["station_operations"]) == 4 * 5 * 3 * 180
    assert len(full_frames["work_orders"]) == 4 * 180


def test_schema_columns(full_frames):
    assert full_frames["production_hourly"].columns.tolist() == list(HOURLY_COLUMNS)
    assert full_frames["downtime_events"].columns.tolist() == list(DOWNTIME_COLUMNS)
    assert full_frames["work_orders"].columns.tolist() == list(WORK_ORDER_COLUMNS)
    assert full_frames["manpower_shifts"].columns.tolist() == list(MANPOWER_COLUMNS)
    assert full_frames["station_operations"].columns.tolist() == list(STATION_COLUMNS)
    assert full_frames["quality_events"].columns.tolist() == list(QUALITY_COLUMNS)


def test_unique_ids(full_frames):
    events = full_frames["downtime_events"]
    assert events["event_id"].is_unique
    assert events["event_id"].str.match(r"^EV-\d{6}$").all()
    assert full_frames["work_orders"]["wo_id"].is_unique
    stations = full_frames["station_operations"]
    assert stations[["line", "station", "shift", "date"]].drop_duplicates().shape[0] == len(stations)


def test_invariants(full_frames):
    hourly = full_frames["production_hourly"]
    assert (hourly["planned_time_min"] > 0).all()
    assert (hourly["run_time_min"] <= hourly["planned_time_min"] + 1e-9).all()
    assert (hourly["good_count"] <= hourly["total_count"]).all()
    for column in ("total_count", "good_count", "scrap_count"):
        assert (hourly[column] >= 0).all()
    for column in ("availability", "performance", "quality", "oee"):
        assert ((hourly[column] >= 0) & (hourly[column] <= 1)).all()
    downtime = full_frames["downtime_events"]
    assert (downtime["duration_min"] >= 0).all()
    assert set(downtime["oee_bucket"].unique()) <= {"Availability", "Performance", "Quality", "Planned"}
    manpower = full_frames["manpower_shifts"]
    assert ((manpower["actual_headcount"] >= 0) & (manpower["actual_headcount"] <= manpower["planned_headcount"])).all()
    assert (manpower["gap"] >= 0).all()
    quality = full_frames["quality_events"]
    assert (quality["units_affected"] > 0).all()
    assert (quality["scrap_cost"] >= 0).all()


def test_oee_math_spotcheck(full_frames):
    sample = full_frames["production_hourly"].head(200)
    for row in sample.itertuples():
        assert row.availability == pytest.approx(
            row.run_time_min / row.planned_time_min, rel=1e-3
        )
        expected_performance = (
            (row.ideal_cycle_time_s * row.total_count) / (row.run_time_min * 60.0)
            if row.run_time_min > 0
            else 1.0
        )
        assert row.performance == pytest.approx(expected_performance, rel=1e-3)
        expected_quality = row.good_count / row.total_count if row.total_count > 0 else 1.0
        assert row.quality == pytest.approx(expected_quality)
        assert row.oee == pytest.approx(
            row.availability * row.performance * row.quality, rel=1e-3
        )


def test_overall_oee_in_band(full_outputs):
    summary = json.loads(full_outputs["simulation_summary"].read_text(encoding="utf-8"))
    assert 0.55 <= summary["overall"]["oee"] <= 0.75
    assert summary["overall"]["oee"] == pytest.approx(
        summary["overall"]["availability"]
        * summary["overall"]["performance"]
        * summary["overall"]["quality"]
    )


def test_line2_night_shift_performance_loss(full_frames):
    hourly = full_frames["production_hourly"]
    perf = {
        shift: _aggregate_oee(hourly[(hourly["line"] == "L2") & (hourly["shift"] == shift)])[1]
        for shift in ("A", "B", "C")
    }
    assert perf["C"] + 0.03 < perf["A"]
    assert perf["C"] + 0.03 < perf["B"]
    minor = full_frames["downtime_events"]
    minor_l2 = minor[(minor["line"] == "L2") & (minor["reason"] == "minor_stop")]
    counts = minor_l2.groupby("shift").size()
    assert counts["C"] > counts["A"]


def test_line3_tool_wear_quality_drift(full_frames):
    line3 = full_frames["production_hourly"]
    line3 = line3[line3["line"] == "L3"].copy()
    line3["day_index"] = (pd.to_datetime(line3["date"]) - pd.Timestamp("2024-01-01")).dt.days
    daily = line3.groupby("day_index").agg(scrap=("scrap_count", "sum"), total=("total_count", "sum"))
    daily["rate"] = daily["scrap"] / daily["total"]
    assert daily["rate"].corr(daily.index.to_series()) > 0.5
    assert daily["rate"].iloc[90:].mean() - daily["rate"].iloc[:90].mean() > 0.02


def test_supplier_quality_hold_event(full_frames):
    downtime = full_frames["downtime_events"]
    holds = downtime[downtime["supplier_tag"] == 1]
    assert len(holds) >= 1
    assert (holds["reason"] == "quality_hold").all()
    hourly = full_frames["production_hourly"]
    p2 = hourly[hourly["product"] == "P2"].copy()
    p2["day_index"] = (pd.to_datetime(p2["date"]) - pd.Timestamp("2024-01-01")).dt.days
    window = p2[(p2["day_index"] >= 90) & (p2["day_index"] < 98)]
    outside = p2[(p2["day_index"] < 90) | (p2["day_index"] >= 98)]
    window_rate = window["scrap_count"].sum() / window["total_count"].sum()
    outside_rate = outside["scrap_count"].sum() / outside["total_count"].sum()
    assert window_rate > outside_rate + 0.05


def test_station_data_supports_bottleneck_analysis(full_frames):
    stations = full_frames["station_operations"]
    assert set(stations["line"].unique()) == {"L1", "L2", "L3", "L4"}
    for line in ("L1", "L2", "L3", "L4"):
        group = stations[stations["line"] == line].copy()
        group["total_time"] = group["processing_time_s"] + group["wait_time_s"]
        means = group.groupby("station")["total_time"].mean()
        bottleneck = group[group["is_bottleneck"] == 1]["station"].iloc[0]
        assert means.idxmax() == bottleneck
        assert (group["processing_time_s"] > 0).all()
        assert (group["wait_time_s"] >= 0).all()
        assert (group["throughput_units"] >= 0).all()


def test_summary_reconciles_with_outputs(full_outputs, full_frames):
    summary = json.loads(full_outputs["simulation_summary"].read_text(encoding="utf-8"))
    hourly = full_frames["production_hourly"]
    assert summary["seed"] == 42
    assert summary["days"] == 180
    assert summary["total_count"] == int(hourly["total_count"].sum())
    assert summary["good_count"] == int(hourly["good_count"].sum())
    assert summary["scrap_count"] == int(hourly["scrap_count"].sum())
    assert summary["work_order_count"] == len(full_frames["work_orders"])
    assert summary["downtime_event_count"] == len(full_frames["downtime_events"])
    assert summary["manpower_records"] == len(full_frames["manpower_shifts"])
    assert summary["station_operation_count"] == len(full_frames["station_operations"])
    for key in ("overall", "line_oee", "shift_oee", "scenarios", "downtime_minutes_by_bucket"):
        assert key in summary
