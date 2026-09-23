"""Tests for P5-002 Power BI semantic model and DAX measures."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.powerbi_model import evaluate_dax_measures, reconcile_sql_and_dax, run


REPO_ROOT = Path(__file__).resolve().parents[1]
PROD_CSV = REPO_ROOT / "data" / "processed" / "mes_production_hourly.csv"
DOWNTIME_CSV = REPO_ROOT / "data" / "processed" / "mes_downtime_events.csv"
QUALITY_CSV = REPO_ROOT / "data" / "processed" / "mes_quality_events.csv"
MANPOWER_CSV = REPO_ROOT / "data" / "processed" / "mes_manpower_shifts.csv"
STATION_CSV = REPO_ROOT / "data" / "processed" / "mes_station_operations.csv"
SQL_SUMMARY_PATH = REPO_ROOT / "reports" / "mes_simulation_summary.json"


@pytest.fixture(scope="module")
def dax_eval_data():
    df_prod = pd.read_csv(PROD_CSV)
    df_dt = pd.read_csv(DOWNTIME_CSV)
    df_q = pd.read_csv(QUALITY_CSV)
    df_mp = pd.read_csv(MANPOWER_CSV)
    df_st = pd.read_csv(STATION_CSV)
    return evaluate_dax_measures(df_prod, df_dt, df_q, df_mp, df_st)


def test_dax_measures_reconciliation_within_01_pct(dax_eval_data):
    rec = reconcile_sql_and_dax(dax_eval_data, SQL_SUMMARY_PATH)
    assert rec["overall_status"] == "PASS"
    assert rec["max_relative_diff_pct"] <= 0.10
    assert rec["max_relative_diff_pct"] == pytest.approx(0.0, abs=1e-4)

    for metric_rec in rec["metrics"]:
        assert metric_rec["passes_01pct_tolerance"] is True
        assert metric_rec["relative_diff_pct"] <= 0.10


def test_dax_component_derivation_not_average(dax_eval_data):
    # Proves OEE = A * P * Q from component totals
    p = dax_eval_data["plant_overview"]
    assert p["oee"] == pytest.approx(p["availability"] * p["performance"] * p["quality"])
    assert p["availability"] == pytest.approx(0.9128898, rel=1e-5)
    assert p["performance"] == pytest.approx(0.8450305, rel=1e-5)
    assert p["quality"] == pytest.approx(0.9645769, rel=1e-5)
    assert p["oee"] == pytest.approx(0.7440937, rel=1e-5)


def test_powerbi_theme_json_validity():
    theme_path = REPO_ROOT / "powerbi" / "theme.json"
    assert theme_path.is_file()
    theme = json.loads(theme_path.read_text(encoding="utf-8"))

    assert "name" in theme
    assert "dataColors" in theme
    assert len(theme["dataColors"]) >= 6
    assert "visualStyles" in theme
    assert "card" in theme["visualStyles"]


def test_powerbi_model_mapping_csv():
    mapping_path = REPO_ROOT / "powerbi" / "model_mapping.csv"
    assert mapping_path.is_file()
    df_map = pd.read_csv(mapping_path)

    expected_tables = {
        "dim_date", "dim_line", "dim_time_shift", "dim_station_machine",
        "dim_product", "dim_downtime_reason", "dim_defect_cause", "dim_sensor",
        "fact_production_hourly", "fact_downtime_event", "fact_quality_scrap",
        "fact_quality_lot", "fact_manpower_shift", "fact_station_operation",
        "fact_spc_alert", "fact_sensor_reading"
    }
    assert expected_tables.issubset(set(df_map["table_name"]))
    assert set(df_map["table_type"].unique()) == {"Dimension", "Fact"}


def test_powerbi_measure_catalog_completeness():
    catalog_path = REPO_ROOT / "powerbi" / "measure_catalog.md"
    dax_path = REPO_ROOT / "powerbi" / "measures.dax"
    assert catalog_path.is_file()
    assert dax_path.is_file()

    dax_text = dax_path.read_text(encoding="utf-8")
    for measure_name in [
        "[Availability]", "[Performance]", "[Quality]", "[OEE]",
        "[Total Units]", "[Good Units]", "[Scrap Units]", "[Total Scrap Cost]",
        "[Downtime Hours]", "[Manpower Gap]", "[Capacity Utilization %]",
        "[Alert Precision %]"
    ]:
        assert measure_name in dax_text


def test_run_powerbi_model_validator():
    summary = run()
    assert "dax_evaluation" in summary
    assert "reconciliation" in summary
    assert summary["reconciliation"]["overall_status"] == "PASS"

    out_path = REPO_ROOT / "reports" / "powerbi_reconciliation_summary.json"
    assert out_path.is_file()
