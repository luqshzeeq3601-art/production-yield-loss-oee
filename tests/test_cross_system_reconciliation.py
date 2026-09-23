"""P6-003 cross-system reconciliation gate.

Helper comparison tests use small synthetic fixtures. Integration tests run
the file-based reconciliation engine (read-only apart from its two deterministic
output artifacts) and assert schema, domain coverage, ordering, and zero
unexplained FAIL rows.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.cross_system_reconciliation import (
    DOMAIN_ORDER,
    compare_currency,
    compare_exact,
    compare_float,
    compare_percent_points,
    run,
)

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "reports"


class TestExactComparison:
    def test_integers_equal(self):
        assert compare_exact(17280, 17280)[0] == "PASS"

    def test_integers_differ(self):
        status, diff, _ = compare_exact(17280, 17279)
        assert status == "FAIL"
        assert diff == 1.0

    def test_labels_equal(self):
        assert compare_exact("MODELED", "MODELED")[0] == "PASS"

    def test_labels_differ(self):
        assert compare_exact("MODELED", "MEASURED")[0] == "FAIL"


class TestFloatTolerance:
    def test_within_tolerance(self):
        assert compare_float(0.9128898195950569, 0.9128898195950568, 1e-9)[0] == "PASS"

    def test_exceeded_tolerance(self):
        status, diff, _ = compare_float(74.41, 74.60, 0.005)
        assert status == "FAIL"
        assert diff > 0.005

    def test_zero_source_both_zero(self):
        assert compare_float(0.0, 0.0, 1e-9)[0] == "PASS"


class TestPercentAndCurrency:
    def test_percent_points_boundary(self):
        assert compare_percent_points(4.2318, 4.23, 0.005)[0] == "PASS"
        assert compare_percent_points(4.23, 4.30, 0.005)[0] == "FAIL"

    def test_currency_cents(self):
        assert compare_currency(555891.0, 555891.0)[0] == "PASS"
        assert compare_currency(555891.0, 555891.02)[0] == "FAIL"


class TestModeledObservedDistinction:
    def test_modeled_label_is_not_observed(self):
        assert compare_exact("MODELED", "MEASURED")[0] == "FAIL"
        assert compare_exact("MODELED", "MODELED")[0] == "PASS"


class TestReconciliationOutputs:
    def test_run_passes(self):
        summary = run()
        assert summary["overall_status"] == "PASS"
        assert summary["fail_count"] == 0

    def test_required_domains_present(self):
        run()
        with open(REPORTS / "cross_system_reconciliation.csv", encoding="utf-8") as f:
            domains = {r["domain"] for r in csv.DictReader(f)}
        for d in DOMAIN_ORDER:
            assert d in domains, f"missing domain {d}"

    def test_output_schema(self):
        run()
        with open(REPORTS / "cross_system_reconciliation.csv", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == [
                "reconciliation_id", "domain", "metric_name", "source_layer",
                "target_layer", "source_value", "target_value", "unit",
                "tolerance", "absolute_difference", "relative_difference_pct",
                "status", "source_artifact", "target_artifact", "notes",
            ]
            rows = list(reader)
        assert len(rows) >= 50
        for r in rows:
            assert r["source_artifact"].strip()
            assert r["target_artifact"].strip()
            assert r["status"] in ("PASS", "FAIL", "WARNING")

    def test_deterministic_ordering(self):
        run()
        with open(REPORTS / "cross_system_reconciliation.csv", encoding="utf-8") as f:
            ids = [r["reconciliation_id"] for r in csv.DictReader(f)]
        prefixes = [i.split("-")[0] for i in ids]
        seen: list[str] = []
        for p in prefixes:
            if not seen or seen[-1] != p:
                seen.append(p)
        assert seen == ["MP", "MD", "MQ", "SC", "MT", "PB", "WF", "RP", "DQ"], seen

    def test_zero_unexplained_fail(self):
        summary = run()
        assert summary["fail_count"] == 0
        with open(REPORTS / "cross_system_reconciliation.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["status"] != "PASS":
                    assert r["notes"].strip(), f"{r['reconciliation_id']} unexplained"

    def test_deterministic_bytes(self):
        run()
        a = (REPORTS / "cross_system_reconciliation.csv").read_bytes()
        b = (REPORTS / "cross_system_reconciliation_summary.json").read_bytes()
        run()
        assert (REPORTS / "cross_system_reconciliation.csv").read_bytes() == a
        assert (REPORTS / "cross_system_reconciliation_summary.json").read_bytes() == b

    def test_summary_schema(self):
        summary = run()
        for key in ["total_checks", "pass_count", "fail_count", "warning_count",
                    "checks_by_domain", "exact_match_count",
                    "tolerance_match_count", "known_exceptions",
                    "modeled_metrics_checked", "overall_status"]:
            assert key in summary, f"missing {key}"
        assert summary["total_checks"] == summary["pass_count"] + summary["fail_count"] + summary["warning_count"]
        assert summary["modeled_metrics_checked"] == 6
        assert isinstance(summary["known_exceptions"], list)
