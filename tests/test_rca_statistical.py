"""Tests for P4-003 Statistical Root Cause Analysis."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.rca_statistical import (
    analyze_line_shift_defect_rates,
    analyze_metropt3_contrasts,
    analyze_secom_sensor_contrasts,
    analyze_station_bottlenecks,
    run,
    verify_injected_scenarios,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PROD_CSV = REPO_ROOT / "data" / "processed" / "mes_production_hourly.csv"
DOWNTIME_CSV = REPO_ROOT / "data" / "processed" / "mes_downtime_events.csv"
STATION_CSV = REPO_ROOT / "data" / "processed" / "mes_station_operations.csv"
QUALITY_CSV = REPO_ROOT / "data" / "processed" / "mes_quality_events.csv"
METRO_CSV = REPO_ROOT / "data" / "processed" / "metropt3_readings.csv"
SECOM_CSV = REPO_ROOT / "data" / "processed" / "secom_cleaned.csv"
SCREENING_CSV = REPO_ROOT / "reports" / "feature_screening.csv"


def test_line_shift_defect_rate_chi2():
    df_prod = pd.read_csv(PROD_CSV)
    result = analyze_line_shift_defect_rates(df_prod)

    line_diff = result["line_differences"]
    assert line_diff["is_significant_005"] is True
    assert line_diff["p_value"] < 1e-10
    assert line_diff["degrees_of_freedom"] == 3

    # Check Line 3 is the elevated line
    records = {r["line"]: r["defect_rate"] for r in line_diff["records"]}
    assert records["L3"] > 0.05
    assert records["L1"] < 0.03
    assert records["L2"] < 0.03
    assert records["L4"] < 0.03


def test_station_bottleneck_identification():
    df_st = pd.read_csv(STATION_CSV)
    df_dt = pd.read_csv(DOWNTIME_CSV)

    st_df, summary = analyze_station_bottlenecks(df_st, df_dt)
    assert summary["bottleneck_station"] == "Processing"
    assert summary["station_count"] == 5

    s3_row = st_df[st_df["station_name"] == "Processing"].iloc[0]
    assert s3_row["is_bottleneck"] == 1
    assert s3_row["mean_processing_time_s"] == pytest.approx(65.0, abs=1.0)
    assert s3_row["mean_wait_time_s"] > 100.0


def test_scenario_rediscovery_l2_l3_supplier():
    df_prod = pd.read_csv(PROD_CSV)
    df_dt = pd.read_csv(DOWNTIME_CSV)
    df_q = pd.read_csv(QUALITY_CSV)

    scenarios = verify_injected_scenarios(df_prod, df_dt, df_q)

    # Scenario 1: L2 Night Shift minor stops
    sc1 = scenarios["scenario_1_line2_night_shift"]
    assert sc1["discovered"] is True
    assert sc1["observed_multiplier"] >= 2.5
    assert sc1["performance_gap_c_vs_a"] > 0.03

    # Scenario 2: L3 tool wear progressive deterioration
    sc2 = scenarios["scenario_2_line3_tool_wear"]
    assert sc2["discovered"] is True
    assert sc2["h2_defect_rate"] > sc2["h1_defect_rate"]
    assert sc2["p_value"] < 1e-10
    assert sc2["tool_wear_scrap_units_by_half"]["H2_second_half"] > sc2["tool_wear_scrap_units_by_half"]["H1_first_half"]

    # Scenario 3: Supplier quality hold on P2
    sc3 = scenarios["scenario_3_supplier_quality_hold"]
    assert sc3["discovered"] is True
    assert sc3["p2_supplier_scrap_units"] > 500
    assert sc3["p2_share_of_supplier_scrap"] > 0.50


def test_metropt3_failure_window_contrasts():
    df_metro = pd.read_csv(METRO_CSV)
    contrasts = analyze_metropt3_contrasts(df_metro)

    assert "analog_signals" in contrasts
    signals = contrasts["analog_signals"]
    assert set(signals.keys()) >= {"TP2", "TP3", "H1", "DV_pressure", "Reservoirs", "Oil_temperature", "Motor_current"}

    # Pressure TP2 and Oil temperature are noticeably higher in failure windows
    assert signals["TP2"]["failure_window"]["mean"] > signals["TP2"]["normal"]["mean"]
    assert signals["Oil_temperature"]["failure_window"]["mean"] > signals["Oil_temperature"]["normal"]["mean"]


def test_secom_sensor_contrasts():
    df_secom = pd.read_csv(SECOM_CSV)
    df_screening = pd.read_csv(SCREENING_CSV)

    contrasts = analyze_secom_sensor_contrasts(df_secom, df_screening, top_k=10)
    assert "screened_sensors" in contrasts
    assert len(contrasts["screened_sensors"]) == 10
    assert "methodological_note" in contrasts

    for sensor, data in contrasts["screened_sensors"].items():
        assert "pass_mean" in data
        assert "fail_mean" in data
        assert "cohens_d" in data
        assert "mann_whitney_p_value" in data


def test_run_produces_valid_rca_report():
    summary = run()
    assert "line_shift_defect_rates" in summary
    assert "station_bottlenecks" in summary
    assert "scenario_rediscovery" in summary
    assert "metropt3_failure_contrasts" in summary
    assert "secom_sensor_contrasts" in summary
    assert "key_conclusions" in summary

    rep_path = REPO_ROOT / "reports" / "rca_statistical_summary.json"
    assert rep_path.is_file()
    loaded = json.loads(rep_path.read_text(encoding="utf-8"))
    assert loaded["scenario_rediscovery"]["scenario_1_line2_night_shift"]["discovered"] is True
    assert loaded["scenario_rediscovery"]["scenario_2_line3_tool_wear"]["discovered"] is True
    assert loaded["scenario_rediscovery"]["scenario_3_supplier_quality_hold"]["discovered"] is True
