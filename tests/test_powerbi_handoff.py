"""Regression checks for the Desktop assembly handoff, not analytical tuning."""

import csv
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_precision_is_method_specific_and_not_prevalence():
    dax = (ROOT / "powerbi/measures.dax").read_text(encoding="utf-8")
    backtest = json.loads((ROOT / "reports/spc_backtest_summary.json").read_text())
    for measure, method in [("WE Precision %", "WE"),
                            ("Combined Precision %", "WE+EWMA+T2")]:
        expression = re.search(
            rf"^\[{re.escape(measure)}\]\s*=(.*?)(?=^\[[^\]]+\]\s*=|\Z)",
            dax, re.M | re.S,
        )
        assert expression is not None
        assert "pb_spc_methods" in expression[1]
        assert method in expression[1]
        result = backtest["methods"][method]
        assert result["precision"] == pytest.approx(result["TP"] / (result["TP"] + result["FP"]))
        assert result["precision"] != backtest["phase2_prevalence"]
    assert "0.0419" not in dax


def test_work_orders_and_report_evidence_are_mapped():
    with (ROOT / "powerbi/model_mapping.csv").open() as stream:
        mapping = {r["table_name"]: r for r in csv.DictReader(stream)}
    for name in ("vw_work_orders", "pb_spc_methods", "pb_dq_checks",
                 "pb_reconciliation", "pb_impact_metrics"):
        assert mapping[name]["schema_source"] == f"analytics.{name}"
    for dimension in ("dim_date", "dim_line", "dim_product"):
        assert dimension in mapping["vw_work_orders"]["foreign_keys"]


def test_work_order_visuals_use_observed_status_and_counts():
    mapping = json.loads((ROOT / "powerbi/visual_mapping.json").read_text())
    page = next(p for p in mapping["pages"] if p["page_id"] == 5)
    cards = {v["id"]: v for v in page["visuals"] if v["type"] == "card"}
    assert cards["v_wo_card_total"]["measure"] == "[Work Orders Total]"
    assert cards["v_wo_card_ontime"]["measure"] == "[WO On-Time %]"
    table = next(v for v in page["visuals"] if v["type"] == "table")
    assert "vw_work_orders.status" in table["columns"]
    assert "vw_work_orders.work_order_id" in table["columns"]
