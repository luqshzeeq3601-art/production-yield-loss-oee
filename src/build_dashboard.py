"""Build the interactive OEE & early-warning dashboard from committed report artifacts.

Reads validated reports (never recomputes authoritative metrics) plus the
simulated MES hourly file for the weekly OEE trend, embeds them as JSON into
``src/dashboard_template.html`` and writes a single self-contained page to
``docs/dashboard.html`` (no external scripts, opens offline).

Usage:
    py -3.11 -m src.build_dashboard
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

PLACEHOLDER = "/*__DASHBOARD_DATA__*/null"
LINES = ["L1", "L2", "L3", "L4"]
SHIFTS = ["A", "B", "C"]
WHATIF_MODES = ["scrap_only", "downtime_only", "combined"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _r(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _apqo(block: dict[str, Any]) -> dict[str, float]:
    return {k: _r(block[k]) for k in ("availability", "performance", "quality", "oee")}


def plant_summary(reports: Path) -> dict[str, Any]:
    """Plant KPIs, loss decomposition and line/shift breakdowns (Power BI reconciled)."""
    dax = _json(reports / "powerbi_reconciliation_summary.json")["dax_evaluation"]
    plant = dax["plant_overview"]
    loss = dax["loss_decomposition"]
    return {
        "plant": {
            **_apqo(plant),
            "oee_target": _r(plant["oee_target"]),
            "total_units": int(plant["total_units"]),
            "good_units": int(plant["good_units"]),
            "scrap_units": int(plant["scrap_units"]),
            "planned_hours": _r(plant["planned_production_time_h"], 1),
        },
        "loss_hours": {
            "availability": _r(loss["availability_loss_hours"], 1),
            "performance": _r(loss["performance_loss_hours"], 1),
            "quality": _r(loss["quality_equivalent_loss_hours"], 1),
        },
        "scrap_cost": _r(loss["total_scrap_cost"], 0),
        "unplanned_downtime_hours": _r(loss["unplanned_downtime_hours"], 1),
        "lines": {k: _apqo(dax["line_breakdown"][k]) for k in LINES},
        "shifts": {k: _apqo(dax["shift_breakdown"][k]) for k in SHIFTS},
    }


def weekly_oee(production_csv: Path) -> list[dict[str, Any]]:
    """Weekly OEE per line, weighted from hourly components (never averaged %)."""
    df = pd.read_csv(production_csv, parse_dates=["date"])
    df["ideal_min"] = df["ideal_cycle_time_s"] * df["total_count"] / 60.0
    df["week"] = df["date"].dt.to_period("W-SUN").dt.start_time
    cols = [
        "planned_time_min",
        "run_time_min",
        "ideal_min",
        "total_count",
        "good_count",
    ]

    def _oee(g: pd.DataFrame) -> float:
        s = g[cols].sum()
        return float(
            s["ideal_min"] / s["planned_time_min"] * s["good_count"] / s["total_count"]
        )

    rows = []
    for week, wk in df.groupby("week", sort=True):
        row: dict[str, Any] = {
            "week": week.strftime("%Y-%m-%d"),
            "days": int(wk["date"].nunique()),
        }
        for line in LINES:
            row[line] = _r(_oee(wk[wk["line"] == line]))
        row["plant"] = _r(_oee(wk))
        rows.append(row)
    return rows


def paretos(reports: Path) -> dict[str, list[dict[str, Any]]]:
    dt = pd.read_csv(reports / "pareto_downtime.csv")
    sc = pd.read_csv(reports / "pareto_scrap.csv")
    return {
        "downtime": [
            {
                "label": r.reason.replace("_", " "),
                "value": _r(r.duration_hours, 1),
                "share": _r(r.downtime_share),
                "cum": _r(r.cumulative_downtime_share),
                "events": int(r.event_count),
                "bucket": r.oee_bucket,
                "planned": bool(r.is_planned),
            }
            for r in dt.itertuples()
        ],
        "scrap": [
            {
                "label": r.defect_cause,
                "value": _r(r.scrap_cost, 0),
                "share": _r(r.scrap_cost_share),
                "cum": _r(r.cumulative_scrap_cost_share),
                "units": int(r.units_affected),
            }
            for r in sc.itertuples()
        ],
    }


def spc(reports: Path) -> dict[str, Any]:
    methods = pd.read_csv(reports / "spc_backtest_methods.csv")
    pchart = pd.read_csv(reports / "p_chart_daily.csv")
    t2 = pd.read_csv(reports / "hotelling_t2_series.csv").dropna(subset=["t2"])
    return {
        "methods": [
            {
                "method": r.method,
                "precision": _r(r.precision),
                "recall": _r(r.recall),
                "false_alarms_per_100": _r(r.false_alarms_per_100_lots, 2),
                "median_hours_saved": _r(r.median_hours_saved, 2),
                "tp": int(r.TP),
                "fp": int(r.FP),
                "fn": int(r.FN),
            }
            for r in methods.itertuples()
        ],
        "pchart": [
            {
                "date": r.date,
                "rate": _r(r.defect_rate),
                "ucl": _r(r.ucl),
                "pbar": _r(r.pbar),
                "lots": int(r.total_lots),
                "fails": int(r.fail_lots),
                "violation": bool(r.violation),
            }
            for r in pchart.itertuples()
        ],
        "t2": [
            {
                "ts": str(r.timestamp)[:16],
                "t2": _r(r.t2, 2),
                "phase": r.phase,
                "violation": bool(r.violation),
            }
            for r in t2.itertuples()
        ],
        "t2_ucl": _r(t2["ucl"].iloc[0], 2),
    }


def whatif(reports: Path) -> dict[str, Any]:
    sens = pd.read_csv(reports / "oee_whatif_sensitivity.csv")
    base = float(sens["oee_baseline"].iloc[0])
    return {
        "baseline": _r(base),
        "series": {
            mode: [{"reduction": 0.0, "oee": _r(base)}]
            + [
                {"reduction": _r(r.reduction_rate, 2), "oee": _r(r.oee_new)}
                for r in sens[sens["scenario_mode"] == mode]
                .sort_values("reduction_rate")
                .itertuples()
            ]
            for mode in WHATIF_MODES
        },
    }


def impact(reports: Path) -> dict[str, Any]:
    m = pd.read_csv(reports / "impact_metrics.csv").set_index("metric_id")["value"]
    baseline = _json(reports / "manual_reporting_baseline.json")
    return {
        "median_hours_saved": float(m["SPC-007"]),
        "top3_downtime_share": float(m["PAR-003"]) / 100,
        "top3_scrap_share": float(m["PAR-001"]) / 100,
        "manual_minutes": float(m["RA-002"]),
        "automated_minutes": float(m["RA-003"]),
        "reporting_reduction_pct": float(m["RA-007"]),
        "manual_phases": baseline["step_breakdown_by_phase"],
        "dq_checks": int(float(m["DQ-001"])),
    }


def build_payload(repo: Path) -> dict[str, Any]:
    reports = repo / "reports"
    return {
        "summary": plant_summary(reports),
        "weekly": weekly_oee(repo / "data" / "processed" / "mes_production_hourly.csv"),
        "pareto": paretos(reports),
        "spc": spc(reports),
        "whatif": whatif(reports),
        "impact": impact(reports),
    }


def render(payload: dict[str, Any], template: str) -> str:
    if PLACEHOLDER not in template:
        raise ValueError("dashboard template is missing the data placeholder")
    # "</" is escaped so embedded strings can never close the <script> block.
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    return template.replace(PLACEHOLDER, data)


def run(out: Path | None = None) -> dict[str, Any]:
    repo = _repo_root()
    payload = build_payload(repo)
    template = (repo / "src" / "dashboard_template.html").read_text(encoding="utf-8")
    out = out or repo / "docs" / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(payload, template), encoding="utf-8")
    print(f"Dashboard written to {out}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="output HTML path")
    args = parser.parse_args(argv)
    try:
        run(args.out)
    except (OSError, KeyError, ValueError) as exc:
        print(f"Dashboard build failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
