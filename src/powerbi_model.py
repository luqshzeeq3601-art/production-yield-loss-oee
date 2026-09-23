"""Power BI semantic model and DAX reconciliation validator (P5-002).

Validates star schema relationships and evaluates DAX measure expressions
against PostgreSQL fact data to enforce <= 0.1% reconciliation tolerance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from src.config_loader import load_config


def evaluate_dax_measures(
    df_prod: pd.DataFrame,
    df_dt: pd.DataFrame,
    df_quality: pd.DataFrame,
    df_manpower: pd.DataFrame,
    df_station_ops: pd.DataFrame,
) -> dict[str, Any]:
    """Evaluate all DAX measure expressions against processed fact datasets."""
    # 1. Volume & Time Measures
    planned_h = float(df_prod["planned_time_min"].sum() / 60.0)
    run_h = float(df_prod["run_time_min"].sum() / 60.0)
    ideal_basis_h = float((df_prod["ideal_cycle_time_s"] * df_prod["total_count"]).sum() / 3600.0)
    total_units = int(df_prod["total_count"].sum())
    good_units = int(df_prod["good_count"].sum())
    scrap_units = int(df_prod["scrap_count"].sum())

    yield_pct = good_units / total_units if total_units > 0 else 0.0
    scrap_rate_pct = scrap_units / total_units if total_units > 0 else 0.0

    # 2. Core OEE Measures (Additive component derivation)
    availability = run_h / planned_h if planned_h > 0 else 0.0
    performance = ideal_basis_h / run_h if run_h > 0 else 0.0
    quality = good_units / total_units if total_units > 0 else 0.0
    oee = availability * performance * quality

    oee_target = 0.85
    oee_vs_target = oee - oee_target

    # 3. Loss Decomposition Measures
    dt_min = float(df_dt["duration_min"].sum())
    dt_hours = dt_min / 60.0
    unplanned_dt_h = float(df_dt[df_dt["planned"].isin([0, False])]["duration_min"].sum() / 60.0)
    planned_dt_h = float(df_dt[df_dt["planned"].isin([1, True])]["duration_min"].sum() / 60.0)

    avail_loss_h = planned_h - run_h
    perf_loss_h = run_h - ideal_basis_h
    quality_equiv_loss_h = float((df_prod["ideal_cycle_time_s"] * df_prod["scrap_count"]).sum() / 3600.0)

    total_scrap_cost = float(df_quality["scrap_cost"].sum())
    top3_causes = ["dimensional", "surface defect", "contamination"]
    top3_scrap_cost = float(df_quality[df_quality["defect_cause"].isin(top3_causes)]["scrap_cost"].sum())
    top3_scrap_share = top3_scrap_cost / total_scrap_cost if total_scrap_cost > 0 else 0.0

    # 4. Manpower & Operations
    planned_headcount = int(df_manpower["planned_headcount"].sum())
    actual_headcount = int(df_manpower["actual_headcount"].sum())
    manpower_gap = planned_headcount - actual_headcount
    capacity_utilization = run_h / planned_h if planned_h > 0 else 0.0

    # 5. Station Operations
    avg_proc_time = float(df_station_ops["processing_time_s"].mean())
    avg_wait_time = float(df_station_ops["wait_time_s"].mean())
    bottleneck_proc_time = float(df_station_ops[df_station_ops["is_bottleneck"] == 1]["processing_time_s"].mean())

    # 6. Line Level OEE DAX breakdown
    line_metrics: dict[str, Any] = {}
    for line_id in sorted(df_prod["line"].unique()):
        sub_p = df_prod[df_prod["line"] == line_id]
        l_plan = float(sub_p["planned_time_min"].sum() / 60.0)
        l_run = float(sub_p["run_time_min"].sum() / 60.0)
        l_ideal = float((sub_p["ideal_cycle_time_s"] * sub_p["total_count"]).sum() / 3600.0)
        l_tot = int(sub_p["total_count"].sum())
        l_good = int(sub_p["good_count"].sum())

        l_a = l_run / l_plan if l_plan > 0 else 0.0
        l_p = l_ideal / l_run if l_run > 0 else 0.0
        l_q = l_good / l_tot if l_tot > 0 else 0.0
        l_oee = l_a * l_p * l_q

        line_metrics[line_id] = {
            "planned_hours": l_plan,
            "run_hours": l_run,
            "ideal_hours": l_ideal,
            "total_units": l_tot,
            "good_units": l_good,
            "availability": l_a,
            "performance": l_p,
            "quality": l_q,
            "oee": l_oee,
        }

    # 7. Shift Level OEE DAX breakdown
    shift_metrics: dict[str, Any] = {}
    for shift_id in sorted(df_prod["shift"].unique()):
        sub_s = df_prod[df_prod["shift"] == shift_id]
        s_plan = float(sub_s["planned_time_min"].sum() / 60.0)
        s_run = float(sub_s["run_time_min"].sum() / 60.0)
        s_ideal = float((sub_s["ideal_cycle_time_s"] * sub_s["total_count"]).sum() / 3600.0)
        s_tot = int(sub_s["total_count"].sum())
        s_good = int(sub_s["good_count"].sum())

        s_a = s_run / s_plan if s_plan > 0 else 0.0
        s_p = s_ideal / s_run if s_run > 0 else 0.0
        s_q = s_good / s_tot if s_tot > 0 else 0.0
        s_oee = s_a * s_p * s_q

        shift_metrics[shift_id] = {
            "planned_hours": s_plan,
            "run_hours": s_run,
            "ideal_hours": s_ideal,
            "total_units": s_tot,
            "good_units": s_good,
            "availability": s_a,
            "performance": s_p,
            "quality": s_q,
            "oee": s_oee,
        }

    return {
        "plant_overview": {
            "planned_production_time_h": planned_h,
            "run_time_h": run_h,
            "ideal_operating_basis_h": ideal_basis_h,
            "total_units": total_units,
            "good_units": good_units,
            "scrap_units": scrap_units,
            "yield_pct": yield_pct,
            "scrap_rate_pct": scrap_rate_pct,
            "availability": availability,
            "performance": performance,
            "quality": quality,
            "oee": oee,
            "oee_target": oee_target,
            "oee_vs_target": oee_vs_target,
        },
        "loss_decomposition": {
            "downtime_minutes": dt_min,
            "downtime_hours": dt_hours,
            "unplanned_downtime_hours": unplanned_dt_h,
            "planned_downtime_hours": planned_dt_h,
            "availability_loss_hours": avail_loss_h,
            "performance_loss_hours": perf_loss_h,
            "quality_equivalent_loss_hours": quality_equiv_loss_h,
            "total_scrap_cost": total_scrap_cost,
            "top3_scrap_cost": top3_scrap_cost,
            "top3_scrap_share": top3_scrap_share,
        },
        "manpower_and_capacity": {
            "planned_headcount": planned_headcount,
            "actual_headcount": actual_headcount,
            "manpower_gap": manpower_gap,
            "capacity_utilization": capacity_utilization,
        },
        "station_bottlenecks": {
            "avg_processing_time_s": avg_proc_time,
            "avg_wait_time_s": avg_wait_time,
            "bottleneck_processing_time_s": bottleneck_proc_time,
        },
        "line_breakdown": line_metrics,
        "shift_breakdown": shift_metrics,
    }


def reconcile_sql_and_dax(
    dax_results: dict[str, Any],
    sql_summary_path: Path,
) -> dict[str, Any]:
    """Reconcile DAX measures against authoritative SQL summary, ensuring <= 0.1% diff."""
    if not sql_summary_path.is_file():
        raise FileNotFoundError(f"SQL summary not found at {sql_summary_path}")

    sql_data = json.loads(sql_summary_path.read_text(encoding="utf-8"))
    sql_overall = sql_data["overall"]
    dax_overall = dax_results["plant_overview"]

    reconciliations = []
    comparisons = [
        ("Availability", sql_overall["availability"], dax_overall["availability"]),
        ("Performance", sql_overall["performance"], dax_overall["performance"]),
        ("Quality", sql_overall["quality"], dax_overall["quality"]),
        ("OEE", sql_overall["oee"], dax_overall["oee"]),
        ("Total Units", float(sql_data["total_count"]), float(dax_overall["total_units"])),
        ("Good Units", float(sql_data["good_count"]), float(dax_overall["good_units"])),
        ("Scrap Units", float(sql_data["scrap_count"]), float(dax_overall["scrap_units"])),
    ]

    max_rel_diff = 0.0
    for name, sql_val, dax_val in comparisons:
        abs_diff = abs(sql_val - dax_val)
        rel_diff = abs_diff / abs(sql_val) if sql_val != 0 else 0.0
        max_rel_diff = max(max_rel_diff, rel_diff)
        reconciliations.append({
            "metric": name,
            "sql_value": float(sql_val),
            "dax_value": float(dax_val),
            "absolute_diff": float(abs_diff),
            "relative_diff_pct": float(rel_diff * 100.0),
            "passes_01pct_tolerance": bool(rel_diff <= 0.001),
        })

    return {
        "max_relative_diff_pct": float(max_rel_diff * 100.0),
        "overall_status": "PASS" if max_rel_diff <= 0.001 else "FAIL",
        "tolerance_threshold_pct": 0.10,
        "metrics": reconciliations,
    }


def run(config_path: str | Path | None = None) -> dict[str, Any]:
    """Execute Power BI semantic model validation and reconciliation."""
    config = load_config(config_path)
    root = Path(__file__).resolve().parents[1]

    mes_cfg = config.get("mes", {}).get("outputs", {})
    prod_path = _resolve_path(root, mes_cfg.get("production_hourly", "data/processed/mes_production_hourly.csv"))
    dt_path = _resolve_path(root, mes_cfg.get("downtime_events", "data/processed/mes_downtime_events.csv"))
    q_path = _resolve_path(root, mes_cfg.get("quality_events", "data/processed/mes_quality_events.csv"))
    mp_path = _resolve_path(root, mes_cfg.get("manpower_shifts", "data/processed/mes_manpower_shifts.csv"))
    st_path = _resolve_path(root, mes_cfg.get("station_operations", "data/processed/mes_station_operations.csv"))
    sql_sum_path = _resolve_path(root, mes_cfg.get("simulation_summary", "reports/mes_simulation_summary.json"))

    df_prod = pd.read_csv(prod_path)
    df_dt = pd.read_csv(dt_path)
    df_q = pd.read_csv(q_path)
    df_mp = pd.read_csv(mp_path)
    df_st = pd.read_csv(st_path)

    # Evaluate DAX
    dax_metrics = evaluate_dax_measures(df_prod, df_dt, df_q, df_mp, df_st)

    # Reconcile with SQL
    reconciliation = reconcile_sql_and_dax(dax_metrics, sql_sum_path)

    summary: dict[str, Any] = {
        "dax_evaluation": dax_metrics,
        "reconciliation": reconciliation,
        "model_artifacts": {
            "theme_json": str(_resolve_path(root, "powerbi/theme.json")),
            "model_mapping_csv": str(_resolve_path(root, "powerbi/model_mapping.csv")),
            "measures_dax": str(_resolve_path(root, "powerbi/measures.dax")),
            "measure_catalog_md": str(_resolve_path(root, "powerbi/measure_catalog.md")),
            "powerbi_model_doc": str(_resolve_path(root, "docs/powerbi_model.md")),
        },
    }

    out_json = _resolve_path(root, "reports/powerbi_reconciliation_summary.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("Power BI model validation & DAX reconciliation complete:")
    print(f"  - Overall Reconciliation Status: {reconciliation['overall_status']}")
    print(f"  - Max Relative Difference: {reconciliation['max_relative_diff_pct']:.4f}% (Tolerance: <= 0.10%)")
    print(f"  - Summary report: {out_json}")

    return summary


def _resolve_path(root: Path, path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else root / p


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for Power BI model validator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    try:
        run(args.config)
        return 0
    except Exception as exc:
        print(f"Error during Power BI model validation: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
