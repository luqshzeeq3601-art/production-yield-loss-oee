"""Interactive dashboard: provenance of embedded values and page integrity."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from src.build_dashboard import PLACEHOLDER, build_payload, render, run

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "reports"


@pytest.fixture(scope="module")
def payload() -> dict:
    return build_payload(REPO)


def test_plant_kpis_match_impact_metrics(payload):
    m = pd.read_csv(REPORTS / "impact_metrics.csv").set_index("metric_id")["value"]
    plant = payload["summary"]["plant"]
    assert round(plant["oee"] * 100, 2) == float(m["OEE-004"])
    assert round(plant["availability"] * 100, 2) == float(m["OEE-001"])
    assert round(plant["performance"] * 100, 2) == float(m["OEE-002"])
    assert round(plant["quality"] * 100, 2) == float(m["OEE-003"])
    assert payload["summary"]["scrap_cost"] == float(m["OEE-007"])


def test_line_oee_matches_impact_metrics(payload):
    m = pd.read_csv(REPORTS / "impact_metrics.csv").set_index("metric_id")["value"]
    for i, line in enumerate(["L1", "L2", "L3", "L4"], start=9):
        assert (
            abs(
                payload["summary"]["lines"][line]["oee"] * 100
                - float(m[f"OEE-{i:03d}"])
            )
            < 0.01
        )


def _cube_totals(mes: dict) -> dict:
    f = {k: i for i, k in enumerate(mes["prod_fields"])}
    keys = ["planned_min", "run_min", "ideal_min", "total", "good", "scrap_ideal_min"]
    return {k: sum(r[f[k]] for r in mes["prod"]) for k in keys}


def test_filter_cube_covers_full_horizon(payload):
    mes = payload["mes"]
    assert sum(w["days"] for w in mes["weeks"]) == 180
    assert len(mes["weeks"]) == 26


def test_filter_cube_reproduces_validated_oee_and_losses(payload):
    t = _cube_totals(payload["mes"])
    a, p, q = (
        t["run_min"] / t["planned_min"],
        t["ideal_min"] / t["run_min"],
        t["good"] / t["total"],
    )
    plant = payload["summary"]["plant"]
    assert abs(a * p * q - plant["oee"]) < 1e-4
    assert t["total"] == plant["total_units"] and t["good"] == plant["good_units"]
    loss = payload["summary"]["loss_hours"]
    assert abs((t["planned_min"] - t["run_min"]) / 60 - loss["availability"]) < 0.1
    assert abs((t["run_min"] - t["ideal_min"]) / 60 - loss["performance"]) < 0.1
    assert abs(t["scrap_ideal_min"] / 60 - loss["quality"]) < 0.1


def test_filter_cube_reproduces_paretos(payload):
    mes = payload["mes"]
    downtime: dict[str, float] = {}
    for _, _, reason, minutes, _ in mes["downtime"]:
        downtime[reason] = downtime.get(reason, 0) + minutes / 60
    for row in payload["pareto"]["downtime"]:
        assert abs(downtime[row["label"].replace(" ", "_")] - row["value"]) < 0.1
    unplanned = sum(v for k, v in downtime.items() if not mes["reasons"][k]["planned"])
    assert abs(unplanned - payload["summary"]["unplanned_downtime_hours"]) < 0.1
    scrap: dict[str, float] = {}
    for _, _, cause, cost, _ in mes["scrap"]:
        scrap[cause] = scrap.get(cause, 0) + cost
    for row in payload["pareto"]["scrap"]:
        assert abs(scrap[row["label"]] - row["value"]) < 1


def test_spc_methods_keep_precision_visible(payload):
    methods = {r["method"]: r for r in payload["spc"]["methods"]}
    assert methods["WE"]["recall"] == 1.0
    assert abs(methods["WE"]["precision"] * 100 - 4.23) < 0.01


def test_pareto_cumulative_ends_at_one(payload):
    for key in ("downtime", "scrap"):
        assert abs(payload["pareto"][key][-1]["cum"] - 1.0) < 1e-3


def test_render_escapes_script_close():
    out = render({"x": "</script>"}, f"<script>const D = {PLACEHOLDER};</script>")
    assert out.count("</script>") == 1


def test_built_page_is_self_contained(tmp_path):
    out = tmp_path / "dashboard.html"
    run(out)
    html = out.read_text(encoding="utf-8")
    assert PLACEHOLDER not in html
    assert not re.search(
        r"<script[^>]+src=", html
    ), "dashboard must not load external scripts"
    data = json.loads(
        re.search(r"const DATA = (\{.*?\});\n", html).group(1).replace("<\\/", "</")
    )
    assert set(data) == {"summary", "mes", "pareto", "spc", "whatif", "impact"}
