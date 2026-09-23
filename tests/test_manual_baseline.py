"""Tests for P5-001 Manual Excel reporting baseline."""

from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from src.manual_baseline import MANUAL_STEPS, run


REPO_ROOT = Path(__file__).resolve().parents[1]
EXCEL_PATH = REPO_ROOT / "excel" / "manual_report_baseline.xlsx"
STEPS_CSV_PATH = REPO_ROOT / "reports" / "manual_reporting_steps.csv"
SUMMARY_JSON_PATH = REPO_ROOT / "reports" / "manual_reporting_baseline.json"


def test_manual_steps_integrity():
    assert len(MANUAL_STEPS) == 14
    total_minutes = sum(step["estimated_minutes"] for step in MANUAL_STEPS)
    assert total_minutes == 360  # Exactly 6.0 hours/week
    assert total_minutes / 60.0 == pytest.approx(6.0)

    for step in MANUAL_STEPS:
        assert step["step_id"] > 0
        assert step["phase"]
        assert step["task_name"]
        assert step["estimated_minutes"] > 0
        assert step["operator"]
        assert step["failure_modes"]


def test_run_produces_valid_reports_and_metrics():
    summary = run()

    assert summary["baseline_workflow"]["weekly_manual_hours"] == pytest.approx(6.0)
    assert summary["baseline_workflow"]["annual_manual_hours"] == pytest.approx(312.0)
    assert summary["automation_target"]["target_weekly_minutes"] <= 10.0
    assert summary["automation_target"]["expected_annual_hours_saved"] >= 300.0
    assert summary["automation_target"]["efficiency_gain_pct"] >= 95.0

    assert STEPS_CSV_PATH.is_file()
    assert SUMMARY_JSON_PATH.is_file()
    assert EXCEL_PATH.is_file()

    df_steps = pd.read_csv(STEPS_CSV_PATH)
    assert len(df_steps) == 14
    assert set(df_steps.columns) >= {"step_id", "phase", "task_name", "estimated_minutes", "failure_modes"}


def test_excel_workbook_sheets_and_formulas():
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=False)

    expected_sheets = {
        "Executive_Summary",
        "OEE_Summary",
        "Downtime_Summary",
        "Scrap_Summary",
        "Raw_Hourly_Production",
        "Raw_Downtime_Events",
        "Raw_Quality_Scrap",
    }
    assert expected_sheets.issubset(set(wb.sheetnames))

    # Check OEE Summary formulas
    ws_oee = wb["OEE_Summary"]
    assert str(ws_oee["H4"].value).startswith("=D4/C4")  # Availability formula
    assert str(ws_oee["I4"].value).startswith("=E4/D4")  # Performance formula
    assert str(ws_oee["J4"].value).startswith("=G4/F4")  # Quality formula
    assert str(ws_oee["K4"].value).startswith("=H4*I4*J4")  # OEE formula

    # Check Downtime Summary formulas
    ws_dt = wb["Downtime_Summary"]
    assert str(ws_dt["F4"].value).startswith("=E4/$E$10")  # Share formula
    assert str(ws_dt["G4"].value).startswith("=SUM($E$4:E4)/$E$10")  # Cumulative formula

    # Check Scrap Summary formulas
    ws_sc = wb["Scrap_Summary"]
    assert str(ws_sc["E4"].value).startswith("=D4/$D$10")  # Cost share formula
    assert str(ws_sc["F4"].value).startswith("=SUM($D$4:D4)/$D$10")  # Cumulative cost share
