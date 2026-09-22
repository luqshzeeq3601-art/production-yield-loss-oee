import re
from pathlib import Path

import pytest

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"

EXPECTED_TABLES = {
    "staging": {
        "secom_cleaned",
        "metropt3_readings",
        "metropt3_failure_intervals",
        "metropt3_state_periods",
        "mes_production_hourly",
        "mes_downtime_events",
        "mes_work_orders",
        "mes_manpower_shifts",
        "mes_station_operations",
        "mes_quality_events",
    },
    "analytics": {
        "dim_date",
        "dim_time_shift",
        "dim_line",
        "dim_station_machine",
        "dim_product",
        "dim_sensor",
        "dim_downtime_reason",
        "dim_defect_cause",
        "dim_work_order",
        "fact_production_hourly",
        "fact_downtime_event",
        "fact_quality_lot",
        "fact_sensor_reading",
        "fact_spc_alert",
        "fact_manpower_shift",
        "fact_station_operation",
        "fact_quality_scrap",
        "fact_equipment_state_period",
    },
}

STAGING_SOURCES = {
    "staging.secom_cleaned": "secom_cleaned.csv",
    "staging.metropt3_readings": "metropt3_readings.csv",
    "staging.metropt3_failure_intervals": "metropt3_failure_intervals.csv",
    "staging.metropt3_state_periods": "metropt3_state_periods.csv",
    "staging.mes_production_hourly": "mes_production_hourly.csv",
    "staging.mes_downtime_events": "mes_downtime_events.csv",
    "staging.mes_work_orders": "mes_work_orders.csv",
    "staging.mes_manpower_shifts": "mes_manpower_shifts.csv",
    "staging.mes_station_operations": "mes_station_operations.csv",
    "staging.mes_quality_events": "mes_quality_events.csv",
}

DIMENSION_TABLES = {
    "analytics.dim_date",
    "analytics.dim_time_shift",
    "analytics.dim_line",
    "analytics.dim_station_machine",
    "analytics.dim_product",
    "analytics.dim_sensor",
    "analytics.dim_downtime_reason",
    "analytics.dim_defect_cause",
    "analytics.dim_work_order",
}

FACT_TABLES = {
    "analytics.fact_production_hourly",
    "analytics.fact_downtime_event",
    "analytics.fact_quality_lot",
    "analytics.fact_sensor_reading",
    "analytics.fact_spc_alert",
    "analytics.fact_manpower_shift",
    "analytics.fact_station_operation",
    "analytics.fact_quality_scrap",
    "analytics.fact_equipment_state_period",
}

try:
    import pgserver  # noqa: F401

    _HAS_PGSERVER = True
except ImportError:
    _HAS_PGSERVER = False


def _read_sql(name):
    return (SQL_DIR / name).read_text(encoding="utf-8")


def _all_sql():
    return "\n".join(_read_sql(name) for name in ("01_schema.sql", "02_staging.sql", "03_dims.sql", "04_facts.sql"))


def _create_statements():
    tables = {}
    for name in ("02_staging.sql", "03_dims.sql", "04_facts.sql"):
        for statement in _read_sql(name).split(";"):
            match = re.search(
                r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)\.(\w+)", statement
            )
            if match:
                tables[f"{match.group(1)}.{match.group(2)}"] = statement
    return tables


def _columns(statement):
    columns = []
    for line in statement.splitlines():
        match = re.match(r"\s{4}(\w+)\b", line)
        if match and match.group(1).upper() not in {
            "CONSTRAINT",
            "PRIMARY",
            "FOREIGN",
            "UNIQUE",
            "CHECK",
        }:
            columns.append(match.group(1).lower())
    return columns


def _csv_header(filename):
    with (DATA_DIR / filename).open("r", encoding="utf-8-sig", newline="") as handle:
        for line in handle:
            return [column.strip().lower() for column in line.rstrip("\n").split(",")]
    raise AssertionError(f"empty source file: {filename}")


# ---------- static tests ----------


def test_sql_files_exist():
    for name in ("01_schema.sql", "02_staging.sql", "03_dims.sql", "04_facts.sql"):
        assert (SQL_DIR / name).is_file()


def test_schemas_declared():
    text = _read_sql("01_schema.sql")
    assert "CREATE SCHEMA IF NOT EXISTS staging" in text
    assert "CREATE SCHEMA IF NOT EXISTS analytics" in text


def test_required_tables_declared():
    tables = _create_statements()
    for schema, names in EXPECTED_TABLES.items():
        for name in names:
            assert f"{schema}.{name}" in tables, f"missing table {schema}.{name}"


def test_dimensions_have_primary_keys():
    tables = _create_statements()
    for table in DIMENSION_TABLES:
        assert "PRIMARY KEY" in tables[table], f"no PK in {table}"


def test_facts_have_documented_grains():
    text = _all_sql()
    for table in FACT_TABLES:
        short = table.split(".")[1]
        pattern = re.compile(
            r"GRAIN:[^\n]*\n(?:--[^\n]*\n)*CREATE TABLE [^\n]*" + re.escape(short),
        )
        assert pattern.search(text), f"no GRAIN comment on {table}"


def test_expected_foreign_keys():
    tables = _create_statements()
    expectations = {
        "analytics.fact_production_hourly": [
            "analytics.dim_line",
            "analytics.dim_time_shift",
            "analytics.dim_date",
            "analytics.dim_product",
        ],
        "analytics.fact_downtime_event": [
            "analytics.dim_line",
            "analytics.dim_station_machine",
            "analytics.dim_downtime_reason",
        ],
        "analytics.fact_sensor_reading": ["analytics.dim_sensor"],
        "analytics.fact_spc_alert": ["analytics.dim_sensor"],
        "analytics.fact_manpower_shift": [
            "analytics.dim_line",
            "analytics.dim_time_shift",
            "analytics.dim_date",
        ],
        "analytics.fact_station_operation": [
            "analytics.dim_line",
            "analytics.dim_station_machine",
        ],
        "analytics.fact_quality_scrap": [
            "analytics.dim_date",
            "analytics.dim_line",
            "analytics.dim_product",
            "analytics.dim_defect_cause",
        ],
        "analytics.dim_work_order": ["analytics.dim_line", "analytics.dim_product"],
        "analytics.dim_station_machine": ["analytics.dim_line"],
    }
    for table, targets in expectations.items():
        for target in targets:
            assert f"REFERENCES {target}" in tables[table], f"{table} missing FK to {target}"


def test_required_check_constraints():
    tables = _create_statements()
    expectations = {
        "analytics.fact_production_hourly": [
            "good_count <= total_count",
            "run_time_min <= planned_time_min",
        ],
        "analytics.fact_downtime_event": ["end_timestamp >= start_timestamp"],
        "analytics.fact_quality_lot": ["target IN (0, 1)"],
        "analytics.fact_manpower_shift": ["actual_headcount <= planned_headcount"],
        "analytics.fact_equipment_state_period": ["end_ts >= start_ts"],
        "analytics.dim_sensor": ["source_system IN ('SECOM', 'METROPT3')"],
        "analytics.dim_downtime_reason": ["oee_bucket IN ("],
    }
    for table, fragments in expectations.items():
        for fragment in fragments:
            assert fragment in tables[table], f"{table} missing CHECK {fragment}"


def test_production_fact_stores_components_not_oee():
    columns = _columns(_create_statements()["analytics.fact_production_hourly"])
    for derived in ("availability", "performance", "quality", "oee"):
        assert derived not in columns, f"derived KPI stored: {derived}"
    for component in (
        "planned_time_min",
        "run_time_min",
        "ideal_cycle_time_s",
        "total_count",
        "good_count",
        "scrap_count",
    ):
        assert component in columns, f"missing component: {component}"


def test_no_invented_limits():
    tables = _create_statements()
    for table, statement in tables.items():
        for column in _columns(statement):
            assert column not in {"usl", "lsl"}, f"invented limit column in {table}"


def test_staging_covers_actual_sources():
    tables = _create_statements()
    for table, filename in STAGING_SOURCES.items():
        staged = set(_columns(tables[table]))
        source = set(_csv_header(filename))
        assert source.issubset(staged), f"{table} missing columns: {sorted(source - staged)}"


# ---------- live tests (ephemeral PostgreSQL 16) ----------


@pytest.fixture(scope="module")
def live_db():
    pgserver = pytest.importorskip("pgserver")
    import tempfile

    import psycopg2

    server = pgserver.get_server(tempfile.mkdtemp(prefix="p2_002_"))
    conn = psycopg2.connect(server.get_uri())
    conn.autocommit = True
    cursor = conn.cursor()
    for name in ("01_schema.sql", "02_staging.sql", "03_dims.sql", "04_facts.sql"):
        cursor.execute(_read_sql(name))
    yield conn
    conn.close()
    server.cleanup()


@pytest.fixture(scope="module")
def live_keys(live_db):
    cursor = live_db.cursor()
    cursor.execute(
        "INSERT INTO analytics.dim_date (date_key, full_date, year, quarter, month,"
        " month_name, week, day, day_of_week, is_weekend)"
        " VALUES (20240101, DATE '2024-01-01', 2024, 1, 1, 'January', 1, 1, 1, FALSE)"
    )
    cursor.execute(
        "INSERT INTO analytics.dim_line (line_code, line_name)"
        " VALUES ('L1', 'Line 1') RETURNING line_key"
    )
    line_key = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO analytics.dim_product (product_code, product_name,"
        " ideal_cycle_time_s, unit_scrap_cost, cost_source)"
        " VALUES ('P1', 'Product 1', 40.0, 12.0, 'src/config.yaml')"
        " RETURNING product_key"
    )
    product_key = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO analytics.dim_station_machine (line_key, station_code,"
        " station_name, equipment_id, station_sequence, is_bottleneck)"
        " VALUES (%s, 'L1-S1', 'Loading', 'L1-S1', 1, FALSE)"
        " RETURNING station_machine_key",
        (line_key,),
    )
    station_key = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO analytics.dim_sensor (source_system, sensor_code, unit,"
        " sensor_type, is_critical)"
        " VALUES ('SECOM', 'sensor_021', NULL, 'analog', NULL)"
        " RETURNING sensor_key"
    )
    sensor_key = cursor.fetchone()[0]
    cursor.execute("SELECT shift_key FROM analytics.dim_time_shift WHERE shift_code = 'A'")
    shift_key = cursor.fetchone()[0]
    cursor.execute(
        "SELECT downtime_reason_key FROM analytics.dim_downtime_reason"
        " WHERE reason_code = 'breakdown'"
    )
    reason_key = cursor.fetchone()[0]
    cursor.execute(
        "SELECT defect_cause_key FROM analytics.dim_defect_cause WHERE cause_code = 'tool wear'"
    )
    cause_key = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO analytics.dim_work_order (work_order_id, line_key, product_key,"
        " order_date, due_date, planned_qty)"
        " VALUES ('WO-TEST-1', %s, %s, DATE '2024-01-01', DATE '2024-01-03', 100)"
        " RETURNING work_order_key",
        (line_key, product_key),
    )
    work_order_key = cursor.fetchone()[0]
    return {
        "line_key": line_key,
        "product_key": product_key,
        "station_key": station_key,
        "sensor_key": sensor_key,
        "shift_key": shift_key,
        "reason_key": reason_key,
        "cause_key": cause_key,
        "work_order_key": work_order_key,
    }


def test_live_ddl_tables_present(live_db):
    cursor = live_db.cursor()
    cursor.execute(
        "SELECT table_schema || '.' || table_name FROM information_schema.tables"
        " WHERE table_schema IN ('staging', 'analytics') AND table_type = 'BASE TABLE'"
    )
    present = {row[0] for row in cursor.fetchall()}
    for schema, names in EXPECTED_TABLES.items():
        for name in names:
            assert f"{schema}.{name}" in present, f"missing live table {schema}.{name}"


def test_live_reference_seeds(live_db):
    cursor = live_db.cursor()
    cursor.execute("SELECT count(*) FROM analytics.dim_time_shift")
    assert cursor.fetchone()[0] == 3
    cursor.execute("SELECT count(*) FROM analytics.dim_downtime_reason")
    assert cursor.fetchone()[0] == 6
    cursor.execute(
        "SELECT count(*) FROM analytics.dim_downtime_reason WHERE oee_bucket = 'Planned'"
    )
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT count(*) FROM analytics.dim_defect_cause")
    assert cursor.fetchone()[0] == 6


def test_live_valid_fixtures_load(live_db, live_keys):
    cursor = live_db.cursor()
    cursor.execute(
        "INSERT INTO analytics.fact_production_hourly (line_key, shift_key, date_key,"
        " product_key, hour_in_shift, hour_start, planned_time_min, run_time_min,"
        " ideal_cycle_time_s, actual_cycle_time_s, total_count, good_count, scrap_count)"
        " VALUES (%s, %s, 20240101, %s, 0, TIMESTAMP '2024-01-01 06:00', 60, 55, 40, 42, 78, 76, 2)",
        (live_keys["line_key"], live_keys["shift_key"], live_keys["product_key"]),
    )
    cursor.execute(
        "INSERT INTO analytics.fact_downtime_event (event_id, line_key,"
        " station_machine_key, downtime_reason_key, shift_key, date_key,"
        " start_timestamp, end_timestamp, duration_min, supplier_tag)"
        " VALUES ('EV-000001', %s, %s, %s, %s, 20240101,"
        " TIMESTAMP '2024-01-01 07:00', TIMESTAMP '2024-01-01 07:20', 20, FALSE)",
        (
            live_keys["line_key"],
            live_keys["station_key"],
            live_keys["reason_key"],
            live_keys["shift_key"],
        ),
    )
    cursor.execute(
        "INSERT INTO analytics.fact_quality_lot (source_system, source_row,"
        " lot_timestamp, target, target_label)"
        " VALUES ('SECOM', 1, TIMESTAMP '2008-07-19 11:55', 0, 'pass')"
    )
    cursor.execute(
        "INSERT INTO analytics.fact_sensor_reading (sensor_key, source_system,"
        " source_row, reading_ts, reading_value)"
        " VALUES (%s, 'SECOM', 1, TIMESTAMP '2008-07-19 11:55', 0.5)",
        (live_keys["sensor_key"],),
    )
    cursor.execute(
        "INSERT INTO analytics.fact_spc_alert (alert_ts, sensor_key, source_system,"
        " source_row, rule_code, method, severity)"
        " VALUES (TIMESTAMP '2008-07-19 11:55', %s, 'SECOM', 1, 'WE1', 'I-MR', 'warning')",
        (live_keys["sensor_key"],),
    )
    cursor.execute(
        "INSERT INTO analytics.fact_manpower_shift (line_key, shift_key, date_key,"
        " planned_headcount, actual_headcount)"
        " VALUES (%s, %s, 20240101, 6, 5)",
        (live_keys["line_key"], live_keys["shift_key"]),
    )
    cursor.execute(
        "INSERT INTO analytics.fact_station_operation (line_key, station_machine_key,"
        " shift_key, date_key, processing_time_s, wait_time_s, throughput_units)"
        " VALUES (%s, %s, %s, 20240101, 25.0, 30.0, 500)",
        (live_keys["line_key"], live_keys["station_key"], live_keys["shift_key"]),
    )
    cursor.execute(
        "INSERT INTO analytics.fact_quality_scrap (date_key, line_key, product_key,"
        " defect_cause_key, units_affected, scrap_cost)"
        " VALUES (20240101, %s, %s, %s, 10, 120.0)",
        (live_keys["line_key"], live_keys["product_key"], live_keys["cause_key"]),
    )
    cursor.execute(
        "INSERT INTO analytics.fact_equipment_state_period (source_system, equipment_ref,"
        " period_type, state_label, start_ts, end_ts, reading_count, duration_seconds)"
        " VALUES ('METROPT3', 'APU', 'failure_window', 'Air leak',"
        " TIMESTAMP '2020-04-18 00:00', TIMESTAMP '2020-04-18 23:59', 8663, 86340)"
    )


def test_live_constraints_reject_invalid(live_db, live_keys):
    import psycopg2

    cursor = live_db.cursor()
    bad_rows = [
        (
            "INSERT INTO analytics.fact_production_hourly (line_key, shift_key, date_key,"
            " product_key, hour_in_shift, hour_start, planned_time_min, run_time_min,"
            " ideal_cycle_time_s, actual_cycle_time_s, total_count, good_count, scrap_count)"
            " VALUES (%s, %s, 20240101, %s, 1, TIMESTAMP '2024-01-01 07:00', 60, 55, 40, 42, 10, 11, 0)",
            "good_count above total_count",
        ),
        (
            "INSERT INTO analytics.fact_production_hourly (line_key, shift_key, date_key,"
            " product_key, hour_in_shift, hour_start, planned_time_min, run_time_min,"
            " ideal_cycle_time_s, actual_cycle_time_s, total_count, good_count, scrap_count)"
            " VALUES (%s, %s, 20240101, %s, 2, TIMESTAMP '2024-01-01 08:00', 60, 61, 40, 42, 10, 10, 0)",
            "run_time above planned_time",
        ),
        (
            "INSERT INTO analytics.fact_production_hourly (line_key, shift_key, date_key,"
            " product_key, hour_in_shift, hour_start, planned_time_min, run_time_min,"
            " ideal_cycle_time_s, actual_cycle_time_s, total_count, good_count, scrap_count)"
            " VALUES (9999, %s, 20240101, %s, 3, TIMESTAMP '2024-01-01 09:00', 60, 55, 40, 42, 10, 10, 0)",
            "unknown line foreign key",
        ),
        (
            "INSERT INTO analytics.fact_downtime_event (event_id, line_key,"
            " downtime_reason_key, shift_key, date_key, start_timestamp, end_timestamp,"
            " duration_min, supplier_tag)"
            " VALUES ('EV-000002', %s, %s, %s, 20240101,"
            " TIMESTAMP '2024-01-01 08:20', TIMESTAMP '2024-01-01 08:00', 20, FALSE)",
            "end before start",
        ),
        (
            "INSERT INTO analytics.fact_downtime_event (event_id, line_key,"
            " downtime_reason_key, shift_key, date_key, start_timestamp, end_timestamp,"
            " duration_min, supplier_tag)"
            " VALUES ('EV-000001', %s, %s, %s, 20240101,"
            " TIMESTAMP '2024-01-01 09:00', TIMESTAMP '2024-01-01 09:20', 20, FALSE)",
            "duplicate event natural key",
        ),
        (
            "INSERT INTO analytics.fact_quality_lot (source_system, source_row,"
            " lot_timestamp, target, target_label)"
            " VALUES ('SECOM', 1, TIMESTAMP '2008-07-19 11:55', 0, 'pass')",
            "duplicate lot natural key",
        ),
        (
            "INSERT INTO analytics.fact_manpower_shift (line_key, shift_key, date_key,"
            " planned_headcount, actual_headcount)"
            " VALUES (%s, %s, 20240101, 6, 7)",
            "actual headcount above planned",
        ),
        (
            "INSERT INTO analytics.fact_sensor_reading (sensor_key, source_system,"
            " source_row, reading_ts, reading_value)"
            " VALUES (9999, 'SECOM', 2, TIMESTAMP '2008-07-19 11:55', 0.5)",
            "unknown sensor foreign key",
        ),
    ]
    params = {
        "good_count above total_count": (
            live_keys["line_key"],
            live_keys["shift_key"],
            live_keys["product_key"],
        ),
        "run_time above planned_time": (
            live_keys["line_key"],
            live_keys["shift_key"],
            live_keys["product_key"],
        ),
        "unknown line foreign key": (live_keys["shift_key"], live_keys["product_key"]),
        "end before start": (
            live_keys["line_key"],
            live_keys["reason_key"],
            live_keys["shift_key"],
        ),
        "duplicate event natural key": (
            live_keys["line_key"],
            live_keys["reason_key"],
            live_keys["shift_key"],
        ),
        "duplicate lot natural key": (),
        "actual headcount above planned": (live_keys["line_key"], live_keys["shift_key"]),
        "unknown sensor foreign key": (),
    }
    for statement, label in bad_rows:
        try:
            cursor.execute(statement, params[label] or None)
        except psycopg2.Error:
            live_db.rollback()
        else:
            live_db.rollback()
            pytest.fail(f"constraint case accepted invalid row: {label}")
