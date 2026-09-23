"""P6-004 documentation claim-consistency gate.

Validates that portfolio documentationnumeric claims match committed evidence
and that unsafe wording (realized savings, hidden precision miss, complete
PBIX, undeclared simulation) is absent. Tolerant to formatting, strict on facts.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "reports"
DOCS = REPO / "docs"


def _json(name: str) -> dict:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def _doc(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def _readme() -> str:
    return (REPO / "README.md").read_text(encoding="utf-8")


class TestEvidenceFacts:
    def test_secom_lots(self):
        assert _json("secom_cleaning_summary.json")["original_row_count"] == 1567

    def test_metropt_observations(self):
        assert _json("metropt3_ingestion_summary.json")["expected_rows"] == 1516948

    def test_metropt_readings(self):
        assert _json("db_load_summary.json")["reconciliation"]["metropt3_readings_fact"] == 22754220

    def test_mes_rows(self):
        assert _json("db_load_summary.json")["fact_counts"]["fact_production_hourly"] == 17280

    def test_oee(self):
        assert abs(_json("oee_whatif_summary.json")["baseline"]["oee"] * 100 - 74.41) < 0.05

    def test_scrap_concentration(self):
        kf = _json("pareto_summary.json")["key_findings"]
        assert abs(kf["top_3_scrap_cost_share"] * 100 - 74.38) < 0.05

    def test_downtime_concentration(self):
        kf = _json("pareto_summary.json")["key_findings"]
        assert abs(kf["top_3_downtime_share_unplanned"] * 100 - 87.75) < 0.05

    def test_we_precision_recall(self):
        we = _json("spc_backtest_summary.json")["methods"]["WE"]
        assert abs(we["precision"] * 100 - 4.23) < 0.05
        assert we["recall"] == 1.0

    def test_reporting_baseline(self):
        m = _json("manual_reporting_baseline.json")
        assert m["baseline_workflow"]["weekly_manual_hours"] == 6.0
        assert m["automation_target"]["efficiency_gain_pct"] == 97.2

    def test_dq_checks(self):
        dq = _json("dq_check_summary.json")
        assert dq["passed_checks"] == 65 and dq["total_violations"] == 0

    def test_reconciliation_checks(self):
        s = _json("cross_system_reconciliation_summary.json")
        assert s["total_checks"] == 75 and s["fail_count"] == 0

    def test_suite_count(self):
        # Committed P6-002 evidence records 212; the suite only grows since.
        assert _json("full_validation_summary.json")["test_total"] >= 212


class TestReadmeHonesty:
    def test_o1_partial_visible(self):
        assert "PARTIAL" in _readme()

    def test_precision_miss_visible(self):
        assert "4.21%" in _readme() and "60%" in _readme()

    def test_simulated_mes_labeled(self):
        assert "Simulated" in _readme() or "simulated" in _readme()

    def test_pbix_not_claimed_complete(self):
        text = _readme()
        assert "manual" in text.lower() and ".pbix" in text

    def test_no_realized_savings(self):
        text = _readme()
        assert "Saved $1.69M" not in text
        assert "saved $1.7M" not in text.lower()

    def test_modeled_qualified(self):
        text = _readme()
        assert "Modeled" in text or "modeled" in text
        assert "projected" in text.lower()

    def test_stale_claims_removed(self):
        text = _readme()
        assert "dashboard is not built yet" not in text
        assert "115 pytest tests" not in text


class TestPortfolioDocs:
    def test_docs_exist(self):
        for name in ["case_study.md", "resume_bullets.md", "project_facts.md"]:
            assert (DOCS / name).is_file(), f"missing docs/{name}"

    def test_resume_uses_safe_claims(self):
        text = _doc("resume_bullets.md")
        assert "Saved $1.69M" not in text
        assert "projecting OEE improvement from\n74.41% to 78.96%" in text or \
            "74.41% to 78.96%" in text
        assert "$1.69M annual recoverable value" in text

    def test_case_study_failure_section(self):
        text = _doc("case_study.md").lower()
        assert "failed" in text and "precision" in text

    def test_project_facts_divides_outcomes(self):
        text = _doc("project_facts.md")
        assert "Measured" in text and "Configured baseline" in text and "Modeled" in text

    def test_impact_csv_objectives_match_docs(self):
        with open(REPORTS / "impact_metrics.csv", encoding="utf-8") as f:
            rows = {r["metric_id"]: r for r in csv.DictReader(f)}
        assert rows["OEE-004"]["value"] == "74.41"
        assert "PARTIAL" in _doc("project_facts.md") or "PARTIAL" in _readme()
