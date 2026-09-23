"""Generate static portfolio figures from committed report artifacts — polish only.

Reads existing validated reports (never recomputes authoritative metrics) and
writes GitHub-ready PNGs to docs/assets/. All plotted values come straight
from the source artifacts; each builder returns its data for provenance tests.

Usage:
    py -3.11 -m src.generate_portfolio_figures
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

NAVY = "#1B365D"
STEEL = "#2C5282"
TEAL = "#319795"
RED = "#E53E3E"
GOLD = "#D69E2E"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _style() -> None:
    plt.rcParams.update({
        "figure.dpi": 150,
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.3,
    })


def oee_by_line(reports: Path) -> dict[str, float]:
    """Plant OEE by line from the Power BI reconciliation artifact."""
    pb = json.loads((reports / "powerbi_reconciliation_summary.json").read_text(encoding="utf-8"))
    return {line: round(float(pb["dax_evaluation"]["line_breakdown"][line]["oee"]) * 100, 2)
            for line in ["L1", "L2", "L3", "L4"]}


def oee_by_shift(reports: Path) -> dict[str, float]:
    """Plant OEE by shift from the Power BI reconciliation artifact."""
    pb = json.loads((reports / "powerbi_reconciliation_summary.json").read_text(encoding="utf-8"))
    return {shift: round(float(pb["dax_evaluation"]["shift_breakdown"][shift]["oee"]) * 100, 2)
            for shift in ["A", "B", "C"]}


def _bar_with_target(path: Path, title: str, data: dict[str, float], target: float) -> None:
    fig, ax = plt.subplots(figsize=(6, 3.5))
    labels = list(data.keys())
    values = list(data.values())
    bars = ax.bar(labels, values, color=[NAVY, STEEL, TEAL, GOLD][: len(labels)])
    ax.axhline(target, color=RED, linestyle="--", linewidth=1, label=f"Target {target:.0f}%")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.4, f"{value:.2f}%",
                ha="center", fontsize=9)
    ax.set_ylim(0, 100)
    ax.set_ylabel("OEE (%)")
    ax.set_title(title)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def _pareto(path: Path, title: str, labels: list[str], values: list[float],
            shares: list[float], cum_shares: list[float], value_label: str) -> None:
    fig, ax1 = plt.subplots(figsize=(7, 3.8))
    bars = ax1.bar(labels, values, color=NAVY)
    ax1.set_ylabel(value_label)
    ax1.tick_params(axis="x", rotation=18)
    ax2 = ax1.twinx()
    ax2.plot(labels, [s * 100 for s in cum_shares], color=RED, marker="o",
             linewidth=1.5, label="Cumulative %")
    ax2.axhline(80, color=GOLD, linestyle=":", linewidth=1, label="80% reference")
    ax2.set_ylabel("Cumulative share (%)")
    ax2.set_ylim(0, 105)
    for bar, share in zip(bars, shares):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                 f"{share * 100:.1f}%", ha="center", va="bottom", fontsize=8)
    ax1.set_title(title)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def spc_methods(reports: Path) -> dict[str, dict[str, float]]:
    """Recall vs precision per backtest method (shows the false-positive burden)."""
    df = pd.read_csv(reports / "spc_backtest_methods.csv")
    return {row["method"]: {"recall": round(float(row["recall"]) * 100, 2),
                            "precision": round(float(row["precision"]) * 100, 2)}
            for _, row in df.iterrows()}


def _spc_chart(path: Path, data: dict[str, dict[str, float]]) -> None:
    methods = list(data.keys())
    recall = [data[m]["recall"] for m in methods]
    precision = [data[m]["precision"] for m in methods]
    x = range(len(methods))
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.bar([i - 0.2 for i in x], recall, width=0.4, color=TEAL, label="Recall (%)")
    ax.bar([i + 0.2 for i in x], precision, width=0.4, color=RED, label="Precision (%)")
    ax.axhline(60, color=GOLD, linestyle="--", linewidth=1, label="Precision target 60%")
    ax.set_xticks(list(x))
    ax.set_xticklabels(methods, rotation=12)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Percent (%)")
    ax.set_title("SPC backtest: recall vs precision by method (1,097 Phase II lots)")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def run() -> dict[str, Any]:
    repo = _repo_root()
    reports = repo / "reports"
    assets = repo / "docs" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    _style()

    by_line = oee_by_line(reports)
    _bar_with_target(assets / "oee_by_line.png", "Plant OEE by line (%)", by_line, 85.0)
    by_shift = oee_by_shift(reports)
    _bar_with_target(assets / "oee_by_shift.png", "Plant OEE by shift (%)", by_shift, 85.0)

    scrap = pd.read_csv(reports / "pareto_scrap.csv")
    _pareto(assets / "scrap_pareto.png", "Scrap cost Pareto by defect cause",
            scrap["defect_cause"].tolist(), scrap["scrap_cost"].tolist(),
            scrap["scrap_cost_share"].tolist(),
            scrap["cumulative_scrap_cost_share"].tolist(), "Scrap cost ($)")

    downtime = pd.read_csv(reports / "pareto_downtime.csv")
    _pareto(assets / "downtime_pareto.png", "Downtime Pareto by reason (all events)",
            downtime["reason"].tolist(), downtime["duration_hours"].tolist(),
            downtime["downtime_share"].tolist(),
            downtime["cumulative_downtime_share"].tolist(), "Downtime (hours)")

    methods = spc_methods(reports)
    _spc_chart(assets / "spc_method_performance.png", methods)

    produced = {
        "oee_by_line": by_line,
        "oee_by_shift": by_shift,
        "spc_methods": methods,
        "files": ["oee_by_line.png", "oee_by_shift.png", "scrap_pareto.png",
                  "downtime_pareto.png", "spc_method_performance.png"],
    }
    print("Portfolio figures written to docs/assets/:")
    for name in produced["files"]:
        print(f"  - {name}")
    return produced


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        run()
    except Exception as exc:
        print(f"Figure generation failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
