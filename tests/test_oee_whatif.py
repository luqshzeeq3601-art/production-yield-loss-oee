"""Tests for P4-004 OEE what-if recovery and recoverable value modeling."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.oee_whatif import (
    compute_baseline_components,
    generate_sensitivity_matrix,
    model_loss_reduction_scenario,
    run,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PROD_CSV = REPO_ROOT / "data" / "processed" / "mes_production_hourly.csv"
DOWNTIME_CSV = REPO_ROOT / "data" / "processed" / "mes_downtime_events.csv"
QUALITY_CSV = REPO_ROOT / "data" / "processed" / "mes_quality_events.csv"


@pytest.fixture(scope="module")
def baseline_data():
    df_prod = pd.read_csv(PROD_CSV)
    df_dt = pd.read_csv(DOWNTIME_CSV)
    df_q = pd.read_csv(QUALITY_CSV)
    baseline = compute_baseline_components(df_prod, df_q, df_dt)
    return baseline, df_q, df_dt


def test_baseline_components_reconciles_with_mes_facts(baseline_data):
    baseline, _, _ = baseline_data
    assert baseline["total_count"] == 1074073
    assert baseline["good_count"] == 1036026
    assert baseline["scrap_count"] == 38047
    assert baseline["total_scrap_cost"] == pytest.approx(555891.0)
    assert baseline["availability"] == pytest.approx(0.9128898, rel=1e-5)
    assert baseline["performance"] == pytest.approx(0.8450305, rel=1e-5)
    assert baseline["quality"] == pytest.approx(0.9645769, rel=1e-5)
    assert baseline["oee"] == pytest.approx(0.7440937, rel=1e-5)

    assert baseline["top3_scrap_causes"] == ["dimensional", "surface defect", "contamination"]
    assert baseline["top3_scrap_cost"] == pytest.approx(413447.0)
    assert baseline["top3_scrap_units"] == 28087


def test_scrap_only_scenario_math(baseline_data):
    baseline, _, _ = baseline_data
    econ_cfg = {"unit_contribution_margin": 22.50, "annual_horizon_days": 365, "baseline_horizon_days": 180}
    sc = model_loss_reduction_scenario(baseline, 0.30, "scrap_only", econ_cfg)

    # Availability and Performance unchanged
    assert sc["availability_new"] == pytest.approx(baseline["availability"])
    assert sc["performance_new"] == pytest.approx(baseline["performance"])
    # Quality improved
    assert sc["quality_new"] > baseline["quality"]
    assert sc["quality_new"] == pytest.approx((1036026 + 28087 * 0.30) / 1074073)
    # OEE derived from components
    assert sc["oee_new"] == pytest.approx(sc["availability_new"] * sc["performance_new"] * sc["quality_new"])
    assert sc["oee_delta_pts"] == pytest.approx(0.60518, rel=1e-3)
    assert sc["annual_scrap_cost_avoided"] == pytest.approx(413447.0 * 0.30 * (365 / 180))


def test_downtime_only_scenario_math(baseline_data):
    baseline, _, _ = baseline_data
    econ_cfg = {"unit_contribution_margin": 22.50, "annual_horizon_days": 365, "baseline_horizon_days": 180}
    sc = model_loss_reduction_scenario(baseline, 0.30, "downtime_only", econ_cfg)

    # Quality unchanged
    assert sc["quality_new"] == pytest.approx(baseline["quality"])
    # Availability and Performance both improve
    assert sc["availability_new"] > baseline["availability"]
    assert sc["performance_new"] > baseline["performance"]
    # OEE derived from components
    assert sc["oee_new"] == pytest.approx(sc["availability_new"] * sc["performance_new"] * sc["quality_new"])
    assert sc["oee_delta_pts"] == pytest.approx(3.9234, rel=1e-3)


def test_combined_scenario_math_and_annual_value(baseline_data):
    baseline, _, _ = baseline_data
    econ_cfg = {"unit_contribution_margin": 22.50, "annual_horizon_days": 365, "baseline_horizon_days": 180}
    sc = model_loss_reduction_scenario(baseline, 0.30, "combined", econ_cfg)

    assert sc["oee_new"] == pytest.approx(0.78956, rel=1e-4)
    assert sc["oee_delta_pts"] == pytest.approx(4.5466, rel=1e-3)
    assert sc["annual_extra_good_units"] == pytest.approx(63864.0, abs=100)
    assert sc["total_annual_recoverable_value"] == pytest.approx(1688452.14, rel=1e-3)


def test_sensitivity_matrix_monotonicity(baseline_data):
    baseline, _, _ = baseline_data
    econ_cfg = {"unit_contribution_margin": 22.50, "annual_horizon_days": 365, "baseline_horizon_days": 180}
    rates = [0.10, 0.20, 0.30, 0.40, 0.50]
    sens_df = generate_sensitivity_matrix(baseline, rates, econ_cfg)

    assert len(sens_df) == 15  # 5 rates x 3 modes

    for mode in ["scrap_only", "downtime_only", "combined"]:
        sub = sens_df[sens_df["scenario_mode"] == mode].sort_values("reduction_rate")
        oee_vals = sub["oee_new"].tolist()
        val_vals = sub["total_annual_recoverable_value"].tolist()
        assert all(x < y for x, y in zip(oee_vals[:-1], oee_vals[1:]))
        assert all(x < y for x, y in zip(val_vals[:-1], val_vals[1:]))


def test_run_produces_valid_whatif_reports():
    summary = run()
    assert "baseline" in summary
    assert "headline_scenarios_30pct" in summary
    assert "key_impact_summary" in summary
    assert "outputs" in summary

    scenarios_csv = Path(summary["outputs"]["scenarios_csv"])
    sensitivity_csv = Path(summary["outputs"]["sensitivity_csv"])
    summary_json = Path(summary["outputs"]["summary_json"])

    assert scenarios_csv.is_file()
    assert sensitivity_csv.is_file()
    assert summary_json.is_file()

    df_scenarios = pd.read_csv(scenarios_csv)
    assert len(df_scenarios) == 3
    df_sens = pd.read_csv(sensitivity_csv)
    assert len(df_sens) == 15
