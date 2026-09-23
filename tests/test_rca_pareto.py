"""Tests for P4-002 Scrap and downtime Pareto analysis."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.rca_pareto import (
    compute_downtime_pareto,
    compute_line_level_pareto,
    compute_scrap_pareto,
    run,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
QUALITY_CSV = REPO_ROOT / "data" / "processed" / "mes_quality_events.csv"
DOWNTIME_CSV = REPO_ROOT / "data" / "processed" / "mes_downtime_events.csv"
MES_SUMMARY_JSON = REPO_ROOT / "reports" / "mes_simulation_summary.json"


def test_compute_scrap_pareto_synthetic_fixture():
    df = pd.DataFrame(
        {
            "defect_cause": ["Cause A", "Cause B", "Cause C", "Cause D"],
            "scrap_cost": [500.0, 300.0, 150.0, 50.0],
            "units_affected": [50, 30, 15, 5],
        }
    )
    pareto_df, summary = compute_scrap_pareto(df, top_n=3)

    assert len(pareto_df) == 4
    assert pareto_df["rank"].tolist() == [1, 2, 3, 4]
    assert pareto_df["defect_cause"].tolist() == ["Cause A", "Cause B", "Cause C", "Cause D"]
    assert pareto_df["scrap_cost_share"].tolist() == pytest.approx([0.50, 0.30, 0.15, 0.05])
    assert pareto_df["cumulative_scrap_cost_share"].tolist() == pytest.approx([0.50, 0.80, 0.95, 1.00])
    assert summary["total_scrap_cost"] == pytest.approx(1000.0)
    assert summary["total_units_affected"] == 100
    assert summary["top_n_causes"] == ["Cause A", "Cause B", "Cause C"]
    assert summary["top_n_scrap_cost"] == pytest.approx(950.0)
    assert summary["top_n_scrap_cost_share"] == pytest.approx(0.95)


def test_compute_downtime_pareto_synthetic_fixture():
    df = pd.DataFrame(
        {
            "reason": ["breakdown", "minor_stop", "planned_maint", "changeover"],
            "duration_min": [100.0, 60.0, 30.0, 10.0],
            "oee_bucket": ["Availability", "Performance", "Planned", "Availability"],
            "planned": [0, 0, 1, 0],
        }
    )
    pareto_all, summary_all = compute_downtime_pareto(df, top_n=2, exclude_planned=False)
    assert len(pareto_all) == 4
    assert summary_all["total_duration_min"] == pytest.approx(200.0)
    assert summary_all["top_n_reasons"] == ["breakdown", "minor_stop"]
    assert summary_all["top_n_duration_share"] == pytest.approx(0.80)

    pareto_unplanned, summary_unplanned = compute_downtime_pareto(df, top_n=2, exclude_planned=True)
    assert len(pareto_unplanned) == 3
    assert summary_unplanned["total_duration_min"] == pytest.approx(170.0)
    assert summary_unplanned["top_n_duration_share"] == pytest.approx(160.0 / 170.0)


def test_empty_dataframe_pareto_edge_case():
    empty = pd.DataFrame()
    scrap_df, scrap_sum = compute_scrap_pareto(empty)
    assert scrap_df.empty
    assert scrap_sum["total_scrap_cost"] == 0.0
    assert scrap_sum["top_n_causes"] == []

    dt_df, dt_sum = compute_downtime_pareto(empty)
    assert dt_df.empty
    assert dt_sum["total_duration_min"] == 0.0
    assert dt_sum["top_n_reasons"] == []


def test_pareto_reconciliation_with_mes_simulation_facts():
    df_quality = pd.read_csv(QUALITY_CSV)
    df_downtime = pd.read_csv(DOWNTIME_CSV)
    mes_sum = json.loads(MES_SUMMARY_JSON.read_text(encoding="utf-8"))

    scrap_df, scrap_sum = compute_scrap_pareto(df_quality, top_n=3)
    # Total scrap units match MES summary
    assert scrap_sum["total_units_affected"] == mes_sum["scrap_count"]
    assert scrap_sum["total_units_affected"] == 38047
    # Top 3 scrap causes explain >= 60% of scrap cost
    assert scrap_sum["top_n_scrap_cost_share"] >= 0.60
    assert scrap_sum["top_n_scrap_cost_share"] == pytest.approx(0.74375, rel=1e-3)
    assert scrap_sum["top_n_causes"] == ["dimensional", "surface defect", "contamination"]

    # Cumulative shares start at rank 1 and monotonically reach 1.0
    cum_shares = scrap_df["cumulative_scrap_cost_share"].tolist()
    assert cum_shares[-1] == pytest.approx(1.0)
    assert all(x <= y for x, y in zip(cum_shares[:-1], cum_shares[1:]))

    # Downtime analysis
    dt_df, dt_sum = compute_downtime_pareto(df_downtime, top_n=3, exclude_planned=False)
    assert dt_sum["total_event_count"] == mes_sum["downtime_event_count"]
    assert dt_sum["total_event_count"] == 24147
    assert dt_sum["top_n_reasons"] == ["minor_stop", "changeover", "breakdown"]
    assert dt_sum["top_n_duration_share"] >= 0.80

    # Unplanned downtime top 3
    _, dt_unplanned_sum = compute_downtime_pareto(df_downtime, top_n=3, exclude_planned=True)
    expected_unplanned_min = (
        mes_sum["downtime_minutes_by_bucket"]["Availability"]
        + mes_sum["downtime_minutes_by_bucket"]["Performance"]
    )
    assert dt_unplanned_sum["total_duration_min"] == pytest.approx(expected_unplanned_min, rel=1e-4)


def test_line_level_breakdowns():
    df_quality = pd.read_csv(QUALITY_CSV)
    df_downtime = pd.read_csv(DOWNTIME_CSV)

    line_results = compute_line_level_pareto(df_quality, df_downtime, top_n=3)
    assert set(line_results.keys()) == {"L1", "L2", "L3", "L4"}

    for line_id, results in line_results.items():
        assert results["scrap"]["total_units_affected"] > 0
        assert results["scrap"]["top_n_scrap_cost_share"] >= 0.50
        assert results["downtime_unplanned"]["total_duration_min"] > 0


def test_run_produces_valid_reports(tmp_path):
    summary = run()
    assert "scrap" in summary
    assert "downtime_all_events" in summary
    assert "downtime_unplanned" in summary
    assert "key_findings" in summary

    scrap_csv = Path(summary["outputs"]["scrap_pareto"])
    downtime_csv = Path(summary["outputs"]["downtime_pareto"])
    summary_json = Path(summary["outputs"]["summary"])

    assert scrap_csv.is_file()
    assert downtime_csv.is_file()
    assert summary_json.is_file()

    df_scrap_read = pd.read_csv(scrap_csv)
    assert len(df_scrap_read) == 6
    assert set(df_scrap_read.columns) >= {"rank", "defect_cause", "scrap_cost", "scrap_cost_share", "cumulative_scrap_cost_share"}
