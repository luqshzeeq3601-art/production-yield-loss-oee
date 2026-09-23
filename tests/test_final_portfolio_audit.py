"""P6-005 final portfolio audit gates (read-only, stable, non-duplicative)."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DOCS = [
    REPO / "README.md",
    REPO / "docs" / "case_study.md",
    REPO / "docs" / "resume_bullets.md",
    REPO / "docs" / "project_facts.md",
]

UNSAFE_PHRASES = [
    "Saved $1.69M",
    "saved $1.7M",
    "Prevented 38,047",
    "prevented 38,047",
    "Improved factory OEE",
    "improved factory OEE",
]

LIMITATION_MARKERS = [
    "simulated",
    "60%",
    "false-positive",
    "modeled",
    "manual",
    ".pbix",
]


def _text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in DOCS)


class TestAuditArtifact:
    def test_verdict(self):
        audit = json.loads((REPO / "reports" / "final_portfolio_audit.json").read_text(encoding="utf-8"))
        assert audit["overall_verdict"] == "PORTFOLIO_READY_WITH_MANUAL_POWERBI_STEP"
        assert audit["blocking_findings"] == []
        assert audit["limitations_visible"] is True

    def test_required_keys(self):
        audit = json.loads((REPO / "reports" / "final_portfolio_audit.json").read_text(encoding="utf-8"))
        for key in ["final_git_commit_before_audit", "test_status", "test_count",
                    "dq_status", "reconciliation_status", "O1_status", "O2_status",
                    "O3_status", "documentation_status", "PowerBI_status",
                    "reproducibility_status", "security_status",
                    "repository_hygiene_status", "manual_remaining_steps"]:
            assert key in audit, f"missing {key}"


class TestClaimSafety:
    def test_no_unsafe_wording(self):
        text = _text()
        lowered = text.lower()
        for phrase in UNSAFE_PHRASES:
            assert phrase.lower() not in lowered, f"unsafe wording: {phrase}"

    def test_no_stale_references(self):
        lowered = _text().lower()
        assert "bosch" not in lowered
        assert "file:///" not in _text()

    def test_limitations_present(self):
        lowered = _text().lower()
        for marker in LIMITATION_MARKERS:
            assert marker.lower() in lowered, f"missing limitation marker: {marker}"


class TestReportInventory:
    def test_key_reports_present(self):
        for name in ["impact_metrics.csv", "impact_metrics_summary.json",
                     "impact_claims.json", "full_validation_summary.json",
                     "cross_system_reconciliation_summary.json",
                     "powerbi_reconciliation_summary.json",
                     "spc_backtest_summary.json", "pareto_summary.json",
                     "oee_whatif_summary.json", "dq_check_summary.json",
                     "db_load_summary.json", "final_portfolio_audit.json"]:
            assert (REPO / "reports" / name).is_file(), f"missing reports/{name}"
