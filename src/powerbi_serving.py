"""Load frozen analytical evidence and verify Desktop assembly dependencies.

This serving layer does not rerun or tune SPC/RCA/impact calculations. The
full analytical pipeline remains the default in src.load_db and run_pipeline.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pandas as pd
from psycopg2 import sql
from psycopg2.extras import execute_values

from src.config_loader import load_config
from src.dashboard_spec import REQUIRED_PAGES
from src.powerbi_model import evaluate_dax_measures

ROOT = Path(__file__).resolve().parents[1]


def validate_spc_evidence(reports: Path, cleaned_path: Path) -> dict:
    """Reject stale CSV metrics or lot identities without changing evidence."""
    summary = json.loads((reports / "spc_backtest_summary.json").read_text())
    methods = pd.read_csv(reports / "spc_backtest_methods.csv").set_index("method")
    for method, result in summary["methods"].items():
        for field in ("TP", "FP", "TN", "FN", "precision", "recall", "prevalence",
                      "population_lots", "false_alarms_per_100_lots",
                      "median_detection_latency_hours", "median_hours_saved",
                      "p90_hours_saved", "pct_failures_before_manual"):
            if abs(float(methods.loc[method, field]) - float(result[field])) > 1e-12:
                raise ValueError(f"Stale SPC evidence: {method}/{field}")
        precision = result["TP"] / (result["TP"] + result["FP"])
        if abs(precision - result["precision"]) > 1e-12:
            raise ValueError(f"Invalid precision confusion counts: {method}")
    lots = pd.read_csv(reports / "spc_backtest_lots.csv")
    cleaned = pd.read_csv(cleaned_path)
    boundary = summary["frozen_evidence"]["phase1_boundary"]
    expected = cleaned.iloc[boundary:].reset_index(drop=True)
    if lots.source_row.tolist() != list(range(boundary, len(cleaned))):
        raise ValueError("Stale SPC lot identity or Phase II population")
    if (lots.target.tolist() != expected.target.tolist()
            or not pd.to_datetime(lots.timestamp).equals(pd.to_datetime(expected.timestamp))):
        raise ValueError("SPC lots do not match the cleaned source")
    for method, result in summary["methods"].items():
        if result["population_lots"] != len(lots) or result["TP"] + result["FN"] != int(lots.target.sum()):
            raise ValueError(f"SPC method population mismatch: {method}")
    return summary


def _replace_table(cursor, name: str, frame: pd.DataFrame, keys: tuple[str, ...]) -> None:
    """Atomic typed snapshot import; callers own the transaction."""
    if frame.empty or frame.duplicated(list(keys)).any():
        raise ValueError(f"Empty or duplicate evidence keys in {name}")
    columns = []
    for column, dtype in frame.dtypes.items():
        kind = ("BOOLEAN" if pd.api.types.is_bool_dtype(dtype) else
                "BIGINT" if pd.api.types.is_integer_dtype(dtype) else
                "DOUBLE PRECISION" if pd.api.types.is_numeric_dtype(dtype) else
                "TIMESTAMP" if pd.api.types.is_datetime64_any_dtype(dtype) else "TEXT")
        columns.append(sql.SQL("{} {}").format(sql.Identifier(column), sql.SQL(kind)))
    relation = sql.Identifier("analytics", name)
    cursor.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} ({}, PRIMARY KEY ({}))").format(
        relation, sql.SQL(", ").join(columns), sql.SQL(", ").join(map(sql.Identifier, keys)),
    ))
    cursor.execute(sql.SQL("TRUNCATE {}").format(relation))
    values = [tuple(None if pd.isna(v) else v for v in row)
              for row in frame.itertuples(index=False, name=None)]
    execute_values(cursor, sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
        relation, sql.SQL(", ").join(map(sql.Identifier, frame.columns)),
    ).as_string(cursor), values)


def load_evidence(conn, reports: Path, dq: dict) -> dict[str, int]:
    """Load historical SPC diagnostics, impact provenance, and check results."""
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT sensor_code, sensor_key FROM analytics.dim_sensor WHERE source_system='SECOM'")
            sensors = dict(cur.fetchall())
            snapshots = {
                "pb_spc_methods": (pd.read_csv(reports / "spc_backtest_methods.csv"), ("method",)),
                "pb_spc_lots": (pd.read_csv(reports / "spc_backtest_lots.csv", parse_dates=["timestamp"]), ("source_row",)),
                "pb_spc_failures": (pd.read_csv(reports / "spc_backtest_failures.csv", parse_dates=["timestamp"]), ("source_row", "method")),
                "pb_spc_limits": (pd.read_csv(reports / "spc_limits.csv"), ("sensor_key",)),
                "pb_impact_metrics": (pd.read_csv(reports / "impact_metrics.csv"), ("metric_id",)),
                "pb_dq_checks": (pd.DataFrame(dq["checks"]), ("check_id",)),
                "pb_reconciliation": (pd.read_csv(reports / "cross_system_reconciliation.csv"), ("reconciliation_id",)),
                "pb_oee_bridge": (pd.DataFrame({"step": ["Planned", "Availability Loss", "Performance Loss", "Quality Loss", "Good Output"], "step_order": range(1, 6)}), ("step",)),
            }
            limits = snapshots["pb_spc_limits"][0]
            limits["sensor_key"] = limits.sensor.map(sensors)
            if limits.sensor_key.isna().any():
                raise ValueError("Unresolved SPC sensor key")
            limits["sensor_key"] = limits.sensor_key.astype(int)
            snapshots["pb_impact_metrics"][0]["numeric_value"] = pd.to_numeric(
                snapshots["pb_impact_metrics"][0].value, errors="coerce",
            )
            failures = snapshots["pb_spc_failures"][0]
            failures["hours_saved_bucket"] = failures.hours_saved.fillna(0).astype(int)
            for table, (frame, keys) in snapshots.items():
                _replace_table(cur, table, frame, keys)
            # Historical diagnostic events, not observed production acknowledgments.
            cur.execute("TRUNCATE analytics.fact_spc_alert RESTART IDENTITY")
            alerts = []
            for filename, method, value_field in (
                ("spc_rule_violations.csv", "WE", "value"),
                ("ewma_violations.csv", "EWMA", "ewma_value"),
                ("hotelling_t2_violations.csv", "T2", "t2"),
            ):
                for row in pd.read_csv(reports / filename).to_dict("records"):
                    sensor = None if method == "T2" else sensors[row["sensor"]]
                    alerts.append((pd.Timestamp(row["timestamp"]).to_pydatetime(), sensor,
                                   "SECOM", int(row["source_row"]), row.get("rule", method),
                                   method, "warning", "open", float(row[value_field])))
            execute_values(cur, """INSERT INTO analytics.fact_spc_alert
                (alert_ts,sensor_key,source_system,source_row,rule_code,method,severity,status,statistic_value)
                VALUES %s""", alerts)
            cur.execute((ROOT / "sql/07_powerbi_serving.sql").read_text(encoding="utf-8"))
    return {name: len(frame) for name, (frame, _) in snapshots.items()} | {"fact_spc_alert": len(alerts)}


def validate_bindings(conn) -> list[dict]:
    """Resolve every visual field, DAX column, measure, and relationship live."""
    with (ROOT / "powerbi/model_mapping.csv").open(newline="", encoding="utf-8") as stream:
        mapping = {row["table_name"]: row for row in csv.DictReader(stream)}
    columns, counts = {}, {}
    with conn.cursor() as cur:
        for name, row in mapping.items():
            schema, relation = row["schema_source"].split(".")
            cur.execute(sql.SQL("SELECT * FROM {} LIMIT 0").format(sql.Identifier(schema, relation)))
            columns[name] = {item.name for item in cur.description}
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(schema, relation)))
            counts[name] = int(cur.fetchone()[0])
            if counts[name] == 0:
                raise ValueError(f"Empty Power BI relation: {name}")
            if row["primary_key"]:
                keys = [k.strip() for k in row["primary_key"].split(",")]
                cur.execute(sql.SQL("SELECT COUNT(*) FROM (SELECT {} FROM {} GROUP BY {} HAVING COUNT(*) > 1) d").format(
                    sql.SQL(",").join(map(sql.Identifier, keys)), sql.Identifier(schema, relation),
                    sql.SQL(",").join(map(sql.Identifier, keys)),
                ))
                if cur.fetchone()[0]:
                    raise ValueError(f"Nonunique model key: {name}")
    dax = (ROOT / "powerbi/measures.dax").read_text(encoding="utf-8")
    measures = set(re.findall(r"^\[([^\]]+)\]\s*=", dax, re.M))
    dependencies = {}
    for match in re.finditer(r"^\[([^\]]+)\]\s*=(.*?)(?=^\[[^\]]+\]\s*=|\Z)", dax, re.M | re.S):
        tables = set()
        for table, column in re.findall(r"\b(\w+)\[([^\]]+)\]", match[2]):
            if column not in columns.get(table, set()):
                raise ValueError(f"Unmapped DAX column: {table}[{column}]")
            tables.add(table)
        dependencies[match[1]] = (tables, set(re.findall(r"(?<!\w)\[([^\]]+)\]", match[2])))
    def measure_tables(name, visited=None):
        if name not in measures:
            raise ValueError(f"Missing DAX measure: {name}")
        visited = set() if visited is None else visited
        if name in visited:
            return set()
        visited.add(name)
        tables, refs = dependencies[name]
        return tables | set().union(*(measure_tables(r, visited) for r in refs))
    def collect(value, tables, used):
        if isinstance(value, (list, dict)):
            if isinstance(value, dict):
                for key, item in value.items():
                    if "." in key:
                        collect(key, tables, used)
                    collect(item, tables, used)
            else:
                for item in value:
                    collect(item, tables, used)
        elif isinstance(value, str):
            for table, column in re.findall(r"\b(\w+)\.(\w+)", value):
                if table not in mapping or column not in columns[table]:
                    raise ValueError(f"Unmapped visual column: {table}.{column}")
                tables.add(table)
            for name in re.findall(r"\[([^\]]+)\]", value):
                used.add(name)
                tables.update(measure_tables(name))
    for row in mapping.values():
        for key, target in re.findall(r"(\w+) -> (\w+)", row["foreign_keys"]):
            if key not in columns[row["table_name"]] or target not in mapping:
                raise ValueError("Invalid relationship mapping")
    pages = json.loads((ROOT / "powerbi/visual_mapping.json").read_text())["pages"]
    if {p["page_id"] for p in pages} != {p[0] for p in REQUIRED_PAGES} or len(pages) != 7:
        raise ValueError("Missing or duplicate dashboard pages")
    result = []
    for page in pages:
        tables, used = set(), set()
        for visual in page["visuals"]:
            # Titles may contain decimals and aren't data bindings.
            collect({k: v for k, v in visual.items() if k not in {"title", "position", "format", "id"}}, tables, used)
            if visual["type"] == "card" and not re.fullmatch(r"\[[^\]]+\]", visual["measure"]):
                raise ValueError(f"Literal card value: {visual['id']}")
        for table in list(tables):
            tables.update(re.findall(r"-> (\w+)", mapping[table]["foreign_keys"]))
        result.append({"page": page["display_name"], "status": "READY", "relations": sorted(tables),
                       "dimensions": sorted(t for t in tables if mapping[t]["table_type"] == "Dimension"),
                       "measures": sorted(used), "relation_rows": {t: counts[t] for t in sorted(tables)}})
    return result


def validate_live(conn, config_path=None) -> dict:
    """Compare real SQL aggregates to source components and the model emulator."""
    config = load_config(config_path)
    outputs = config["mes"]["outputs"]
    frames = [pd.read_csv(ROOT / outputs[k]) for k in (
        "production_hourly", "downtime_events", "quality_events", "manpower_shifts", "station_operations",
    )]
    expected = evaluate_dax_measures(*frames)
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        select_one = cur.fetchone()[0]
        cur.execute("SELECT * FROM analytics.vw_oee_plant")
        plant = dict(zip([c.name for c in cur.description], cur.fetchone()))
        comparisons = {"total_count": "total_units", "good_count": "good_units", "scrap_count": "scrap_units",
                       "availability": "availability", "performance": "performance", "quality": "quality", "oee": "oee"}
        for actual, exp in comparisons.items():
            a, b = float(plant[actual]), float(expected["plant_overview"][exp])
            if abs(a - b) > max(abs(b) * 0.001, 1e-9):
                raise ValueError(f"Live SQL/source mismatch: {actual}")
        cur.execute("SELECT status, COUNT(*) FROM analytics.vw_work_orders GROUP BY status")
        wo_counts = dict(cur.fetchall())
        source_orders = pd.read_csv(ROOT / outputs["work_orders"])
        if wo_counts != source_orders.status.value_counts().to_dict():
            raise ValueError("Live work-order status mismatch")
        cur.execute("SELECT SUM(planned_headcount), SUM(actual_headcount) FROM analytics.fact_manpower_shift")
        manpower = list(map(int, cur.fetchone()))
        if manpower != [int(frames[3][c].sum()) for c in ("planned_headcount", "actual_headcount")]:
            raise ValueError("Live manpower/source mismatch")
        cur.execute("SELECT SUM(scrap_cost) FROM analytics.fact_quality_scrap")
        scrap_cost = float(cur.fetchone()[0])
        if abs(scrap_cost - expected["loss_decomposition"]["total_scrap_cost"]) > 0.01:
            raise ValueError("Live scrap-cost mismatch")
        cur.execute("SELECT SUM(e.duration_min) FROM analytics.fact_downtime_event e JOIN analytics.dim_downtime_reason r USING(downtime_reason_key) WHERE NOT r.is_planned")
        downtime = float(cur.fetchone()[0])
        if abs(downtime / 60 - expected["loss_decomposition"]["unplanned_downtime_hours"]) > 1e-6:
            raise ValueError("Live downtime mismatch")
    return {"select_one": select_one, "plant": plant, "scrap_cost": scrap_cost,
            "unplanned_downtime_minutes": downtime, "work_orders": wo_counts, "manpower": manpower,
            "pages": validate_bindings(conn), "powerbi_engine_executed": False,
            "comparison_basis": "live SQL vs source components and Python DAX-formula emulation; PBIX not assembled"}
