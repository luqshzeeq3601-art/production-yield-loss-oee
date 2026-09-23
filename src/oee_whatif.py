"""OEE What-If loss recovery and financial value model (P4-004).

Models transparent improvement scenarios for top identified losses:
- Recomputes OEE from components (Availability, Performance, Quality).
- Calculates incremental good units and annualizes from baseline horizon (180 days -> 365 days).
- Estimates recoverable value using dynamic economic assumptions from config.yaml.
- Produces sensitivity tables across reduction rates (10% to 50%).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.config_loader import load_config


def compute_baseline_components(
    df_prod: pd.DataFrame, df_quality: pd.DataFrame, df_downtime: pd.DataFrame
) -> dict[str, Any]:
    """Calculate authoritative baseline OEE components and top losses."""
    planned_min = float(df_prod["planned_time_min"].sum())
    run_min = float(df_prod["run_time_min"].sum())
    ideal_basis_min = float((df_prod["ideal_cycle_time_s"] * df_prod["total_count"] / 60.0).sum())
    total_count = int(df_prod["total_count"].sum())
    good_count = int(df_prod["good_count"].sum())
    scrap_count = int(df_prod["scrap_count"].sum())
    total_scrap_cost = float(df_quality["scrap_cost"].sum())

    a_base = run_min / planned_min if planned_min > 0 else 0.0
    p_base = ideal_basis_min / run_min if run_min > 0 else 0.0
    q_base = good_count / total_count if total_count > 0 else 0.0
    oee_base = a_base * p_base * q_base

    # Top 3 scrap causes
    scrap_by_cause = (
        df_quality.groupby("defect_cause", as_index=False)
        .agg(scrap_cost=("scrap_cost", "sum"), units_affected=("units_affected", "sum"))
        .sort_values(by="scrap_cost", ascending=False)
        .reset_index(drop=True)
    )
    top3_scrap_causes = scrap_by_cause.iloc[:3]["defect_cause"].tolist()
    top3_scrap_cost = float(scrap_by_cause.iloc[:3]["scrap_cost"].sum())
    top3_scrap_units = int(scrap_by_cause.iloc[:3]["units_affected"].sum())

    # Top 3 downtime reasons
    dt_by_reason = (
        df_downtime.groupby(["reason", "oee_bucket", "planned"], as_index=False)
        .agg(duration_min=("duration_min", "sum"), event_count=("duration_min", "count"))
        .sort_values(by="duration_min", ascending=False)
        .reset_index(drop=True)
    )
    top3_dt_reasons = dt_by_reason.iloc[:3]["reason"].tolist()
    top3_dt_min = float(dt_by_reason.iloc[:3]["duration_min"].sum())

    # Unplanned availability downtime in top 3
    avail_top_reasons = dt_by_reason[(dt_by_reason["reason"].isin(top3_dt_reasons)) & (dt_by_reason["oee_bucket"] == "Availability")]
    avail_top_min = float(avail_top_reasons["duration_min"].sum())

    # Performance minor stops in top 3
    perf_top_reasons = dt_by_reason[(dt_by_reason["reason"].isin(top3_dt_reasons)) & (dt_by_reason["oee_bucket"] == "Performance")]
    perf_top_min = float(perf_top_reasons["duration_min"].sum())

    return {
        "planned_time_min": planned_min,
        "run_time_min": run_min,
        "ideal_basis_min": ideal_basis_min,
        "total_count": total_count,
        "good_count": good_count,
        "scrap_count": scrap_count,
        "total_scrap_cost": total_scrap_cost,
        "availability": a_base,
        "performance": p_base,
        "quality": q_base,
        "oee": oee_base,
        "top3_scrap_causes": top3_scrap_causes,
        "top3_scrap_cost": top3_scrap_cost,
        "top3_scrap_units": top3_scrap_units,
        "top3_downtime_reasons": top3_dt_reasons,
        "top3_downtime_min": top3_dt_min,
        "top3_availability_downtime_min": avail_top_min,
        "top3_performance_downtime_min": perf_top_min,
    }


def model_loss_reduction_scenario(
    baseline: dict[str, Any],
    reduction_rate: float,
    mode: str,
    economic_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Recompute OEE, output units, and recoverable economic value for a scenario.

    Parameters
    ----------
    baseline : dict[str, Any]
        Baseline metrics from compute_baseline_components.
    reduction_rate : float
        Fraction of top losses eliminated (e.g. 0.30 for 30%).
    mode : str
        'scrap_only', 'downtime_only', or 'combined'.
    economic_cfg : dict[str, Any]
        Assumptions from config (unit_contribution_margin, annual_horizon_days, baseline_horizon_days).
    """
    annual_days = float(economic_cfg.get("annual_horizon_days", 365.0))
    base_days = float(economic_cfg.get("baseline_horizon_days", 180.0))
    annual_multiplier = annual_days / base_days
    unit_margin = float(economic_cfg.get("unit_contribution_margin", 22.50))

    # Baseline values
    planned_min = baseline["planned_time_min"]
    run_min = baseline["run_time_min"]
    ideal_min = baseline["ideal_basis_min"]
    total_count = baseline["total_count"]
    good_count = baseline["good_count"]
    a_base = baseline["availability"]
    p_base = baseline["performance"]
    q_base = baseline["quality"]
    oee_base = baseline["oee"]

    new_run_min = run_min
    new_ideal_min = ideal_min
    new_total_count = float(total_count)
    new_good_count = float(good_count)
    scrap_cost_avoided_180 = 0.0

    # 1. Scrap recovery
    if mode in ("scrap_only", "combined"):
        scrap_units_avoided = baseline["top3_scrap_units"] * reduction_rate
        scrap_cost_avoided_180 += baseline["top3_scrap_cost"] * reduction_rate
        # Avoided scrap units become good units
        new_good_count += scrap_units_avoided

    # 2. Downtime recovery
    if mode in ("downtime_only", "combined"):
        # Availability downtime reduced becomes extra run time
        avail_dt_reduced = baseline["top3_availability_downtime_min"] * reduction_rate
        new_run_min += avail_dt_reduced
        # Recovered run time produces parts at baseline performance & speed
        parts_per_run_min = total_count / run_min if run_min > 0 else 0.0
        extra_parts_from_avail = avail_dt_reduced * parts_per_run_min
        extra_good_from_avail = extra_parts_from_avail * q_base

        # Performance minor stops reduction directly increases ideal basis production
        perf_dt_reduced = baseline["top3_performance_downtime_min"] * reduction_rate
        new_ideal_min += (avail_dt_reduced * p_base) + perf_dt_reduced

        new_total_count += extra_parts_from_avail
        new_good_count += extra_good_from_avail

    # Recompute OEE components from additive components
    a_new = new_run_min / planned_min if planned_min > 0 else 0.0
    p_new = new_ideal_min / new_run_min if new_run_min > 0 else 0.0
    q_new = new_good_count / new_total_count if new_total_count > 0 else 0.0
    oee_new = a_new * p_new * q_new

    delta_a = a_new - a_base
    delta_p = p_new - p_base
    delta_q = q_new - q_base
    delta_oee = oee_new - oee_base

    # Incremental Output & Financials
    extra_good_units_180 = new_good_count - good_count
    annual_extra_good_units = extra_good_units_180 * annual_multiplier
    annual_scrap_cost_avoided = scrap_cost_avoided_180 * annual_multiplier
    annual_contribution_value = annual_extra_good_units * unit_margin
    total_annual_recoverable_value = annual_scrap_cost_avoided + annual_contribution_value

    return {
        "scenario_mode": mode,
        "reduction_rate": reduction_rate,
        "reduction_pct": f"{reduction_rate * 100:.0f}%",
        "availability_baseline": a_base,
        "availability_new": a_new,
        "availability_delta_pts": delta_a * 100.0,
        "performance_baseline": p_base,
        "performance_new": p_new,
        "performance_delta_pts": delta_p * 100.0,
        "quality_baseline": q_base,
        "quality_new": q_new,
        "quality_delta_pts": delta_q * 100.0,
        "oee_baseline": oee_base,
        "oee_new": oee_new,
        "oee_delta_pts": delta_oee * 100.0,
        "oee_relative_gain_pct": (delta_oee / oee_base) * 100.0 if oee_base > 0 else 0.0,
        "extra_good_units_180d": extra_good_units_180,
        "annual_extra_good_units": annual_extra_good_units,
        "annual_scrap_cost_avoided": annual_scrap_cost_avoided,
        "annual_contribution_margin_value": annual_contribution_value,
        "total_annual_recoverable_value": total_annual_recoverable_value,
    }


def generate_sensitivity_matrix(
    baseline: dict[str, Any],
    reduction_rates: Sequence[float],
    economic_cfg: dict[str, Any],
) -> pd.DataFrame:
    """Generate sensitivity table across reduction rates and scenario modes."""
    rows: list[dict[str, Any]] = []
    modes = ["scrap_only", "downtime_only", "combined"]

    for rate in reduction_rates:
        for mode in modes:
            res = model_loss_reduction_scenario(baseline, rate, mode, economic_cfg)
            rows.append(res)

    return pd.DataFrame(rows)


def run(config_path: str | Path | None = None) -> dict[str, Any]:
    """Execute OEE what-if analysis, generate sensitivity reports and summary."""
    config = load_config(config_path)
    root = Path(__file__).resolve().parents[1]

    # Resolve paths
    mes_cfg = config.get("mes", {}).get("outputs", {})
    prod_path = _resolve_path(root, mes_cfg.get("production_hourly", "data/processed/mes_production_hourly.csv"))
    dt_path = _resolve_path(root, mes_cfg.get("downtime_events", "data/processed/mes_downtime_events.csv"))
    q_path = _resolve_path(root, mes_cfg.get("quality_events", "data/processed/mes_quality_events.csv"))

    whatif_cfg = config.get("whatif", {})
    econ_cfg = whatif_cfg.get("economic_assumptions", {
        "unit_contribution_margin": 22.50,
        "annual_horizon_days": 365.0,
        "baseline_horizon_days": 180.0,
    })

    df_prod = pd.read_csv(prod_path)
    df_dt = pd.read_csv(dt_path)
    df_q = pd.read_csv(q_path)

    # Compute baseline
    baseline = compute_baseline_components(df_prod, df_q, df_dt)

    default_rate = float(whatif_cfg.get("default_reduction_rate", 0.30))
    rates = [float(r) for r in whatif_cfg.get("reduction_scenarios", [0.10, 0.20, 0.30, 0.40, 0.50])]

    # Headline default scenarios (30% reduction)
    headline_scrap = model_loss_reduction_scenario(baseline, default_rate, "scrap_only", econ_cfg)
    headline_dt = model_loss_reduction_scenario(baseline, default_rate, "downtime_only", econ_cfg)
    headline_comb = model_loss_reduction_scenario(baseline, default_rate, "combined", econ_cfg)

    # Sensitivity matrix
    sens_df = generate_sensitivity_matrix(baseline, rates, econ_cfg)

    # Output paths
    outputs_cfg = whatif_cfg.get("outputs", {})
    scenarios_csv_path = _resolve_path(root, outputs_cfg.get("scenarios", "reports/oee_whatif_scenarios.csv"))
    sens_csv_path = _resolve_path(root, outputs_cfg.get("sensitivity", "reports/oee_whatif_sensitivity.csv"))
    summary_json_path = _resolve_path(root, outputs_cfg.get("summary", "reports/oee_whatif_summary.json"))

    scenarios_csv_path.parent.mkdir(parents=True, exist_ok=True)
    sens_csv_path.parent.mkdir(parents=True, exist_ok=True)
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)

    # Save scenarios CSV (headline scenarios)
    scenarios_df = pd.DataFrame([headline_scrap, headline_dt, headline_comb])
    scenarios_df.to_csv(scenarios_csv_path, index=False)
    sens_df.to_csv(sens_csv_path, index=False)

    summary_doc: dict[str, Any] = {
        "baseline": baseline,
        "economic_assumptions": econ_cfg,
        "headline_scenarios_30pct": {
            "scrap_only": headline_scrap,
            "downtime_only": headline_dt,
            "combined": headline_comb,
        },
        "key_impact_summary": {
            "baseline_oee": baseline["oee"],
            "combined_30pct_oee": headline_comb["oee_new"],
            "oee_uplift_pts": headline_comb["oee_delta_pts"],
            "annual_scrap_cost_avoided": headline_comb["annual_scrap_cost_avoided"],
            "annual_extra_good_units": headline_comb["annual_extra_good_units"],
            "total_annual_recoverable_value": headline_comb["total_annual_recoverable_value"],
        },
        "outputs": {
            "scenarios_csv": str(scenarios_csv_path),
            "sensitivity_csv": str(sens_csv_path),
            "summary_json": str(summary_json_path),
        },
    }

    with summary_json_path.open("w", encoding="utf-8") as f:
        json.dump(summary_doc, f, indent=2)

    print("OEE What-If analysis complete:")
    print(f"  - Baseline OEE: {baseline['oee']:.2%}")
    print(f"  - 30% Combined Reduction OEE: {headline_comb['oee_new']:.2%} (+{headline_comb['oee_delta_pts']:.2f} pts)")
    print(f"  - Annual extra good units: {headline_comb['annual_extra_good_units']:,.0f}")
    print(f"  - Annual recoverable value: ${headline_comb['total_annual_recoverable_value']:,.2f}")
    print(f"  - Summary report: {summary_json_path}")

    return summary_doc


def _resolve_path(root: Path, path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else root / p


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for OEE what-if analysis."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    try:
        run(args.config)
        return 0
    except Exception as exc:
        print(f"Error during OEE what-if analysis: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
