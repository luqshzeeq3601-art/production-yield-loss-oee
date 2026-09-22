import os
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = REPO_ROOT / "sql"


def _read_sql(name):
    return (SQL_DIR / name).read_text(encoding="utf-8")


def _run_dq(cursor):
    cursor.execute(_read_sql("06_dq_checks.sql"))
    return {row[0]: (row[5], int(row[4])) for row in cursor.fetchall()}


@pytest.fixture(scope="module")
def dq_conn():
    pgserver = pytest.importorskip("pgserver")
    import tempfile

    import psycopg2

    server = pgserver.get_server(str(tempfile.mkdtemp(prefix="dq_")))
    conn = psycopg2.connect(server.get_uri())
    cursor = conn.cursor()
    for name in ("01_schema.sql", "02_staging.sql", "03_dims.sql", "04_facts.sql"):
        cursor.execute(_read_sql(name))
    cursor.execute(_SETUP_SQL)
    conn.commit()
    yield conn
    conn.close()
    server.cleanup()


def test_positive_all_checks_pass(dq_conn):
    results = _run_dq(dq_conn.cursor())
    assert len(results) == _read_sql("06_dq_checks.sql").count("UNION ALL SELECT") + 1
    failures = {key: value for key, value in results.items() if value[0] != "PASS"}
    assert failures == {}


def _assert_rejected(dq_conn, sql, params=()):
    import psycopg2

    cursor = dq_conn.cursor()
    cursor.execute("SAVEPOINT t")
    try:
        with pytest.raises(psycopg2.Error):
            cursor.execute(sql, params)
    finally:
        cursor.execute("ROLLBACK TO SAVEPOINT t")


def test_constraints_reject_invalid(dq_conn):
    cursor = dq_conn.cursor()
    cursor.execute("SELECT line_key FROM analytics.dim_line WHERE line_code = 'L1'")
    line_key = cursor.fetchone()[0]
    _assert_rejected(
        dq_conn,
        "INSERT INTO analytics.fact_production_hourly (line_key, shift_key, date_key,"
        " product_key, hour_in_shift, hour_start, planned_time_min, run_time_min,"
        " ideal_cycle_time_s, actual_cycle_time_s, total_count, good_count, scrap_count)"
        " SELECT %s, shift_key, date_key, product_key, 5, TIMESTAMP '2024-01-01 11:00',"
        " 60, 55, 40, 42, 10, 11, 0 FROM analytics.fact_production_hourly LIMIT 1",
        (line_key,),
    )
    _assert_rejected(
        dq_conn,
        "INSERT INTO analytics.fact_production_hourly (line_key, shift_key, date_key,"
        " product_key, hour_in_shift, hour_start, planned_time_min, run_time_min,"
        " ideal_cycle_time_s, actual_cycle_time_s, total_count, good_count, scrap_count)"
        " SELECT %s, shift_key, date_key, product_key, 6, TIMESTAMP '2024-01-01 12:00',"
        " 60, 61, 40, 42, 10, 10, 0 FROM analytics.fact_production_hourly LIMIT 1",
        (line_key,),
    )
    _assert_rejected(
        dq_conn,
        "INSERT INTO analytics.fact_production_hourly (line_key, shift_key, date_key,"
        " product_key, hour_in_shift, hour_start, planned_time_min, run_time_min,"
        " ideal_cycle_time_s, actual_cycle_time_s, total_count, good_count, scrap_count)"
        " VALUES (9999, 1, 20240101, 1, 7, TIMESTAMP '2024-01-01 13:00', 60, 55, 40, 42, 10, 10, 0)",
    )
    _assert_rejected(
        dq_conn,
        "INSERT INTO analytics.fact_downtime_event (event_id, line_key,"
        " downtime_reason_key, shift_key, date_key, start_timestamp, end_timestamp,"
        " duration_min, supplier_tag) VALUES ('EV-BAD-1', 1, 1, 1, 20240101,"
        " TIMESTAMP '2024-01-01 08:20', TIMESTAMP '2024-01-01 08:00', 20, FALSE)",
    )
    _assert_rejected(
        dq_conn,
        "INSERT INTO analytics.fact_downtime_event (event_id, line_key,"
        " downtime_reason_key, shift_key, date_key, start_timestamp, end_timestamp,"
        " duration_min, supplier_tag) VALUES ('EV-1', 1, 1, 1, 20240101,"
        " TIMESTAMP '2024-01-01 09:00', TIMESTAMP '2024-01-01 09:20', 20, FALSE)",
    )
    _assert_rejected(
        dq_conn,
        "INSERT INTO analytics.fact_quality_lot (source_system, source_row,"
        " lot_timestamp, target, target_label)"
        " VALUES ('SECOM', 99, TIMESTAMP '2008-07-21 12:00', 2, 'fail')",
    )
    _assert_rejected(
        dq_conn,
        "INSERT INTO analytics.fact_manpower_shift (line_key, shift_key, date_key,"
        " planned_headcount, actual_headcount) VALUES (1, 1, 20240101, 6, 7)",
    )


def _assert_dq_fails(dq_conn, setup_sql, check_id):
    cursor = dq_conn.cursor()
    cursor.execute("SAVEPOINT t")
    try:
        cursor.execute(setup_sql)
        results = _run_dq(cursor)
        assert results[check_id][0] == "FAIL", f"{check_id} did not fail"
        assert results[check_id][1] > 0
    finally:
        cursor.execute("ROLLBACK TO SAVEPOINT t")


def test_dq_catches_station_line_mismatch(dq_conn):
    _assert_dq_fails(
        dq_conn,
        "INSERT INTO analytics.fact_station_operation (line_key, station_machine_key,"
        " shift_key, date_key, processing_time_s, wait_time_s, throughput_units)"
        " SELECT (SELECT line_key FROM analytics.dim_line WHERE line_code = 'L2'),"
        " station_machine_key, shift_key, date_key, 25.0, 10.0, 78"
        " FROM analytics.fact_station_operation LIMIT 1",
        "DQ-F02",
    )


def test_dq_catches_overlapping_breakdowns(dq_conn):
    _assert_dq_fails(
        dq_conn,
        "INSERT INTO analytics.fact_downtime_event (event_id, line_key,"
        " station_machine_key, downtime_reason_key, shift_key, date_key,"
        " start_timestamp, end_timestamp, duration_min, supplier_tag)"
        " SELECT 'EV-OVERLAP', line_key, station_machine_key, downtime_reason_key,"
        " shift_key, date_key, start_timestamp + INTERVAL '5 minutes',"
        " end_timestamp + INTERVAL '5 minutes', duration_min, FALSE"
        " FROM analytics.fact_downtime_event WHERE event_id = 'EV-1'",
        "DQ-D04",
    )


def test_dq_catches_impossible_performance(dq_conn):
    _assert_dq_fails(
        dq_conn,
        "INSERT INTO analytics.fact_production_hourly (line_key, shift_key, date_key,"
        " product_key, hour_in_shift, hour_start, planned_time_min, run_time_min,"
        " ideal_cycle_time_s, actual_cycle_time_s, total_count, good_count, scrap_count)"
        " SELECT line_key, shift_key, date_key, product_key, 4,"
        " TIMESTAMP '2024-01-01 10:00', 60, 10, 40, 42, 1000, 1000, 0"
        " FROM analytics.fact_production_hourly LIMIT 1",
        "DQ-C07",
    )


def test_dq_catches_undocumented_failure_label(dq_conn):
    _assert_dq_fails(
        dq_conn,
        "INSERT INTO analytics.fact_equipment_state_period (source_system, equipment_ref,"
        " period_type, state_label, start_ts, end_ts, reading_count, duration_seconds)"
        " VALUES ('METROPT3', 'APU', 'failure_window', 'Gremlin',"
        " TIMESTAMP '2020-05-01 00:00', TIMESTAMP '2020-05-01 01:00', 10, 3600)",
        "DQ-I05",
    )


def test_dq_catches_flag_interval_mismatch(dq_conn):
    _assert_dq_fails(
        dq_conn,
        "UPDATE staging.metropt3_readings SET in_failure_window = 5 WHERE source_index = 1",
        "DQ-J07",
    )


def test_runner_end_to_end(tmp_path, monkeypatch):
    from src.run_dq_checks import main

    pgserver = pytest.importorskip("pgserver")
    import tempfile

    import psycopg2

    server = pgserver.get_server(str(tempfile.mkdtemp(prefix="dq_run_")))
    url = server.get_uri()
    try:
        conn = psycopg2.connect(url)
        cursor = conn.cursor()
        for name in ("01_schema.sql", "02_staging.sql", "03_dims.sql", "04_facts.sql"):
            cursor.execute(_read_sql(name))
        cursor.execute(_SETUP_SQL)
        conn.commit()
        conn.close()

        raw = tmp_path / "src"
        raw.mkdir()
        sources = {
            "hourly.csv": 1, "downtime.csv": 1, "wos.csv": 1, "manpower.csv": 1,
            "stations.csv": 1, "quality.csv": 1, "secom.csv": 2, "metropt.csv": 2,
            "intervals.csv": 1, "periods.csv": 1,
        }
        for filename, rows in sources.items():
            with (raw / filename).open("w", encoding="utf-8", newline="") as handle:
                handle.write("col\n" + "1\n" * rows)
        config = {
            "paths": {"reports": str(tmp_path / "reports")},
            "database": {},
            "cost_assumptions": {},
            "spc": {},
            "random_seed": 42,
            "mes": {"outputs": {
                "production_hourly": str(raw / "hourly.csv"),
                "downtime_events": str(raw / "downtime.csv"),
                "work_orders": str(raw / "wos.csv"),
                "manpower_shifts": str(raw / "manpower.csv"),
                "station_operations": str(raw / "stations.csv"),
                "quality_events": str(raw / "quality.csv"),
            }},
            "secom": {"outputs": {"cleaned_data": str(raw / "secom.csv")}},
            "metropt3": {"outputs": {
                "processed_readings": str(raw / "metropt.csv"),
                "failure_intervals": str(raw / "intervals.csv"),
                "state_periods": str(raw / "periods.csv"),
            }},
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            __import__("yaml").safe_dump(config, sort_keys=False), encoding="utf-8"
        )
        monkeypatch.setenv("DATABASE_URL", url)
        assert main(["--config", str(config_path)]) == 0
        import json

        summary = json.loads(
            (tmp_path / "reports" / "dq_check_summary.json").read_text(encoding="utf-8")
        )
        assert summary["failed_checks"] == 0
        assert summary["passed_checks"] == summary["total_checks"]
        assert summary["total_checks"] == (
            _read_sql("06_dq_checks.sql").count("UNION ALL SELECT") + 1 + 10
        )
    finally:
        server.cleanup()


def test_runner_connection_failure(monkeypatch, tmp_path):
    from src.run_dq_checks import main

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    config = {
        "paths": {"reports": str(tmp_path / "reports")},
        "database": {"host": "localhost", "port": 5432, "name": "db",
                     "user_env": "POSTGRES_USER", "password_env": "POSTGRES_PASSWORD"},
        "cost_assumptions": {},
        "spc": {},
        "random_seed": 42,
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        __import__("yaml").safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    assert main(["--config", str(config_path)]) == 1


_SETUP_SQL = """
INSERT INTO analytics.dim_date (date_key, full_date, year, quarter, month, month_name, week, day, day_of_week, is_weekend) VALUES
    (20240101, DATE '2024-01-01', 2024, 1, 1, 'January', 1, 1, 1, FALSE),
    (20080719, DATE '2008-07-19', 2008, 3, 7, 'July', 29, 19, 6, TRUE),
    (20080720, DATE '2008-07-20', 2008, 3, 7, 'July', 29, 20, 7, TRUE),
    (20200418, DATE '2020-04-18', 2020, 2, 4, 'April', 16, 18, 6, TRUE);
INSERT INTO analytics.dim_line (line_code, line_name) VALUES ('L1', 'L1'), ('L2', 'L2');
INSERT INTO analytics.dim_product (product_code, product_name, ideal_cycle_time_s, unit_scrap_cost, cost_source)
    VALUES ('P1', 'P1', 40.0, 12.0, 'test');
INSERT INTO analytics.dim_station_machine (line_key, station_code, station_name, equipment_id, station_sequence, is_bottleneck)
    VALUES ((SELECT line_key FROM analytics.dim_line WHERE line_code = 'L1'), 'L1-S1', 'Loading', 'L1-S1', 1, FALSE);
INSERT INTO analytics.dim_station_machine (line_key, station_code, station_name, equipment_id, station_sequence, is_bottleneck)
    VALUES (NULL, 'APU', 'Air Production Unit', 'APU-01', NULL, FALSE);
INSERT INTO analytics.dim_sensor (source_system, sensor_code, unit, sensor_type, is_critical)
    VALUES ('SECOM', 'sensor_000', NULL, 'analog', NULL),
        ('SECOM', 'sensor_001', NULL, 'analog', NULL),
        ('METROPT3', 'tp2', 'bar', 'analog', NULL),
        ('METROPT3', 'comp', NULL, 'digital', NULL);
INSERT INTO analytics.dim_work_order (work_order_id, line_key, product_key, order_date, due_date, planned_qty)
    VALUES ('WO-1',
        (SELECT line_key FROM analytics.dim_line WHERE line_code = 'L1'),
        (SELECT product_key FROM analytics.dim_product WHERE product_code = 'P1'),
        DATE '2024-01-01', DATE '2024-01-03', 100);
INSERT INTO staging.secom_cleaned (timestamp, target_raw, target, target_label, sensor_000, sensor_001) VALUES
    (TIMESTAMP '2008-07-19 11:55:00', -1, 0, 'pass', 1.0, 2.0),
    (TIMESTAMP '2008-07-20 12:00:00', 1, 1, 'fail', NULL, 3.0);
INSERT INTO staging.metropt3_readings
    (source_index, timestamp, tp2, motor_current, comp, operating_state,
     failure_event_id, in_failure_window, in_prefailure_window) VALUES
    (0, TIMESTAMP '2020-04-18 00:00:00', 1.0, 7.0, 1, 'load', 1, 1, 0),
    (1, TIMESTAMP '2020-04-18 00:00:10', 2.0, 7.0, 0, 'load', 0, 0, 0);
INSERT INTO staging.metropt3_failure_intervals
    (event_id, kind, window_start, window_end, readings_in_window, prefailure_readings) VALUES
    (1, 'Air leak', TIMESTAMP '2020-04-18 00:00:00', TIMESTAMP '2020-04-18 00:01:00', 1, 0);
INSERT INTO staging.metropt3_state_periods
    (period_id, operating_state, start_timestamp, end_timestamp, row_count, duration_seconds) VALUES
    (1, 'load', TIMESTAMP '2020-04-18 00:00:00', TIMESTAMP '2020-04-18 00:01:00', 2, 60.0);
INSERT INTO staging.mes_production_hourly
    (line, shift, date, hour_in_shift, hour_start, product, planned_time_min, run_time_min,
     ideal_cycle_time_s, actual_cycle_time_s, total_count, good_count, scrap_count,
     availability, performance, quality, oee) VALUES
    ('L1', 'A', DATE '2024-01-01', 0, TIMESTAMP '2024-01-01 06:00:00', 'P1',
     60, 55, 40, 42, 78, 76, 2, 0.9167, 0.9455, 0.9744, 0.844);
INSERT INTO staging.mes_downtime_events
    (event_id, line, station, shift, date, start_timestamp, end_timestamp, duration_min,
     reason, oee_bucket, planned, supplier_tag) VALUES
    ('EV-1', 'L1', 'L1-S1', 'A', DATE '2024-01-01',
     TIMESTAMP '2024-01-01 07:00:00', TIMESTAMP '2024-01-01 07:20:00', 20,
     'breakdown', 'Availability', 0, 0);
INSERT INTO staging.mes_work_orders
    (wo_id, line, product, date, planned_qty, produced_qty, good_qty, scrap_qty,
     status, due_date, on_time) VALUES
    ('WO-1', 'L1', 'P1', DATE '2024-01-01', 100, 78, 76, 2, 'partial', DATE '2024-01-03', 0);
INSERT INTO staging.mes_manpower_shifts
    (line, shift, date, planned_headcount, actual_headcount, gap) VALUES
    ('L1', 'A', DATE '2024-01-01', 6, 5, 1);
INSERT INTO staging.mes_station_operations
    (line, station, station_name, shift, date, is_bottleneck, processing_time_s,
     wait_time_s, throughput_units, downtime_min, downtime_event_count) VALUES
    ('L1', 'L1-S1', 'Loading', 'A', DATE '2024-01-01', 0, 25.0, 30.0, 78, 0.0, 0);
INSERT INTO staging.mes_quality_events
    (line, date, product, defect_cause, units_affected, scrap_cost) VALUES
    ('L1', DATE '2024-01-01', 'P1', 'dimensional', 2, 24.0);
INSERT INTO analytics.fact_production_hourly
    (line_key, shift_key, date_key, product_key, hour_in_shift, hour_start,
     planned_time_min, run_time_min, ideal_cycle_time_s, actual_cycle_time_s,
     total_count, good_count, scrap_count)
    SELECT l.line_key, s.shift_key, d.date_key, p.product_key, 0,
        TIMESTAMP '2024-01-01 06:00:00', 60, 55, 40, 42, 78, 76, 2
    FROM analytics.dim_line AS l, analytics.dim_time_shift AS s,
        analytics.dim_date AS d, analytics.dim_product AS p
    WHERE l.line_code = 'L1' AND s.shift_code = 'A' AND d.date_key = 20240101
        AND p.product_code = 'P1';
INSERT INTO analytics.fact_downtime_event
    (event_id, line_key, station_machine_key, downtime_reason_key, shift_key,
     date_key, start_timestamp, end_timestamp, duration_min, supplier_tag)
    SELECT 'EV-1', l.line_key, m.station_machine_key, r.downtime_reason_key,
        s.shift_key, d.date_key, TIMESTAMP '2024-01-01 07:00:00',
        TIMESTAMP '2024-01-01 07:20:00', 20, FALSE
    FROM analytics.dim_line AS l, analytics.dim_station_machine AS m,
        analytics.dim_downtime_reason AS r, analytics.dim_time_shift AS s,
        analytics.dim_date AS d
    WHERE l.line_code = 'L1' AND m.station_code = 'L1-S1'
        AND r.reason_code = 'breakdown' AND s.shift_code = 'A' AND d.date_key = 20240101;
INSERT INTO analytics.fact_quality_lot
    (source_system, source_row, lot_timestamp, target, target_label) VALUES
    ('SECOM', 1, TIMESTAMP '2008-07-19 11:55:00', 0, 'pass'),
    ('SECOM', 2, TIMESTAMP '2008-07-20 12:00:00', 1, 'fail');
INSERT INTO analytics.fact_sensor_reading
    (sensor_key, source_system, source_row, reading_ts, reading_value)
    SELECT k.sensor_key, 'SECOM', 1, TIMESTAMP '2008-07-19 11:55:00', 1.0
    FROM analytics.dim_sensor AS k WHERE k.source_system = 'SECOM' AND k.sensor_code = 'sensor_000';
INSERT INTO analytics.fact_sensor_reading
    (sensor_key, source_system, source_row, reading_ts, reading_value)
    SELECT k.sensor_key, 'SECOM', 1, TIMESTAMP '2008-07-19 11:55:00', 2.0
    FROM analytics.dim_sensor AS k WHERE k.source_system = 'SECOM' AND k.sensor_code = 'sensor_001';
INSERT INTO analytics.fact_sensor_reading
    (sensor_key, source_system, source_row, reading_ts, reading_value)
    SELECT k.sensor_key, 'SECOM', 2, TIMESTAMP '2008-07-20 12:00:00', 3.0
    FROM analytics.dim_sensor AS k WHERE k.source_system = 'SECOM' AND k.sensor_code = 'sensor_001';
INSERT INTO analytics.fact_sensor_reading
    (sensor_key, source_system, source_row, reading_ts, reading_value)
    SELECT k.sensor_key, 'METROPT3', 0, TIMESTAMP '2020-04-18 00:00:00', 1.0
    FROM analytics.dim_sensor AS k WHERE k.source_system = 'METROPT3' AND k.sensor_code = 'tp2';
INSERT INTO analytics.fact_sensor_reading
    (sensor_key, source_system, source_row, reading_ts, reading_value)
    SELECT k.sensor_key, 'METROPT3', 0, TIMESTAMP '2020-04-18 00:00:00', 1.0
    FROM analytics.dim_sensor AS k WHERE k.source_system = 'METROPT3' AND k.sensor_code = 'comp';
INSERT INTO analytics.fact_sensor_reading
    (sensor_key, source_system, source_row, reading_ts, reading_value)
    SELECT k.sensor_key, 'METROPT3', 1, TIMESTAMP '2020-04-18 00:00:10', 2.0
    FROM analytics.dim_sensor AS k WHERE k.source_system = 'METROPT3' AND k.sensor_code = 'tp2';
INSERT INTO analytics.fact_sensor_reading
    (sensor_key, source_system, source_row, reading_ts, reading_value)
    SELECT k.sensor_key, 'METROPT3', 1, TIMESTAMP '2020-04-18 00:00:10', 0.0
    FROM analytics.dim_sensor AS k WHERE k.source_system = 'METROPT3' AND k.sensor_code = 'comp';
INSERT INTO analytics.fact_manpower_shift
    (line_key, shift_key, date_key, planned_headcount, actual_headcount)
    SELECT l.line_key, s.shift_key, d.date_key, 6, 5
    FROM analytics.dim_line AS l, analytics.dim_time_shift AS s, analytics.dim_date AS d
    WHERE l.line_code = 'L1' AND s.shift_code = 'A' AND d.date_key = 20240101;
INSERT INTO analytics.fact_station_operation
    (line_key, station_machine_key, shift_key, date_key, processing_time_s,
     wait_time_s, throughput_units)
    SELECT l.line_key, m.station_machine_key, s.shift_key, d.date_key, 25.0, 30.0, 78
    FROM analytics.dim_line AS l, analytics.dim_station_machine AS m,
        analytics.dim_time_shift AS s, analytics.dim_date AS d
    WHERE l.line_code = 'L1' AND m.station_code = 'L1-S1'
        AND s.shift_code = 'A' AND d.date_key = 20240101;
INSERT INTO analytics.fact_quality_scrap
    (date_key, line_key, product_key, defect_cause_key, units_affected, scrap_cost)
    SELECT d.date_key, l.line_key, p.product_key, c.defect_cause_key, 2, 24.0
    FROM analytics.dim_date AS d, analytics.dim_line AS l, analytics.dim_product AS p,
        analytics.dim_defect_cause AS c
    WHERE d.date_key = 20240101 AND l.line_code = 'L1' AND p.product_code = 'P1'
        AND c.cause_code = 'dimensional';
INSERT INTO analytics.fact_equipment_state_period
    (source_system, equipment_ref, period_type, state_label, start_ts, end_ts,
     reading_count, duration_seconds) VALUES
    ('METROPT3', 'APU', 'operating_state', 'load',
     TIMESTAMP '2020-04-18 00:00:00', TIMESTAMP '2020-04-18 00:01:00', 2, 60.0),
    ('METROPT3', 'APU', 'failure_window', 'Air leak',
     TIMESTAMP '2020-04-18 00:00:00', TIMESTAMP '2020-04-18 00:01:00', 1, 60.0),
    ('METROPT3', 'APU', 'prefailure_window', 'Air leak',
     TIMESTAMP '2020-04-17 00:00:00', TIMESTAMP '2020-04-18 00:00:00', 0, 86400.0);
"""
