"""Scrap and downtime Pareto analysis for OEE Root Cause Analysis (P4-002).

Provides deterministic Pareto ranking, cumulative share computation,
top-N concentration metrics, and line-level breakdowns for MES quality
and downtime data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from src.config_loader import load_config


def compute_scrap_pareto(
    df: pd.DataFrame, top_n: int = 3
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compute ranked scrap-cost Pareto table and concentration summary.

    Parameters
    ----------
    df : pd.DataFrame
        Quality events data containing 'defect_cause', 'scrap_cost', and 'units_affected'.
    top_n : int, default 3
        Number of top causes for concentration metric calculation.

    Returns
    -------
    tuple[pd.DataFrame, dict[str, Any]]
        Pareto dataframe sorted descending by scrap_cost, and summary dict.
    """
    if df.empty:
        cols = [
            "rank",
            "defect_cause",
            "scrap_cost",
            "units_affected",
            "event_count",
            "scrap_cost_share",
            "cumulative_scrap_cost",
            "cumulative_scrap_cost_share",
            "units_share",
            "cumulative_units_share",
        ]
        return pd.DataFrame(columns=cols), {
            "total_scrap_cost": 0.0,
            "total_units_affected": 0,
            "total_records": 0,
            "cause_count": 0,
            "top_n": top_n,
            "top_n_causes": [],
            "top_n_scrap_cost": 0.0,
            "top_n_scrap_cost_share": 0.0,
            "top_n_units_affected": 0,
            "top_n_units_share": 0.0,
        }

    grouped = (
        df.groupby("defect_cause", as_index=False)
        .agg(
            scrap_cost=("scrap_cost", "sum"),
            units_affected=("units_affected", "sum"),
            event_count=("scrap_cost", "count"),
        )
        .sort_values(by=["scrap_cost", "units_affected", "defect_cause"], ascending=[False, False, True])
        .reset_index(drop=True)
    )

    total_cost = float(grouped["scrap_cost"].sum())
    total_units = int(grouped["units_affected"].sum())
    total_records = int(grouped["event_count"].sum())

    grouped["rank"] = grouped.index + 1
    grouped["scrap_cost_share"] = grouped["scrap_cost"] / total_cost if total_cost > 0 else 0.0
    grouped["cumulative_scrap_cost"] = grouped["scrap_cost"].cumsum()
    grouped["cumulative_scrap_cost_share"] = (
        grouped["cumulative_scrap_cost"] / total_cost if total_cost > 0 else 0.0
    )
    grouped["units_share"] = grouped["units_affected"] / total_units if total_units > 0 else 0.0
    grouped["cumulative_units_affected"] = grouped["units_affected"].cumsum()
    grouped["cumulative_units_share"] = (
        grouped["cumulative_units_affected"] / total_units if total_units > 0 else 0.0
    )

    # Column ordering
    ordered_cols = [
        "rank",
        "defect_cause",
        "scrap_cost",
        "units_affected",
        "event_count",
        "scrap_cost_share",
        "cumulative_scrap_cost",
        "cumulative_scrap_cost_share",
        "units_share",
        "cumulative_units_share",
    ]
    pareto_df = grouped[ordered_cols].copy()

    top_slice = pareto_df.iloc[:top_n]
    top_causes = top_slice["defect_cause"].tolist()
    top_cost = float(top_slice["scrap_cost"].sum())
    top_cost_share = float(top_slice["scrap_cost_share"].sum())
    top_units = int(top_slice["units_affected"].sum())
    top_units_share = float(top_slice["units_share"].sum())

    summary = {
        "total_scrap_cost": total_cost,
        "total_units_affected": total_units,
        "total_records": total_records,
        "cause_count": len(pareto_df),
        "top_n": top_n,
        "top_n_causes": top_causes,
        "top_n_scrap_cost": top_cost,
        "top_n_scrap_cost_share": top_cost_share,
        "top_n_units_affected": top_units,
        "top_n_units_share": top_units_share,
    }

    return pareto_df, summary


def compute_downtime_pareto(
    df: pd.DataFrame, top_n: int = 3, exclude_planned: bool = False
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compute ranked downtime-duration Pareto table and concentration summary.

    Parameters
    ----------
    df : pd.DataFrame
        Downtime events data containing 'reason', 'duration_min', 'oee_bucket', and optionally 'planned'.
    top_n : int, default 3
        Number of top reasons for concentration metric calculation.
    exclude_planned : bool, default False
        Whether to filter out planned downtime events before computing Pareto.

    Returns
    -------
    tuple[pd.DataFrame, dict[str, Any]]
        Pareto dataframe sorted descending by duration_min, and summary dict.
    """
    events = df.copy()
    if exclude_planned and "planned" in events.columns:
        events = events[events["planned"].isin([0, False, "0", "False"])].copy()

    if events.empty:
        cols = [
            "rank",
            "reason",
            "oee_bucket",
            "is_planned",
            "duration_min",
            "duration_hours",
            "event_count",
            "downtime_share",
            "cumulative_duration_min",
            "cumulative_duration_hours",
            "cumulative_downtime_share",
            "event_share",
            "cumulative_event_share",
        ]
        return pd.DataFrame(columns=cols), {
            "total_duration_min": 0.0,
            "total_duration_hours": 0.0,
            "total_event_count": 0,
            "reason_count": 0,
            "exclude_planned": exclude_planned,
            "top_n": top_n,
            "top_n_reasons": [],
            "top_n_duration_min": 0.0,
            "top_n_duration_hours": 0.0,
            "top_n_duration_share": 0.0,
            "top_n_event_count": 0,
            "top_n_event_share": 0.0,
        }

    agg_dict = {
        "duration_min": ("duration_min", "sum"),
        "event_count": ("duration_min", "count"),
    }
    if "oee_bucket" in events.columns:
        agg_dict["oee_bucket"] = ("oee_bucket", "first")
    if "planned" in events.columns:
        agg_dict["is_planned"] = ("planned", lambda s: bool(s.iloc[0]) if len(s) else False)

    grouped = (
        events.groupby("reason", as_index=False)
        .agg(**agg_dict)
        .sort_values(by=["duration_min", "event_count", "reason"], ascending=[False, False, True])
        .reset_index(drop=True)
    )

    total_min = float(grouped["duration_min"].sum())
    total_hours = total_min / 60.0
    total_events = int(grouped["event_count"].sum())

    grouped["rank"] = grouped.index + 1
    grouped["duration_hours"] = grouped["duration_min"] / 60.0
    grouped["downtime_share"] = grouped["duration_min"] / total_min if total_min > 0 else 0.0
    grouped["cumulative_duration_min"] = grouped["duration_min"].cumsum()
    grouped["cumulative_duration_hours"] = grouped["cumulative_duration_min"] / 60.0
    grouped["cumulative_downtime_share"] = (
        grouped["cumulative_duration_min"] / total_min if total_min > 0 else 0.0
    )
    grouped["event_share"] = grouped["event_count"] / total_events if total_events > 0 else 0.0
    grouped["cumulative_event_count"] = grouped["event_count"].cumsum()
    grouped["cumulative_event_share"] = (
        grouped["cumulative_event_count"] / total_events if total_events > 0 else 0.0
    )

    cols = ["rank", "reason"]
    if "oee_bucket" in grouped.columns:
        cols.append("oee_bucket")
    if "is_planned" in grouped.columns:
        cols.append("is_planned")
    cols.extend([
        "duration_min",
        "duration_hours",
        "event_count",
        "downtime_share",
        "cumulative_duration_min",
        "cumulative_duration_hours",
        "cumulative_downtime_share",
        "event_share",
        "cumulative_event_share",
    ])
    pareto_df = grouped[cols].copy()

    top_slice = pareto_df.iloc[:top_n]
    top_reasons = top_slice["reason"].tolist()
    top_duration_min = float(top_slice["duration_min"].sum())
    top_duration_hours = top_duration_min / 60.0
    top_duration_share = float(top_slice["downtime_share"].sum())
    top_events = int(top_slice["event_count"].sum())
    top_event_share = float(top_slice["event_share"].sum())

    summary = {
        "total_duration_min": total_min,
        "total_duration_hours": total_hours,
        "total_event_count": total_events,
        "reason_count": len(pareto_df),
        "exclude_planned": exclude_planned,
        "top_n": top_n,
        "top_n_reasons": top_reasons,
        "top_n_duration_min": top_duration_min,
        "top_n_duration_hours": top_duration_hours,
        "top_n_duration_share": top_duration_share,
        "top_n_event_count": top_events,
        "top_n_event_share": top_event_share,
    }

    return pareto_df, summary


def compute_line_level_pareto(
    df_quality: pd.DataFrame, df_downtime: pd.DataFrame, top_n: int = 3
) -> dict[str, Any]:
    """Compute scrap and downtime Pareto breakdowns for each production line."""
    lines = sorted(set(df_quality["line"].unique()).union(set(df_downtime["line"].unique())))
    line_results: dict[str, Any] = {}

    for line_id in lines:
        q_line = df_quality[df_quality["line"] == line_id]
        d_line = df_downtime[df_downtime["line"] == line_id]

        _, scrap_sum = compute_scrap_pareto(q_line, top_n=top_n)
        _, dt_sum = compute_downtime_pareto(d_line, top_n=top_n, exclude_planned=False)
        _, dt_unplanned_sum = compute_downtime_pareto(d_line, top_n=top_n, exclude_planned=True)

        line_results[line_id] = {
            "scrap": scrap_sum,
            "downtime_all": dt_sum,
            "downtime_unplanned": dt_unplanned_sum,
        }

    return line_results


def run(config_path: str | Path | None = None) -> dict[str, Any]:
    """Run full Pareto analysis from processed MES data and save report artifacts."""
    config = load_config(config_path)
    root = Path(__file__).resolve().parents[1]

    # Resolve input paths
    mes_outputs = config.get("mes", {}).get("outputs", {})
    quality_path = _resolve_path(root, mes_outputs.get("quality_events", "data/processed/mes_quality_events.csv"))
    downtime_path = _resolve_path(root, mes_outputs.get("downtime_events", "data/processed/mes_downtime_events.csv"))

    if not quality_path.is_file():
        raise FileNotFoundError(f"MES quality events file not found at {quality_path}")
    if not downtime_path.is_file():
        raise FileNotFoundError(f"MES downtime events file not found at {downtime_path}")

    df_quality = pd.read_csv(quality_path)
    df_downtime = pd.read_csv(downtime_path)

    top_n = int(config.get("pareto", {}).get("top_n", 3))

    # Compute overall Paretos
    scrap_pareto_df, scrap_summary = compute_scrap_pareto(df_quality, top_n=top_n)
    downtime_all_df, downtime_all_summary = compute_downtime_pareto(df_downtime, top_n=top_n, exclude_planned=False)
    downtime_unplanned_df, downtime_unplanned_summary = compute_downtime_pareto(
        df_downtime, top_n=top_n, exclude_planned=True
    )

    # Compute line-level breakdowns
    line_level = compute_line_level_pareto(df_quality, df_downtime, top_n=top_n)

    # Resolve output paths
    pareto_cfg = config.get("pareto", {}).get("outputs", {})
    scrap_out_path = _resolve_path(root, pareto_cfg.get("scrap_pareto", "reports/pareto_scrap.csv"))
    downtime_out_path = _resolve_path(root, pareto_cfg.get("downtime_pareto", "reports/pareto_downtime.csv"))
    summary_out_path = _resolve_path(root, pareto_cfg.get("summary", "reports/pareto_summary.json"))

    scrap_out_path.parent.mkdir(parents=True, exist_ok=True)
    downtime_out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_out_path.parent.mkdir(parents=True, exist_ok=True)

    scrap_pareto_df.to_csv(scrap_out_path, index=False)
    downtime_all_df.to_csv(downtime_out_path, index=False)

    full_summary: dict[str, Any] = {
        "scrap": {
            "overall": scrap_summary,
            "records": scrap_pareto_df.to_dict(orient="records"),
        },
        "downtime_all_events": {
            "overall": downtime_all_summary,
            "records": downtime_all_df.to_dict(orient="records"),
        },
        "downtime_unplanned": {
            "overall": downtime_unplanned_summary,
            "records": downtime_unplanned_df.to_dict(orient="records"),
        },
        "line_breakdown": line_level,
        "key_findings": {
            "top_3_scrap_causes": scrap_summary["top_n_causes"],
            "top_3_scrap_cost_share": scrap_summary["top_n_scrap_cost_share"],
            "top_3_downtime_reasons_unplanned": downtime_unplanned_summary["top_n_reasons"],
            "top_3_downtime_share_unplanned": downtime_unplanned_summary["top_n_duration_share"],
        },
        "outputs": {
            "scrap_pareto": str(scrap_out_path),
            "downtime_pareto": str(downtime_out_path),
            "summary": str(summary_out_path),
        },
    }

    with summary_out_path.open("w", encoding="utf-8") as f:
        json.dump(full_summary, f, indent=2)

    print(f"Pareto analysis complete:")
    print(f"  - Scrap Pareto: {scrap_out_path} (Top 3 share: {scrap_summary['top_n_scrap_cost_share']:.2%})")
    print(f"  - Downtime Pareto: {downtime_out_path} (Top 3 unplanned share: {downtime_unplanned_summary['top_n_duration_share']:.2%})")
    print(f"  - Summary report: {summary_out_path}")

    return full_summary


def _resolve_path(root: Path, path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else root / p


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for Pareto analysis."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    try:
        run(args.config)
        return 0
    except Exception as exc:
        print(f"Error during Pareto analysis: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
