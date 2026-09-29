"""Deterministic PostgreSQL loader: processed CSV -> staging -> dims -> facts."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from src.config_loader import load_config


SQL_FILES = (
    "01_schema.sql",
    "02_staging.sql",
    "03_dims.sql",
    "04_facts.sql",
    "05_views_kpi.sql",
)

STAGING_TABLES = (
    "staging.secom_cleaned",
    "staging.metropt3_readings",
    "staging.metropt3_failure_intervals",
    "staging.metropt3_state_periods",
    "staging.mes_production_hourly",
    "staging.mes_downtime_events",
    "staging.mes_work_orders",
    "staging.mes_manpower_shifts",
    "staging.mes_station_operations",
    "staging.mes_quality_events",
)

# MetroPT-3 signals: (staging column, sensor_type, unit). Units for analog
# signals come from the UCI variable table; digitals carry no unit.
METROPT_SIGNALS = (
    ("tp2", "analog", "bar"),
    ("tp3", "analog", "bar"),
    ("h1", "analog", "bar"),
    ("dv_pressure", "analog", "bar"),
    ("reservoirs", "analog", "bar"),
    ("oil_temperature", "analog", "C"),
    ("motor_current", "analog", "A"),
    ("comp", "digital", None),
    ("dv_eletric", "digital", None),
    ("towers", "digital", None),
    ("mpg", "digital", None),
    ("lps", "digital", None),
    ("pressure_switch", "digital", None),
    ("oil_level", "digital", None),
    ("caudal_impulses", "digital", None),
)

RERUN_STRATEGY = (
    "staging tables are TRUNCATEd (with RESTART IDENTITY) and reloaded;"
    " analytics dimensions and facts use INSERT ... ON CONFLICT DO NOTHING on"
    " natural keys, so reruns add nothing and counts are stable."
)


class LoaderError(Exception):
    """Fatal loader failure with the failing phase attached."""


def run(config_path: str | Path | None = None, *, powerbi_only: bool = False) -> dict[str, Any]:
    """Execute the full load pipeline and return the reconciliation summary."""

    started = time.perf_counter()
    config = load_config(config_path)
    dsn = _resolve_dsn(config)
    sql_dir = _repository_root() / "sql"
    summary: dict[str, Any] = {"rerun_strategy": RERUN_STRATEGY}

    import psycopg2

    try:
        conn = psycopg2.connect(dsn)
    except Exception as exc:
        raise LoaderError(
            "Cannot connect to PostgreSQL. Set DATABASE_URL or the "
            f"{config['database']['user_env']}/{config['database']['password_env']} "
            f"environment variables for {config['database']['host']}:"
            f"{config['database']['port']}/{config['database']['name']}: {exc}"
        ) from exc

    try:
        with conn:
            with conn.cursor() as cursor:
                _phase(cursor, "ddl", _run_sql_files, cursor, sql_dir)
                _phase(cursor, "staging", _load_staging, conn, cursor, config, powerbi_only)
                _phase(cursor, "dimensions", _load_dimensions, cursor, config)
                _phase(cursor, "facts", _load_facts, cursor, config, powerbi_only)
                _phase(cursor, "reconciliation", _reconcile, cursor, config, summary, powerbi_only)
                cursor.execute("SHOW server_version")
                summary["postgresql_version"] = cursor.fetchone()[0]
    except LoaderError:
        raise
    except Exception as exc:
        raise LoaderError(f"Load pipeline failed: {exc}") from exc
    finally:
        conn.close()

    summary["load_duration_seconds"] = round(time.perf_counter() - started, 1)
    summary["profile"] = "powerbi" if powerbi_only else "full_analytics"
    summary["excluded_sources"] = ["metropt3_readings"] if powerbi_only else []
    summary_path = _reports_path(config) / (
        "powerbi_db_load_summary.json" if powerbi_only else "db_load_summary.json"
    )
    _write_json(summary_path, summary)
    print(f"db_load_summary: {summary_path}")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    """Run the loader as a command-line program."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        run(args.config)
    except LoaderError as exc:
        print(f"Database load failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _phase(cursor: Any, name: str, func: Any, *args: Any) -> Any:
    try:
        result = func(*args)
    except Exception as exc:
        raise LoaderError(f"phase '{name}' failed: {exc}") from exc
    print(f"phase '{name}' complete")
    return result


def _resolve_dsn(config: Mapping[str, Any]) -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    database = config.get("database", {})
    user = os.environ.get(str(database.get("user_env", "")), "")
    password = os.environ.get(str(database.get("password_env", "")), "")
    if not user or not password:
        raise LoaderError(
            "Database credentials are unavailable. Set DATABASE_URL or both "
            f"{database.get('user_env')} and {database.get('password_env')}."
        )
    from psycopg2.extensions import make_dsn

    return make_dsn(
        host=os.environ.get("POSTGRES_HOST", database.get("host", "localhost")),
        port=os.environ.get("POSTGRES_PORT", database.get("port", 5432)),
        dbname=os.environ.get("POSTGRES_DB", database.get("name")),
        user=user, password=password,
    )


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_configured_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _repository_root() / path


def _reports_path(config: Mapping[str, Any]) -> Path:
    return _resolve_configured_path(config["paths"]["reports"])


def _run_sql_files(cursor: Any, sql_dir: Path) -> None:
    for name in SQL_FILES:
        cursor.execute((sql_dir / name).read_text(encoding="utf-8"))


def _load_staging(conn: Any, cursor: Any, config: Mapping[str, Any], powerbi_only: bool = False) -> None:
    for table in STAGING_TABLES:
        if powerbi_only and table == "staging.metropt3_readings":
            continue
        cursor.execute(f"TRUNCATE {table} RESTART IDENTITY")
    _copy_csv(conn, cursor, "staging.mes_production_hourly", _processed(config, "production_hourly", config["mes"]))
    _copy_csv(conn, cursor, "staging.mes_downtime_events", _processed(config, "downtime_events", config["mes"]))
    _copy_csv(conn, cursor, "staging.mes_work_orders", _processed(config, "work_orders", config["mes"]))
    _copy_csv(conn, cursor, "staging.mes_manpower_shifts", _processed(config, "manpower_shifts", config["mes"]))
    _copy_csv(conn, cursor, "staging.mes_station_operations", _processed(config, "station_operations", config["mes"]))
    _copy_csv(conn, cursor, "staging.mes_quality_events", _processed(config, "quality_events", config["mes"]))
    _copy_csv(conn, cursor, "staging.secom_cleaned", _processed(config, "cleaned_data", config["secom"]))
    if not powerbi_only:
        _copy_csv(conn, cursor, "staging.metropt3_readings", _processed(config, "processed_readings", config["metropt3"]))
    _copy_csv(conn, cursor, "staging.metropt3_failure_intervals", _processed(config, "failure_intervals", config["metropt3"]))
    _copy_csv(conn, cursor, "staging.metropt3_state_periods", _processed(config, "state_periods", config["metropt3"]))


def _processed(config: Mapping[str, Any], key: str, section: Mapping[str, Any]) -> Path:
    return _resolve_configured_path(section["outputs"][key])


def _copy_csv(conn: Any, cursor: Any, table: str, path: Path) -> None:
    if not path.is_file():
        raise LoaderError(f"source file for {table} is missing: {path}")
    schema, name = table.split(".")
    cursor.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = %s"
        " AND column_name <> 'stg_seq' ORDER BY ordinal_position",
        (schema, name),
    )
    columns = ", ".join(row[0] for row in cursor.fetchall())
    with _LoweredHeaderFile(path) as source:
        cursor.copy_expert(
            f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT CSV, HEADER)", source
        )


class _LoweredHeaderFile:
    """Binary file wrapper lowercasing only the CSV header line.

    PostgreSQL COPY matches header names case-sensitively while staging
    columns are lowercase by convention, so the header is lowered on the fly
    without rewriting multi-hundred-megabyte sources.
    """

    def __init__(self, path: Path) -> None:
        self._stream = open(path, "rb")
        self._pending = self._stream.readline().lower()

    def read(self, size: int = -1) -> bytes:
        if self._pending:
            if size is None or size < 0:
                data, self._pending = self._pending, b""
                return data + self._stream.read()
            chunk = self._pending[:size]
            self._pending = self._pending[size:]
            if len(chunk) < size:
                chunk += self._stream.read(size - len(chunk))
            return chunk
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> _LoweredHeaderFile:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _load_dimensions(cursor: Any, config: Mapping[str, Any]) -> None:
    mes = config["mes"]
    cursor.execute(
        """
        INSERT INTO analytics.dim_date
            (date_key, full_date, year, quarter, month, month_name, week, day,
             day_of_week, is_weekend)
        SELECT DISTINCT
            EXTRACT(YEAR FROM d)::int * 10000
                + EXTRACT(MONTH FROM d)::int * 100
                + EXTRACT(DAY FROM d)::int,
            d,
            EXTRACT(YEAR FROM d)::int,
            EXTRACT(QUARTER FROM d)::int,
            EXTRACT(MONTH FROM d)::int,
            RTRIM(TO_CHAR(d, 'Month')),
            EXTRACT(WEEK FROM d)::int,
            EXTRACT(DAY FROM d)::int,
            EXTRACT(ISODOW FROM d)::int,
            EXTRACT(ISODOW FROM d)::int IN (6, 7)
        FROM (
            SELECT date AS d FROM staging.mes_production_hourly
            UNION SELECT date FROM staging.mes_downtime_events
            UNION SELECT date FROM staging.mes_work_orders
            UNION SELECT date FROM staging.mes_manpower_shifts
            UNION SELECT date FROM staging.mes_station_operations
            UNION SELECT date FROM staging.mes_quality_events
            UNION SELECT timestamp::date FROM staging.secom_cleaned
            UNION SELECT timestamp::date FROM staging.metropt3_readings
        ) AS dates
        ON CONFLICT (date_key) DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.dim_line (line_code, line_name)
        SELECT DISTINCT line, line FROM staging.mes_production_hourly
        ON CONFLICT (line_code) DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.dim_station_machine
            (line_key, station_code, station_name, equipment_id,
             station_sequence, is_bottleneck)
        SELECT DISTINCT l.line_key, s.station, s.station_name, s.station,
            SUBSTRING(s.station FROM '-S([0-9]+)$')::int,
            s.is_bottleneck = 1
        FROM staging.mes_station_operations AS s
        JOIN analytics.dim_line AS l ON l.line_code = s.line
        ON CONFLICT (station_code) DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.dim_station_machine
            (line_key, station_code, station_name, equipment_id,
             station_sequence, is_bottleneck)
        VALUES (NULL, 'APU', 'Air Production Unit', 'APU-01', NULL, FALSE)
        ON CONFLICT (station_code) DO NOTHING
        """
    )
    products = {item["id"]: item for item in mes["products"]}
    cursor.executemany(
        """
        INSERT INTO analytics.dim_product
            (product_code, product_name, ideal_cycle_time_s, unit_scrap_cost,
             cost_source)
        VALUES (%s, %s, %s, %s, 'src/config.yaml mes.products')
        ON CONFLICT (product_code) DO NOTHING
        """,
        [
            (code, code, float(item["ideal_cycle_time_s"]), float(item["scrap_cost"]))
            for code, item in products.items()
        ],
    )
    sensors = _sensor_rows(config)
    cursor.executemany(
        """
        INSERT INTO analytics.dim_sensor
            (source_system, sensor_code, unit, sensor_type, is_critical)
        VALUES (%s, %s, %s, %s, NULL)
        ON CONFLICT (source_system, sensor_code) DO NOTHING
        """,
        sensors,
    )
    reasons = {
        item["reason"]: item for item in mes["downtime_reasons"]
    }
    for code, item in reasons.items():
        cursor.execute(
            """
            INSERT INTO analytics.dim_downtime_reason
                (reason_code, reason_name, is_planned, oee_bucket)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (reason_code) DO NOTHING
            """,
            (code, code, bool(item["planned"]), item["oee_bucket"]),
        )
    cursor.execute(
        """
        INSERT INTO analytics.dim_downtime_reason
            (reason_code, reason_name, is_planned, oee_bucket)
        SELECT DISTINCT s.reason, s.reason, FALSE, s.oee_bucket
        FROM staging.mes_downtime_events AS s
        WHERE NOT EXISTS (
            SELECT 1 FROM analytics.dim_downtime_reason AS r
            WHERE r.reason_code = s.reason
        )
        ON CONFLICT (reason_code) DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.dim_defect_cause
            (cause_code, cause_name, category, source_system)
        SELECT DISTINCT defect_cause, defect_cause, NULL, 'MES_SIM'
        FROM staging.mes_quality_events
        ON CONFLICT (cause_code) DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.dim_work_order
            (work_order_id, line_key, product_key, order_date, due_date,
             planned_qty)
        SELECT w.wo_id, l.line_key, p.product_key, w.date, w.due_date,
            w.planned_qty
        FROM staging.mes_work_orders AS w
        JOIN analytics.dim_line AS l ON l.line_code = w.line
        JOIN analytics.dim_product AS p ON p.product_code = w.product
        ON CONFLICT (work_order_id) DO NOTHING
        """
    )


def _sensor_rows(config: Mapping[str, Any]) -> list[tuple]:
    rows = []
    secom_path = _resolve_configured_path(config["secom"]["outputs"]["cleaned_data"])
    with secom_path.open("r", encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    for column in header:
        if column.startswith("sensor_"):
            rows.append(("SECOM", column, None, "analog"))
    for code, sensor_type, unit in METROPT_SIGNALS:
        rows.append(("METROPT3", code, unit, sensor_type))
    return rows


def _load_facts(cursor: Any, config: Mapping[str, Any], powerbi_only: bool = False) -> None:
    cursor.execute(
        """
        INSERT INTO analytics.fact_production_hourly
            (line_key, shift_key, date_key, product_key, hour_in_shift,
             hour_start, planned_time_min, run_time_min, ideal_cycle_time_s,
             actual_cycle_time_s, total_count, good_count, scrap_count)
        SELECT l.line_key, s.shift_key, d.date_key, p.product_key,
            h.hour_in_shift, h.hour_start, h.planned_time_min, h.run_time_min,
            h.ideal_cycle_time_s, h.actual_cycle_time_s, h.total_count,
            h.good_count, h.scrap_count
        FROM staging.mes_production_hourly AS h
        JOIN analytics.dim_line AS l ON l.line_code = h.line
        JOIN analytics.dim_time_shift AS s ON s.shift_code = h.shift
        JOIN analytics.dim_date AS d ON d.full_date = h.date
        JOIN analytics.dim_product AS p ON p.product_code = h.product
        ON CONFLICT DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.fact_downtime_event
            (event_id, line_key, station_machine_key, downtime_reason_key,
             shift_key, date_key, start_timestamp, end_timestamp, duration_min,
             supplier_tag)
        SELECT e.event_id, l.line_key, m.station_machine_key, r.downtime_reason_key,
            s.shift_key, d.date_key, e.start_timestamp, e.end_timestamp,
            e.duration_min, e.supplier_tag = 1
        FROM staging.mes_downtime_events AS e
        JOIN analytics.dim_line AS l ON l.line_code = e.line
        LEFT JOIN analytics.dim_station_machine AS m ON m.station_code = e.station
        JOIN analytics.dim_downtime_reason AS r ON r.reason_code = e.reason
        JOIN analytics.dim_time_shift AS s ON s.shift_code = e.shift
        JOIN analytics.dim_date AS d ON d.full_date = e.date
        ON CONFLICT DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.fact_quality_lot
            (source_system, source_row, lot_timestamp, target, target_label)
        SELECT 'SECOM', stg_seq, timestamp, target, target_label
        FROM staging.secom_cleaned
        ON CONFLICT DO NOTHING
        """
    )
    _load_secom_readings(cursor, config)
    if not powerbi_only:
        _load_metropt_readings(cursor, config)
    cursor.execute(
        """
        INSERT INTO analytics.fact_manpower_shift
            (line_key, shift_key, date_key, planned_headcount, actual_headcount)
        SELECT l.line_key, s.shift_key, d.date_key, m.planned_headcount,
            m.actual_headcount
        FROM staging.mes_manpower_shifts AS m
        JOIN analytics.dim_line AS l ON l.line_code = m.line
        JOIN analytics.dim_time_shift AS s ON s.shift_code = m.shift
        JOIN analytics.dim_date AS d ON d.full_date = m.date
        ON CONFLICT DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.fact_station_operation
            (line_key, station_machine_key, shift_key, date_key,
             processing_time_s, wait_time_s, throughput_units)
        SELECT l.line_key, m.station_machine_key, s.shift_key, d.date_key,
            o.processing_time_s, o.wait_time_s, o.throughput_units
        FROM staging.mes_station_operations AS o
        JOIN analytics.dim_line AS l ON l.line_code = o.line
        JOIN analytics.dim_station_machine AS m ON m.station_code = o.station
        JOIN analytics.dim_time_shift AS s ON s.shift_code = o.shift
        JOIN analytics.dim_date AS d ON d.full_date = o.date
        ON CONFLICT DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.fact_quality_scrap
            (date_key, line_key, product_key, defect_cause_key, units_affected,
             scrap_cost)
        SELECT d.date_key, l.line_key, p.product_key, c.defect_cause_key,
            q.units_affected, q.scrap_cost
        FROM staging.mes_quality_events AS q
        JOIN analytics.dim_date AS d ON d.full_date = q.date
        JOIN analytics.dim_line AS l ON l.line_code = q.line
        JOIN analytics.dim_product AS p ON p.product_code = q.product
        JOIN analytics.dim_defect_cause AS c ON c.cause_code = q.defect_cause
        ON CONFLICT DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.fact_equipment_state_period
            (source_system, equipment_ref, period_type, state_label, start_ts,
             end_ts, reading_count, duration_seconds)
        SELECT 'METROPT3', 'APU', 'operating_state', operating_state,
            start_timestamp, end_timestamp, row_count, duration_seconds
        FROM staging.metropt3_state_periods
        ON CONFLICT DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.fact_equipment_state_period
            (source_system, equipment_ref, period_type, state_label, start_ts,
             end_ts, reading_count, duration_seconds)
        SELECT 'METROPT3', 'APU', 'failure_window', kind, window_start,
            window_end, readings_in_window,
            EXTRACT(EPOCH FROM (window_end - window_start))
        FROM staging.metropt3_failure_intervals
        ON CONFLICT DO NOTHING
        """
    )
    prefailure_hours = float(config["metropt3"]["prefailure_hours"])
    cursor.execute(
        """
        INSERT INTO analytics.fact_equipment_state_period
            (source_system, equipment_ref, period_type, state_label, start_ts,
             end_ts, reading_count, duration_seconds)
        SELECT 'METROPT3', 'APU', 'prefailure_window', kind,
            window_start - (%s || ' hours')::interval, window_start,
            prefailure_readings, %s * 3600.0
        FROM staging.metropt3_failure_intervals
        ON CONFLICT DO NOTHING
        """,
        (prefailure_hours, prefailure_hours),
    )


def _load_secom_readings(cursor: Any, config: Mapping[str, Any]) -> None:
    secom_path = _resolve_configured_path(config["secom"]["outputs"]["cleaned_data"])
    with secom_path.open("r", encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    sensors = [column for column in header if column.startswith("sensor_")]
    values = ", ".join(f"('{code}', r.{code})" for code in sensors)
    cursor.execute(
        f"""
        INSERT INTO analytics.fact_sensor_reading
            (sensor_key, source_system, source_row, reading_ts, reading_value)
        SELECT d.sensor_key, 'SECOM', r.stg_seq, r.timestamp, v.reading_value
        FROM staging.secom_cleaned AS r
        CROSS JOIN LATERAL (VALUES {values}) AS v(code, reading_value)
        JOIN analytics.dim_sensor AS d
            ON d.source_system = 'SECOM' AND d.sensor_code = v.code
        WHERE v.reading_value IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def _load_metropt_readings(cursor: Any, config: Mapping[str, Any]) -> None:
    del config
    pairs = ", ".join(f"('{code}', r.{code})" for code, _, _ in METROPT_SIGNALS)
    cursor.execute(
        "SELECT MIN(source_index), MAX(source_index) FROM staging.metropt3_readings"
    )
    bounds = cursor.fetchone()
    if bounds[0] is None:
        return
    span = max(int(bounds[1]) - int(bounds[0]) + 1, 1)
    batch = max(span // 4, 1)
    lower = int(bounds[0])
    while lower <= int(bounds[1]):
        upper = min(lower + batch - 1, int(bounds[1]))
        cursor.execute(
            f"""
            INSERT INTO analytics.fact_sensor_reading
                (sensor_key, source_system, source_row, reading_ts,
                 reading_value)
            SELECT d.sensor_key, 'METROPT3', r.source_index, r.timestamp,
                v.reading_value
            FROM staging.metropt3_readings AS r
            CROSS JOIN LATERAL (VALUES {pairs}) AS v(code, reading_value)
            JOIN analytics.dim_sensor AS d
                ON d.source_system = 'METROPT3' AND d.sensor_code = v.code
            WHERE r.source_index BETWEEN %s AND %s
                AND v.reading_value IS NOT NULL
            ON CONFLICT DO NOTHING
            """,
            (lower, upper),
        )
        print(f"metropt readings batch source_index {lower}-{upper} complete")
        lower = upper + 1


def _reconcile(cursor: Any, config: Mapping[str, Any], summary: dict[str, Any], powerbi_only: bool = False) -> None:
    staging_counts = {table: _count(cursor, table) for table in STAGING_TABLES}
    dimension_counts = {
        table: _count(cursor, f"analytics.{table}")
        for table in (
            "dim_date",
            "dim_time_shift",
            "dim_line",
            "dim_station_machine",
            "dim_product",
            "dim_sensor",
            "dim_downtime_reason",
            "dim_defect_cause",
            "dim_work_order",
        )
    }
    fact_counts = {
        table: _count(cursor, f"analytics.{table}")
        for table in (
            "fact_production_hourly",
            "fact_downtime_event",
            "fact_quality_lot",
            "fact_sensor_reading",
            "fact_manpower_shift",
            "fact_station_operation",
            "fact_quality_scrap",
            "fact_equipment_state_period",
            "fact_spc_alert",
        )
    }
    source_counts = _source_counts(config, powerbi_only)
    cursor.execute(
        "SELECT source_system, COUNT(*) FROM analytics.fact_sensor_reading"
        " GROUP BY source_system"
    )
    sensor_by_system = {row[0]: int(row[1]) for row in cursor.fetchall()}
    unresolved = {
        "production_bad_line": _orphans(
            cursor, "fact_production_hourly", "line_key", "dim_line", "line_key"
        ),
        "downtime_bad_reason": _orphans(
            cursor,
            "fact_downtime_event",
            "downtime_reason_key",
            "dim_downtime_reason",
            "downtime_reason_key",
        ),
        "reading_bad_sensor": _orphans(
            cursor, "fact_sensor_reading", "sensor_key", "dim_sensor", "sensor_key"
        ),
    }
    reconciliation = {
        "mes_production": {
            "source": source_counts["mes_production_hourly"],
            "staging": staging_counts["staging.mes_production_hourly"],
            "fact": fact_counts["fact_production_hourly"],
        },
        "mes_downtime": {
            "source": source_counts["mes_downtime_events"],
            "staging": staging_counts["staging.mes_downtime_events"],
            "fact": fact_counts["fact_downtime_event"],
        },
        "mes_work_orders": {
            "source": source_counts["mes_work_orders"],
            "staging": staging_counts["staging.mes_work_orders"],
            "fact_dim_work_order": dimension_counts["dim_work_order"],
        },
        "mes_manpower": {
            "source": source_counts["mes_manpower_shifts"],
            "staging": staging_counts["staging.mes_manpower_shifts"],
            "fact": fact_counts["fact_manpower_shift"],
        },
        "mes_station_operations": {
            "source": source_counts["mes_station_operations"],
            "staging": staging_counts["staging.mes_station_operations"],
            "fact": fact_counts["fact_station_operation"],
        },
        "mes_quality_events": {
            "source": source_counts["mes_quality_events"],
            "staging": staging_counts["staging.mes_quality_events"],
            "fact": fact_counts["fact_quality_scrap"],
        },
        "secom_lots": {
            "source": source_counts["secom_cleaned"],
            "staging": staging_counts["staging.secom_cleaned"],
            "fact": fact_counts["fact_quality_lot"],
        },
        "secom_readings_non_null_source": source_counts["secom_non_null_readings"],
        "secom_readings_fact": sensor_by_system.get("SECOM", 0),
        "metropt3_rows": {
            "source": source_counts["metropt3_readings"],
            "staging": staging_counts["staging.metropt3_readings"],
        },
        "metropt3_readings_expected": source_counts["metropt3_readings"] * len(METROPT_SIGNALS),
        "metropt3_readings_fact": sensor_by_system.get("METROPT3", 0),
        "metropt3_state_periods": {
            "artifact": source_counts["metropt3_state_periods"],
            "staging": staging_counts["staging.metropt3_state_periods"],
        },
        "metropt3_failure_intervals": {
            "artifact": source_counts["metropt3_failure_intervals"],
            "staging": staging_counts["staging.metropt3_failure_intervals"],
        },
        "equipment_periods_fact": fact_counts["fact_equipment_state_period"],
    }
    for name, triple in reconciliation.items():
        if isinstance(triple, dict) and {"source", "staging", "fact"} <= set(triple):
            if not triple["source"] == triple["staging"] == triple["fact"]:
                raise LoaderError(f"reconciliation mismatch in {name}: {triple}")
    work_orders = reconciliation["mes_work_orders"]
    if not work_orders["source"] == work_orders["staging"] == work_orders["fact_dim_work_order"]:
        raise LoaderError(f"reconciliation mismatch in mes_work_orders: {work_orders}")
    if reconciliation["secom_readings_non_null_source"] != reconciliation["secom_readings_fact"]:
        raise LoaderError(
            "SECOM readings mismatch: "
            f"{reconciliation['secom_readings_non_null_source']} != "
            f"{reconciliation['secom_readings_fact']}"
        )
    if not powerbi_only and reconciliation["metropt3_readings_expected"] != reconciliation["metropt3_readings_fact"]:
        raise LoaderError(
            "MetroPT-3 readings mismatch: "
            f"{reconciliation['metropt3_readings_expected']} != "
            f"{reconciliation['metropt3_readings_fact']}"
        )
    expected_periods = (
        reconciliation["metropt3_state_periods"]["staging"]
        + 2 * reconciliation["metropt3_failure_intervals"]["staging"]
    )
    if reconciliation["equipment_periods_fact"] != expected_periods:
        raise LoaderError(
            "equipment period mismatch: "
            f"{reconciliation['equipment_periods_fact']} != {expected_periods}"
        )
    if any(unresolved.values()):
        raise LoaderError(f"unresolved foreign keys: {unresolved}")
    if not powerbi_only and fact_counts["fact_spc_alert"] != 0:
        raise LoaderError("fact_spc_alert must remain empty in P2-003")
    if powerbi_only:
        for key in ("metropt3_rows", "metropt3_readings_expected", "metropt3_readings_fact"):
            reconciliation.pop(key)
    summary.update(
        {
            "staging_counts": staging_counts,
            "dimension_counts": dimension_counts,
            "fact_counts": fact_counts,
            "sensor_readings_by_system": sensor_by_system,
            "unresolved_fk_counts": unresolved,
            "rejected_rows": 0,
            "reconciliation": reconciliation,
        }
    )


def _orphans(
    cursor: Any, fact: str, fact_key: str, dim: str, dim_key: str
) -> int:
    cursor.execute(
        f"SELECT COUNT(*) FROM analytics.{fact} AS f"
        f" LEFT JOIN analytics.{dim} AS d ON d.{dim_key} = f.{fact_key}"
        f" WHERE f.{fact_key} IS NOT NULL AND d.{dim_key} IS NULL"
    )
    return int(cursor.fetchone()[0])


def _count(cursor: Any, table: str) -> int:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    return int(cursor.fetchone()[0])


def _source_counts(config: Mapping[str, Any], powerbi_only: bool = False) -> dict[str, int]:
    mes = config["mes"]
    counts = {}
    for key in (
        "production_hourly",
        "downtime_events",
        "work_orders",
        "manpower_shifts",
        "station_operations",
        "quality_events",
    ):
        counts[f"mes_{key}"] = _csv_rows(_resolve_configured_path(mes["outputs"][key]))
    counts["secom_cleaned"] = _csv_rows(
        _resolve_configured_path(config["secom"]["outputs"]["cleaned_data"])
    )
    counts["secom_non_null_readings"] = _secom_non_null_count(config)
    counts["metropt3_readings"] = 0 if powerbi_only else _csv_rows(
        _resolve_configured_path(config["metropt3"]["outputs"]["processed_readings"])
    )
    counts["metropt3_failure_intervals"] = _csv_rows(
        _resolve_configured_path(config["metropt3"]["outputs"]["failure_intervals"])
    )
    counts["metropt3_state_periods"] = _csv_rows(
        _resolve_configured_path(config["metropt3"]["outputs"]["state_periods"])
    )
    return counts


def _csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return sum(1 for _ in handle) - 1


def _secom_non_null_count(config: Mapping[str, Any]) -> int:
    path = _resolve_configured_path(config["secom"]["outputs"]["cleaned_data"])
    total = 0
    for chunk in pd.read_csv(path, chunksize=500):
        sensors = [column for column in chunk.columns if column.startswith("sensor_")]
        total += int(chunk[sensors].notna().sum().sum())
    return total


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output_file:
        json.dump(payload, output_file, indent=2, sort_keys=True, ensure_ascii=False)
        output_file.write("\n")


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
