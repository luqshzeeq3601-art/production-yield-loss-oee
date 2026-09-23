"""Tests for the impact metrics engine (src/impact_metrics.py)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.impact_metrics import (
    ALLOWED_EVIDENCE_TYPES,
    CSV_COLUMNS,
    run,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS = REPO_ROOT / "reports"


@pytest.fixture(scope="module")
def impact_output():
    """Run impact_metrics.run() once and return the summary."""
    return run()


@pytest.fixture(scope="module")
def csv_rows(impact_output):
    """Read the generated CSV and return rows as dicts."""
    path = REPORTS / "impact_metrics.csv"
    assert path.is_file(), f"Missing: {path}"
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


@pytest.fixture(scope="module")
def claims_data(impact_output):
    """Read the generated claims JSON."""
    path = REPORTS / "impact_claims.json"
    assert path.is_file(), f"Missing: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def summary_data(impact_output):
    """Read the generated summary JSON."""
    path = REPORTS / "impact_metrics_summary.json"
    assert path.is_file(), f"Missing: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


# ── Schema ──────────────────────────────────────────────────────────────────


class TestSchema:
    def test_csv_has_required_columns(self, csv_rows):
        assert len(csv_rows) > 0
        for col in CSV_COLUMNS:
            assert col in csv_rows[0], f"Missing column: {col}"

    def test_no_extra_columns(self, csv_rows):
        actual = set(csv_rows[0].keys())
        expected = set(CSV_COLUMNS)
        assert actual == expected

    def test_metric_ids_unique(self, csv_rows):
        ids = [r["metric_id"] for r in csv_rows]
        assert len(ids) == len(set(ids)), f"Duplicate metric IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_no_empty_metric_ids(self, csv_rows):
        for row in csv_rows:
            assert row["metric_id"].strip(), "Empty metric_id found"

    def test_no_empty_categories(self, csv_rows):
        for row in csv_rows:
            assert row["category"].strip(), f"Empty category in {row['metric_id']}"


# ── Evidence Type Whitelist ─────────────────────────────────────────────────


class TestEvidenceTypes:
    def test_all_evidence_types_allowed(self, csv_rows):
        for row in csv_rows:
            assert row["evidence_type"] in ALLOWED_EVIDENCE_TYPES, (
                f"{row['metric_id']} has invalid evidence_type: {row['evidence_type']}"
            )

    def test_all_four_types_present(self, csv_rows):
        types_used = {r["evidence_type"] for r in csv_rows}
        for t in ALLOWED_EVIDENCE_TYPES:
            assert t in types_used, f"Evidence type {t} not used"


# ── Source Provenance ───────────────────────────────────────────────────────


class TestProvenance:
    def test_source_artifact_non_empty(self, csv_rows):
        for row in csv_rows:
            assert row["source_artifact"].strip(), (
                f"{row['metric_id']} has empty source_artifact"
            )

    def test_source_field_non_empty(self, csv_rows):
        for row in csv_rows:
            assert row["source_field"].strip(), (
                f"{row['metric_id']} has empty source_field"
            )

    def test_source_artifacts_are_valid_paths(self, csv_rows):
        valid_prefixes = {"reports/", "src/"}
        for row in csv_rows:
            sa = row["source_artifact"]
            if sa == "N/A":
                continue
            assert any(sa.startswith(p) for p in valid_prefixes), (
                f"{row['metric_id']} has unexpected source_artifact: {sa}"
            )


# ── Reporting Time Calculations ─────────────────────────────────────────────


class TestReportingAutomation:
    def test_manual_hours_per_week(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "RA-001")
        assert float(row["value"]) == 6.0

    def test_manual_minutes_per_week(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "RA-002")
        assert int(row["value"]) == 360

    def test_annual_manual_hours(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "RA-004")
        assert float(row["value"]) == 312.0

    def test_annual_automated_hours(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "RA-005")
        assert float(row["value"]) == 8.7

    def test_annual_hours_saved(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "RA-006")
        assert float(row["value"]) == 303.3

    def test_annual_hours_arithmetic(self, csv_rows):
        by_id = {r["metric_id"]: r for r in csv_rows}
        annual_manual = float(by_id["RA-004"]["value"])
        annual_auto = float(by_id["RA-005"]["value"])
        saved = float(by_id["RA-006"]["value"])
        assert abs((annual_manual - annual_auto) - saved) < 0.15

    def test_reduction_pct(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "RA-007")
        assert float(row["value"]) == 97.2

    def test_automated_under_10_minutes(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "RA-003")
        assert float(row["value"]) <= 10.0


# ── SPC / Early Warning ────────────────────────────────────────────────────


class TestSPCMetrics:
    def test_precision_target_failed(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "SPC-011")
        assert row["value"] == "No"
        assert row["status"] == "FAIL"

    def test_latency_target_passed(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "SPC-012")
        assert row["value"] == "Yes"
        assert row["status"] == "PASS"

    def test_recall_100_pct(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "SPC-004")
        assert float(row["value"]) == 100.0

    def test_phase2_lots(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "SPC-001")
        assert int(row["value"]) == 1097

    def test_precision_value_matches_backtest(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "SPC-003")
        assert abs(float(row["value"]) - 4.21) < 0.1

    def test_we_precision_value_matches_backtest(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "SPC-013")
        assert abs(float(row["value"]) - 4.23) < 0.1


# ── OEE Reconciliation ─────────────────────────────────────────────────────


class TestOEEMetrics:
    def test_plant_oee_matches_reconciliation(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "OEE-004")
        assert abs(float(row["value"]) - 74.41) < 0.1

    def test_availability_matches(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "OEE-001")
        assert abs(float(row["value"]) - 91.29) < 0.1

    def test_performance_matches(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "OEE-002")
        assert abs(float(row["value"]) - 84.50) < 0.1

    def test_quality_matches(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "OEE-003")
        assert abs(float(row["value"]) - 96.46) < 0.1

    def test_oee_line_shift_ids_present(self, csv_rows):
        by_id = {r["metric_id"]: r for r in csv_rows}
        for mid in ["OEE-009", "OEE-010", "OEE-011", "OEE-012",
                    "OEE-013", "OEE-014", "OEE-015"]:
            assert mid in by_id, f"Missing {mid}"
            assert 60.0 < float(by_id[mid]["value"]) < 85.0


# ── Pareto Reconciliation ──────────────────────────────────────────────────


class TestParetoMetrics:
    def test_top3_scrap_above_60pct(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "PAR-001")
        assert float(row["value"]) >= 60.0

    def test_top3_downtime_above_60pct(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "PAR-003")
        assert float(row["value"]) >= 60.0


# ── Modeled Scenario Labeling ──────────────────────────────────────────────


class TestModeledLabeling:
    def test_whatif_metrics_labeled_modeled(self, csv_rows):
        whatif_rows = [r for r in csv_rows if r["metric_id"].startswith("WIF-")]
        assert len(whatif_rows) >= 6
        for row in whatif_rows:
            assert row["evidence_type"] in ("MODELED", "CONFIGURED_BASELINE"), (
                f"{row['metric_id']} should be MODELED or CONFIGURED_BASELINE, "
                f"got {row['evidence_type']}"
            )

    def test_whatif_category_contains_modeled_label(self, csv_rows):
        whatif_rows = [r for r in csv_rows if r["metric_id"].startswith("WIF-")]
        modeled_rows = [r for r in whatif_rows if r["evidence_type"] == "MODELED"]
        for row in modeled_rows:
            assert "MODELED" in row["category"], (
                f"{row['metric_id']} category should contain 'MODELED'"
            )

    def test_no_realized_savings_language_for_modeled(self, csv_rows):
        modeled = [r for r in csv_rows if r["evidence_type"] == "MODELED"]
        unsafe_words = ["saved", "prevented", "improved", "achieved savings"]
        for row in modeled:
            text = (row["notes"] + " " + row["metric_name"]).lower()
            for word in unsafe_words:
                assert word not in text, (
                    f"{row['metric_id']} uses unsafe language '{word}' "
                    f"for MODELED outcome"
                )


# ── Power BI Reconciliation ────────────────────────────────────────────────


class TestPowerBIReconciliation:
    def test_reconciliation_pass(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "DQ-003")
        assert row["value"] == "PASS"
        assert row["status"] == "PASS"


# ── Database + Pipeline Validation ─────────────────────────────────────────


class TestDatabasePipelineValidation:
    def test_db_reconciliation_pass(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "DQ-005")
        assert row["value"] == "PASS"
        assert row["status"] == "PASS"
        assert row["evidence_type"] == "VALIDATION"

    def test_pipeline_status(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "DQ-006")
        assert row["value"] == "SUCCESS"
        assert row["evidence_type"] == "VALIDATION"

    def test_pipeline_runtime_present(self, csv_rows):
        row = next(r for r in csv_rows if r["metric_id"] == "DQ-007")
        assert float(row["value"]) >= 0.0
        assert row["unit"] == "seconds"


# ── Objective Assessment ────────────────────────────────────────────────────


class TestObjectiveAssessment:
    def test_o1_partial_due_to_precision(self, summary_data):
        o1 = summary_data["objectives"]["O1"]
        assert o1["status"] == "PARTIAL"
        assert o1["latency_target_met"] is True
        assert o1["precision_target_met"] is False

    def test_o2_achieved(self, summary_data):
        o2 = summary_data["objectives"]["O2"]
        assert o2["status"] == "ACHIEVED"
        assert o2["oee_decomposition_calculated"] is True
        assert o2["top_3_scrap_above_60pct"] is True
        assert o2["whatif_analysis_completed"] is True

    def test_o3_achieved(self, summary_data):
        o3 = summary_data["objectives"]["O3"]
        assert o3["status"] == "ACHIEVED"
        assert o3["baseline_6h_confirmed"] is True
        assert o3["automated_under_10min"] is True


# ── Claims Safety ───────────────────────────────────────────────────────────


class TestClaimsSafety:
    def test_claims_have_required_fields(self, claims_data):
        required = {"claim", "evidence_type", "source", "safe_to_use", "caveat"}
        for claim in claims_data:
            assert required.issubset(claim.keys()), f"Missing fields in claim"

    def test_unsafe_claims_flagged(self, claims_data):
        unsafe = [c for c in claims_data if not c["safe_to_use"]]
        assert len(unsafe) >= 3, "Should have at least 3 unsafe example claims"
        for c in unsafe:
            assert "UNSAFE" in c["caveat"], "Unsafe claims must say UNSAFE in caveat"

    def test_safe_claims_exist(self, claims_data):
        safe = [c for c in claims_data if c["safe_to_use"]]
        assert len(safe) >= 5


# ── Determinism ─────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_two_runs_produce_identical_csv(self, tmp_path):
        """Run engine twice and verify byte-identical CSV output."""
        run()
        csv1 = (REPORTS / "impact_metrics.csv").read_bytes()
        run()
        csv2 = (REPORTS / "impact_metrics.csv").read_bytes()
        assert csv1 == csv2, "Two consecutive runs produced different CSV output"

    def test_two_runs_produce_identical_summary(self):
        run()
        s1 = (REPORTS / "impact_metrics_summary.json").read_bytes()
        run()
        s2 = (REPORTS / "impact_metrics_summary.json").read_bytes()
        assert s1 == s2

    def test_two_runs_produce_identical_claims(self):
        run()
        c1 = (REPORTS / "impact_claims.json").read_bytes()
        run()
        c2 = (REPORTS / "impact_claims.json").read_bytes()
        assert c1 == c2


# ── Ordering ────────────────────────────────────────────────────────────────


class TestOrdering:
    def test_metrics_ordered_by_category_group(self, csv_rows):
        """Verify metrics appear in category groups (RA, SPC, OEE, PAR, WIF, DQ, SCL)."""
        prefixes = [r["metric_id"].split("-")[0] for r in csv_rows]
        seen_order = []
        for p in prefixes:
            if not seen_order or seen_order[-1] != p:
                seen_order.append(p)
        expected = ["RA", "SPC", "OEE", "PAR", "WIF", "DQ", "SCL"]
        assert seen_order == expected, f"Ordering: {seen_order}"
