"""P6-002 full-validation regression gate (read-only, no writes, no DB).

Stable cross-phase checks missing as a single gate:
- required artifact inventory exists and parses
- frozen SPC / OEE / Pareto / reconciliation values within tolerance
- impact objective statuses
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "reports"


def _load(name: str) -> dict:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


class TestArtifactInventory:
    def test_required_json_parse(self):
        for name in [
            "spc_backtest_summary.json",
            "oee_whatif_summary.json",
            "pareto_summary.json",
            "powerbi_reconciliation_summary.json",
            "impact_metrics_summary.json",
            "dq_check_summary.json",
            "db_load_summary.json",
            "pipeline_run_summary.json",
        ]:
            assert (REPORTS / name).is_file(), f"missing {name}"
            assert isinstance(_load(name), dict), f"{name} not a JSON object"

    def test_required_sql_files(self):
        for name in [
            "01_schema.sql",
            "02_staging.sql",
            "03_dims.sql",
            "04_facts.sql",
            "05_views_kpi.sql",
            "06_dq_checks.sql",
        ]:
            assert (REPO / "sql" / name).is_file(), f"missing sql/{name}"

    def test_impact_csv_schema(self):
        path = REPORTS / "impact_metrics.csv"
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) >= 57
        required = {
            "metric_id",
            "category",
            "metric_name",
            "value",
            "unit",
            "evidence_type",
            "source_artifact",
            "source_field",
            "status",
            "notes",
        }
        assert required.issubset(rows[0].keys())
        assert len({r["metric_id"] for r in rows}) == len(rows)

    def test_excel_opens(self):
        openpyxl = __import__("openpyxl")
        wb = openpyxl.load_workbook(
            REPO / "excel" / "manual_report_baseline.xlsx",
            read_only=True,
            data_only=False,
        )
        assert set(wb.sheetnames) >= {
            "Executive_Summary",
            "OEE_Summary",
            "Downtime_Summary",
            "Scrap_Summary",
        }
        wb.close()


class TestFrozenRegression:
    def test_spc_frozen(self):
        b = _load("spc_backtest_summary.json")
        assert b["phase2_lots"] == 1097
        assert b["phase2_fail"] == 46
        assert b["methods"]["WE"]["recall"] == 1.0
        assert abs(b["methods"]["WE"]["precision"] * 100 - 4.23) < 0.05
        assert abs(b["methods"]["WE+EWMA+T2"]["precision"] * 100 - 4.21) < 0.05

    def test_oee_frozen(self):
        w = _load("oee_whatif_summary.json")["baseline"]
        assert abs(w["availability"] * 100 - 91.29) < 0.05
        assert abs(w["performance"] * 100 - 84.50) < 0.05
        assert abs(w["quality"] * 100 - 96.46) < 0.05
        assert abs(w["oee"] * 100 - 74.41) < 0.05

    def test_pareto_frozen(self):
        p = _load("pareto_summary.json")["key_findings"]
        assert abs(p["top_3_scrap_cost_share"] * 100 - 74.38) < 0.05
        assert abs(p["top_3_downtime_share_unplanned"] * 100 - 87.75) < 0.05

    def test_powerbi_tolerance(self):
        r = _load("powerbi_reconciliation_summary.json")["reconciliation"]
        assert r["overall_status"] == "PASS"
        assert r["max_relative_diff_pct"] <= 0.1

    def test_objective_statuses(self):
        o = _load("impact_metrics_summary.json")["objectives"]
        assert o["O1"]["status"] == "PARTIAL"
        assert o["O2"]["status"] == "ACHIEVED"
        assert o["O3"]["status"] == "ACHIEVED"
