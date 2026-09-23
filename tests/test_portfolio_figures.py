"""P6 polish: portfolio figure provenance and schema tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.generate_portfolio_figures import oee_by_line, oee_by_shift, run, spc_methods

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "reports"
ASSETS = REPO / "docs" / "assets"

EXPECTED_FILES = [
    "oee_by_line.png",
    "oee_by_shift.png",
    "scrap_pareto.png",
    "downtime_pareto.png",
    "spc_method_performance.png",
]


class TestFigureProvenance:
    def test_oee_by_line_matches_powerbi(self):
        pb = json.loads((REPORTS / "powerbi_reconciliation_summary.json").read_text(encoding="utf-8"))
        data = oee_by_line(REPORTS)
        assert set(data) == {"L1", "L2", "L3", "L4"}
        for line, value in data.items():
            assert value == round(float(pb["dax_evaluation"]["line_breakdown"][line]["oee"]) * 100, 2)

    def test_oee_by_shift_matches_powerbi(self):
        pb = json.loads((REPORTS / "powerbi_reconciliation_summary.json").read_text(encoding="utf-8"))
        data = oee_by_shift(REPORTS)
        assert set(data) == {"A", "B", "C"}
        for shift, value in data.items():
            assert value == round(float(pb["dax_evaluation"]["shift_breakdown"][shift]["oee"]) * 100, 2)

    def test_spc_methods_match_backtest(self):
        df = pd.read_csv(REPORTS / "spc_backtest_methods.csv")
        data = spc_methods(REPORTS)
        assert set(data) == set(df["method"])
        # Both recall and precision shown: the false-positive burden stays visible.
        assert data["WE"]["recall"] == 100.0
        assert abs(data["WE"]["precision"] - 4.23) < 0.05


class TestFigureSchema:
    def test_files_exist_nonempty_png(self):
        run()
        for name in EXPECTED_FILES:
            path = ASSETS / name
            assert path.is_file(), f"missing docs/assets/{name}"
            raw = path.read_bytes()
            assert len(raw) > 5000, f"{name} suspiciously small"
            assert raw[:8] == b"\x89PNG\r\n\x1a\n", f"{name} not a PNG"
