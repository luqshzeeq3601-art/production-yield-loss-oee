"""Tests for P5-003 Power BI dashboard visualization specification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.dashboard_spec import REQUIRED_PAGES, run, validate_dashboard_specification


REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_JSON = REPO_ROOT / "powerbi" / "visual_mapping.json"
DASHBOARD_MD = REPO_ROOT / "powerbi" / "dashboard_specification.md"
GUIDE_MD = REPO_ROOT / "powerbi" / "desktop_assembly_guide.md"


def test_all_seven_dashboard_pages_present():
    assert MAPPING_JSON.is_file()
    val = validate_dashboard_specification(MAPPING_JSON)

    assert val["page_count"] == 7
    assert val["status"] == "VALID"
    assert val["honest_spc_disclaimer_present"] is True

    observed_names = [p["name"] for p in val["pages"]]
    for _, expected_name, _ in REQUIRED_PAGES:
        assert expected_name in observed_names


def test_visual_structure_and_grid_coordinates():
    data = json.loads(MAPPING_JSON.read_text(encoding="utf-8"))
    for page in data["pages"]:
        assert len(page["visuals"]) > 0
        for visual in page["visuals"]:
            assert "id" in visual
            assert "type" in visual
            assert "title" in visual
            pos = visual["position"]
            assert pos["x"] >= 0
            assert pos["y"] >= 0
            assert pos["width"] > 0
            assert pos["height"] > 0
            assert pos["x"] + pos["width"] <= 1300
            assert pos["y"] + pos["height"] <= 750


def test_honest_spc_disclaimer_presence():
    data = json.loads(MAPPING_JSON.read_text(encoding="utf-8"))
    page3 = [p for p in data["pages"] if p["page_id"] == 3][0]
    banner = page3["visuals"][0]
    assert "4.2%" in banner["title"]
    assert "not met" in banner["title"].lower() or "not achieved" in banner["title"].lower()


def test_theme_and_documentation_artifacts():
    assert DASHBOARD_MD.is_file()
    assert GUIDE_MD.is_file()

    doc_text = DASHBOARD_MD.read_text(encoding="utf-8")
    for page_name in ["Executive Summary", "OEE Decomposition", "SPC / Early Warning", "Pareto & Root Cause", "Work Orders", "Capacity & Manpower", "Alerts & Data Quality"]:
        assert page_name in doc_text


def test_run_dashboard_spec_validator():
    summary = run()
    assert summary["dashboard_validation"]["status"] == "VALID"
    assert summary["dashboard_validation"]["total_visuals_specified"] >= 35

    out_file = REPO_ROOT / "reports" / "dashboard_specification_summary.json"
    assert out_file.is_file()
