"""PostgreSQL 16 execution tests for P4-001 OEE KPI views."""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = REPO_ROOT / "sql"
PRODUCTION_CSV = REPO_ROOT / "data" / "processed" / "mes_production_hourly.csv"
DOWNTIME_CSV = REPO_ROOT / "data" / "processed" / "mes_downtime_events.csv"
MES_SUMMARY = REPO_ROOT / "reports" / "mes_simulation_summary.json"
SQL_FILES = ("01_schema.sql", "02_staging.sql", "03_dims.sql", "04_facts.sql", "05_views_kpi.sql")


def _read_sql(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


def _start_database(prefix: str):
    pgserver = pytest.importorskip("pgserver")
    import psycopg2

    server = pgserver.get_server(tempfile.mkdtemp(prefix=prefix))
    conn = psycopg2.connect(server.get_uri())
    conn.autocommit = True
    cursor = conn.cursor()
    for name in SQL_FILES:
        cursor.execute(_read_sql(name))
    cursor.execute(_read_sql("05_views_kpi.sql"))
    return server, conn


def _insert_dates(cursor, values: list[date]) -> None:
    for value in sorted(set(values)):
        cursor.execute(
            """
            INSERT INTO analytics.dim_date
                (date_key, full_date, year, quarter, month, month_name, week, day,
                 day_of_week, is_weekend)
            VALUES (%s, %s, %s, %s, %s, TO_CHAR(%s, 'Month'), %s, %s, %s, %s)
            """,
            (
                int(value.strftime("%Y%m%d")), value, value.year,
                (value.month - 1) // 3 + 1, value.month, value,
                value.isocalendar().week, value.day, value.isoweekday(),
                value.isoweekday() in (6, 7),
            ),
        )


def _lookup(cursor, table: str, code_column: str, code: str, key_column: str) -> int:
    cursor.execute(f"SELECT {key_column} FROM analytics.{table} WHERE {code_column} = %s", (code,))
    return int(cursor.fetchone()[0])


@pytest.fixture(scope="module")
def kpi_db():
    server, conn = _start_database("p4_001_")
    cursor = conn.cursor()
    _insert_dates(cursor, [date(2024, 1, 1), date(2024, 1, 2)])
    cursor.execute(
        "INSERT INTO analytics.dim_line (line_code, line_name) VALUES ('L1', 'Line 1'), ('L2', 'Line 2')"
    )
    cursor.execute(
        """
        INSERT INTO analytics.dim_product
            (product_code, product_name, ideal_cycle_time_s, unit_scrap_cost, cost_source)
        VALUES
            ('P1', 'Product 1', 30.78, NULL, 'test'),
            ('P2', 'Product 2', 30.0, NULL, 'test'),
            ('P3', 'Product 3', 15.0, NULL, 'test')
        """
    )
    keys = {
        "l1": _lookup(cursor, "dim_line", "line_code", "L1", "line_key"),
        "l2": _lookup(cursor, "dim_line", "line_code", "L2", "line_key"),
        "p1": _lookup(cursor, "dim_product", "product_code", "P1", "product_key"),
        "p2": _lookup(cursor, "dim_product", "product_code", "P2", "product_key"),
        "p3": _lookup(cursor, "dim_product", "product_code", "P3", "product_key"),
        "a": _lookup(cursor, "dim_time_shift", "shift_code", "A", "shift_key"),
        "b": _lookup(cursor, "dim_time_shift", "shift_code", "B", "shift_key"),
    }

    rows = [
        # Canonical fixture: A=.90, P=.95, Q=.98, OEE=.8379.
        (keys["l1"], keys["a"], 20240101, keys["p1"], 0, "2024-01-01 06:00", 60, 54, 30.78, 32.4, 100, 98, 2),
        # Two unequal-volume hourly rows in one date-line-shift group prove
        # that the view derives OEE from aggregate components, not AVG(hourly OEE).
        (keys["l1"], keys["a"], 20240102, keys["p2"], 0, "2024-01-02 06:00", 60, 60, 30, 30, 120, 120, 0),
        (keys["l1"], keys["a"], 20240102, keys["p3"], 1, "2024-01-02 07:00", 60, 30, 15, 30, 60, 30, 30),
        (keys["l1"], keys["b"], 20240102, keys["p3"], 0, "2024-01-02 14:00", 60, 30, 15, 30, 60, 30, 30),
        (keys["l2"], keys["a"], 20240102, keys["p2"], 0, "2024-01-02 06:00", 60, 60, 30, 30, 120, 120, 0),
        (keys["l2"], keys["b"], 20240102, keys["p3"], 0, "2024-01-02 14:00", 60, 30, 15, 30, 60, 30, 30),
    ]
    cursor.executemany(
        """
        INSERT INTO analytics.fact_production_hourly
            (line_key, shift_key, date_key, product_key, hour_in_shift, hour_start,
             planned_time_min, run_time_min, ideal_cycle_time_s, actual_cycle_time_s,
             total_count, good_count, scrap_count)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows,
    )
    reason_keys = {
        code: _lookup(cursor, "dim_downtime_reason", "reason_code", code, "downtime_reason_key")
        for code in ("breakdown", "minor_stop", "planned_maintenance")
    }
    cursor.executemany(
        """
        INSERT INTO analytics.fact_downtime_event
            (event_id, line_key, downtime_reason_key, shift_key, date_key,
             start_timestamp, end_timestamp, duration_min, supplier_tag)
        VALUES (%s, %s, %s, %s, 20240101, %s, %s, %s, %s)
        """,
        [
            ("EV-TEST-001", keys["l1"], reason_keys["breakdown"], keys["a"], "2024-01-01 06:00", "2024-01-01 06:10", 10, False),
            ("EV-TEST-002", keys["l1"], reason_keys["minor_stop"], keys["a"], "2024-01-01 06:10", "2024-01-01 06:15", 5, False),
            ("EV-TEST-003", keys["l1"], reason_keys["planned_maintenance"], keys["a"], "2024-01-01 06:15", "2024-01-01 06:22", 7, True),
        ],
    )
    yield conn
    conn.close()
    server.cleanup()


def test_views_execute_rerunnable_and_canonical_oee(kpi_db):
    cursor = kpi_db.cursor()
    cursor.execute(
        "SELECT table_name FROM information_schema.views WHERE table_schema = 'analytics'"
    )
    assert {row[0] for row in cursor.fetchall()} >= {
        "vw_oee_line_shift",
        "vw_oee_loss_decomposition",
        "vw_pareto_scrap",
        "vw_pareto_downtime",
    }
    cursor.execute(
        """
        SELECT availability, performance, quality, oee, downtime_minutes,
               ideal_cycle_time_weighted_basis_minutes
        FROM analytics.vw_oee_line_shift
        WHERE full_date = DATE '2024-01-01' AND line_code = 'L1' AND shift_code = 'A'
        """
    )
    availability, performance, quality, oee, downtime, ideal_minutes = cursor.fetchone()
    assert availability == pytest.approx(0.90)
    assert performance == pytest.approx(0.95)
    assert quality == pytest.approx(0.98)
    assert oee == pytest.approx(0.8379)
    assert downtime == pytest.approx(6.0)
    assert ideal_minutes == pytest.approx(51.3)


def test_unequal_volume_aggregation_uses_components_not_average(kpi_db):
    cursor = kpi_db.cursor()
    cursor.execute(
        """
        WITH hourly AS (
            SELECT
                AVG((run_time_min / planned_time_min)
                    * ((ideal_cycle_time_s * total_count / 60.0) / run_time_min)
                    * (good_count::DOUBLE PRECISION / total_count)) AS arithmetic_hourly_oee,
                SUM(planned_time_min) AS planned,
                SUM(run_time_min) AS run,
                SUM(ideal_cycle_time_s * total_count) / 60.0 AS ideal,
                SUM(total_count) AS total,
                SUM(good_count) AS good
            FROM analytics.fact_production_hourly
            WHERE date_key = 20240102 AND line_key = (
                SELECT line_key FROM analytics.dim_line WHERE line_code = 'L1'
            ) AND shift_key = (
                SELECT shift_key FROM analytics.dim_time_shift WHERE shift_code = 'A'
            )
        )
        SELECT v.oee, hourly.arithmetic_hourly_oee,
            (hourly.run / hourly.planned) * (hourly.ideal / hourly.run)
                * (hourly.good::DOUBLE PRECISION / hourly.total) AS aggregate_component_oee
        FROM analytics.vw_oee_line_shift v CROSS JOIN hourly
        WHERE v.full_date = DATE '2024-01-02' AND v.line_code = 'L1' AND v.shift_code = 'A'
        """
    )
    view_oee, arithmetic_hourly_oee, aggregate_component_oee = cursor.fetchone()
    assert view_oee == pytest.approx(aggregate_component_oee)
    assert view_oee != pytest.approx(arithmetic_hourly_oee)

    cursor.execute(
        """
        WITH source AS (
            SELECT line_key, shift_key, date_key,
                SUM(planned_time_min) AS planned, SUM(run_time_min) AS run,
                SUM(ideal_cycle_time_s * total_count) / 60.0 AS ideal,
                SUM(total_count) AS total, SUM(good_count) AS good
            FROM analytics.fact_production_hourly
            GROUP BY GROUPING SETS ((line_key), (shift_key), (date_key), ())
        ), view_components AS (
            SELECT line_key, shift_key, date_key,
                SUM(planned_production_time) AS planned, SUM(run_time) AS run,
                SUM(ideal_cycle_time_weighted_basis_minutes) AS ideal,
                SUM(total_count) AS total, SUM(good_count) AS good,
                AVG(oee) AS row_average_oee
            FROM analytics.vw_oee_line_shift
            GROUP BY GROUPING SETS ((line_key), (shift_key), (date_key), ())
        )
        SELECT source.planned, source.run, source.ideal, source.total, source.good,
               view_components.planned, view_components.run, view_components.ideal,
               view_components.total, view_components.good, view_components.row_average_oee
        FROM source
        JOIN view_components
            ON source.line_key IS NOT DISTINCT FROM view_components.line_key
            AND source.shift_key IS NOT DISTINCT FROM view_components.shift_key
            AND source.date_key IS NOT DISTINCT FROM view_components.date_key
        """
    )
    rows = cursor.fetchall()
    assert len(rows) == 7  # 2 lines, 2 shifts, 2 days, and the plant all execute.
    differs_from_row_average = False
    for row in rows:
        planned, run, ideal, total, good, v_planned, v_run, v_ideal, v_total, v_good, average_oee = row
        assert (v_planned, v_run, v_ideal, v_total, v_good) == pytest.approx(
            (planned, run, ideal, total, good)
        )
        component_oee = (run / planned) * (ideal / run) * (good / total)
        if average_oee is not None and abs(component_oee - average_oee) > 0.01:
            differs_from_row_average = True
    assert differs_from_row_average


def test_valid_view_metrics_are_in_range_and_losses_are_nonnegative(kpi_db):
    cursor = kpi_db.cursor()
    cursor.execute("SELECT MAX(planned_time_min) FROM analytics.fact_production_hourly")
    assert cursor.fetchone()[0] <= 60
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM analytics.vw_oee_line_shift
        WHERE availability NOT BETWEEN 0 AND 1
           OR performance NOT BETWEEN 0 AND 1
           OR quality NOT BETWEEN 0 AND 1
           OR oee NOT BETWEEN 0 AND 1
        """
    )
    assert cursor.fetchone()[0] == 0
    cursor.execute(
        "SELECT COUNT(*) FROM analytics.vw_oee_loss_decomposition WHERE loss_minutes < 0 OR loss_hours < 0"
    )
    assert cursor.fetchone()[0] == 0


def test_loss_bucket_mapping_and_planned_maintenance_separation(kpi_db):
    cursor = kpi_db.cursor()
    cursor.execute(
        """
        SELECT loss_category, loss_reason, is_planned, loss_minutes, scrap_count,
               supplier_tagged_event_count, measurement_basis
        FROM analytics.vw_oee_loss_decomposition
        WHERE full_date = DATE '2024-01-01' AND line_code = 'L1' AND shift_code = 'A'
        ORDER BY loss_reason
        """
    )
    rows = {row[1]: row for row in cursor.fetchall()}
    assert rows["breakdown"][0:3] == ("Availability", "breakdown", False)
    assert rows["breakdown"][3] == pytest.approx(10.0)
    assert rows["minor_stop"][0:3] == ("Performance", "minor_stop", False)
    assert rows["minor_stop"][3] == pytest.approx(5.0)
    assert rows["planned_maintenance"][0:3] == ("Planned", "planned_maintenance", True)
    assert rows["planned_maintenance"][3] == pytest.approx(7.0)
    assert rows["planned_maintenance"][5] == 1
    assert rows["planned_maintenance"][6] == "raw_downtime_event_duration_diagnostic_non_additive"
    assert rows["reduced_speed"][0] == "Performance"
    assert rows["scrap"][0] == "Quality"
    assert rows["scrap"][4] == 2


def test_zero_denominators_return_null_without_clamping():
    server, conn = _start_database("p4_001_zero_")
    try:
        cursor = conn.cursor()
        _insert_dates(cursor, [date(2024, 1, 3)])
        cursor.execute("INSERT INTO analytics.dim_line (line_code, line_name) VALUES ('L0', 'Line 0')")
        cursor.execute(
            "INSERT INTO analytics.dim_product (product_code, ideal_cycle_time_s) VALUES ('P0', 60)"
        )
        line_key = _lookup(cursor, "dim_line", "line_code", "L0", "line_key")
        product_key = _lookup(cursor, "dim_product", "product_code", "P0", "product_key")
        shift_key = _lookup(cursor, "dim_time_shift", "shift_code", "A", "shift_key")
        cursor.execute(
            "ALTER TABLE analytics.fact_production_hourly DROP CONSTRAINT fact_production_hourly_planned_time_min_check"
        )
        cursor.execute(
            """
            INSERT INTO analytics.fact_production_hourly
                (line_key, shift_key, date_key, product_key, hour_in_shift, hour_start,
                 planned_time_min, run_time_min, ideal_cycle_time_s, actual_cycle_time_s,
                 total_count, good_count, scrap_count)
            VALUES (%s, %s, 20240103, %s, 0, TIMESTAMP '2024-01-03 06:00',
                    0, 0, 60, 60, 0, 0, 0)
            """,
            (line_key, shift_key, product_key),
        )
        cursor.execute(
            """
            SELECT availability, performance, quality, oee
            FROM analytics.vw_oee_line_shift WHERE line_code = 'L0'
            """
        )
        assert cursor.fetchone() == (None, None, None, None)
    finally:
        conn.close()
        server.cleanup()


@pytest.fixture(scope="module")
def mes_csv_db():
    """Load only the existing MES CSVs into an ephemeral PostgreSQL 16 database."""
    server, conn = _start_database("p4_001_mes_")
    cursor = conn.cursor()
    with PRODUCTION_CSV.open("r", encoding="utf-8", newline="") as source:
        cursor.copy_expert("COPY staging.mes_production_hourly FROM STDIN WITH (FORMAT CSV, HEADER)", source)
    with DOWNTIME_CSV.open("r", encoding="utf-8", newline="") as source:
        cursor.copy_expert("COPY staging.mes_downtime_events FROM STDIN WITH (FORMAT CSV, HEADER)", source)
    cursor.execute(
        """
        INSERT INTO analytics.dim_date
            (date_key, full_date, year, quarter, month, month_name, week, day,
             day_of_week, is_weekend)
        SELECT DISTINCT
            EXTRACT(YEAR FROM date)::INTEGER * 10000
                + EXTRACT(MONTH FROM date)::INTEGER * 100 + EXTRACT(DAY FROM date)::INTEGER,
            date, EXTRACT(YEAR FROM date)::SMALLINT, EXTRACT(QUARTER FROM date)::SMALLINT,
            EXTRACT(MONTH FROM date)::SMALLINT, RTRIM(TO_CHAR(date, 'Month')),
            EXTRACT(WEEK FROM date)::SMALLINT, EXTRACT(DAY FROM date)::SMALLINT,
            EXTRACT(ISODOW FROM date)::SMALLINT, EXTRACT(ISODOW FROM date)::INTEGER IN (6, 7)
        FROM (SELECT date FROM staging.mes_production_hourly UNION SELECT date FROM staging.mes_downtime_events) dates
        """
    )
    cursor.execute(
        "INSERT INTO analytics.dim_line (line_code, line_name) SELECT DISTINCT line, line FROM staging.mes_production_hourly"
    )
    cursor.execute(
        """
        INSERT INTO analytics.dim_product (product_code, product_name, ideal_cycle_time_s)
        SELECT product, product, MAX(ideal_cycle_time_s) FROM staging.mes_production_hourly GROUP BY product
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.fact_production_hourly
            (line_key, shift_key, date_key, product_key, hour_in_shift, hour_start,
             planned_time_min, run_time_min, ideal_cycle_time_s, actual_cycle_time_s,
             total_count, good_count, scrap_count)
        SELECT l.line_key, s.shift_key, d.date_key, p.product_key, h.hour_in_shift,
            h.hour_start, h.planned_time_min, h.run_time_min, h.ideal_cycle_time_s,
            h.actual_cycle_time_s, h.total_count, h.good_count, h.scrap_count
        FROM staging.mes_production_hourly h
        JOIN analytics.dim_line l ON l.line_code = h.line
        JOIN analytics.dim_time_shift s ON s.shift_code = h.shift
        JOIN analytics.dim_date d ON d.full_date = h.date
        JOIN analytics.dim_product p ON p.product_code = h.product
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.fact_downtime_event
            (event_id, line_key, downtime_reason_key, shift_key, date_key,
             start_timestamp, end_timestamp, duration_min, supplier_tag)
        SELECT e.event_id, l.line_key, r.downtime_reason_key, s.shift_key, d.date_key,
            e.start_timestamp, e.end_timestamp, e.duration_min, e.supplier_tag = 1
        FROM staging.mes_downtime_events e
        JOIN analytics.dim_line l ON l.line_code = e.line
        JOIN analytics.dim_downtime_reason r ON r.reason_code = e.reason
        JOIN analytics.dim_time_shift s ON s.shift_code = e.shift
        JOIN analytics.dim_date d ON d.full_date = e.date
        """
    )
    yield conn
    conn.close()
    server.cleanup()


def test_whole_mes_csv_reconciles_with_p2_summary_and_preserves_scenarios(mes_csv_db):
    expected = json.loads(MES_SUMMARY.read_text(encoding="utf-8"))["overall"]
    cursor = mes_csv_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM analytics.fact_production_hourly")
    assert cursor.fetchone()[0] == 17280
    cursor.execute("SELECT COUNT(*) FROM analytics.vw_oee_line_shift")
    assert cursor.fetchone()[0] == 2160
    cursor.execute(
        """
        SELECT
            SUM(run_time) / SUM(planned_production_time),
            SUM(ideal_cycle_time_weighted_basis_minutes) / SUM(run_time),
            SUM(good_count)::DOUBLE PRECISION / SUM(total_count),
            (SUM(run_time) / SUM(planned_production_time))
                * (SUM(ideal_cycle_time_weighted_basis_minutes) / SUM(run_time))
                * (SUM(good_count)::DOUBLE PRECISION / SUM(total_count))
        FROM analytics.vw_oee_line_shift
        """
    )
    actual = cursor.fetchone()
    for value, name in zip(actual, ("availability", "performance", "quality", "oee"), strict=True):
        assert value == pytest.approx(expected[name])
    # Aggregate components, rather than row-level ratios, expose L2-C's lower performance.
    cursor.execute(
        """
        SELECT shift_code,
            SUM(ideal_cycle_time_weighted_basis_minutes) / SUM(run_time) AS performance
        FROM analytics.vw_oee_line_shift WHERE line_code = 'L2'
        GROUP BY shift_code ORDER BY shift_code
        """
    )
    l2_performance = dict(cursor.fetchall())
    assert l2_performance["C"] < l2_performance["A"]
    assert l2_performance["C"] < l2_performance["B"]
    cursor.execute(
        """
        SELECT
            SUM(good_count) FILTER (WHERE full_date < DATE '2024-03-31')::DOUBLE PRECISION
                / SUM(total_count) FILTER (WHERE full_date < DATE '2024-03-31'),
            SUM(good_count) FILTER (WHERE full_date >= DATE '2024-03-31')::DOUBLE PRECISION
                / SUM(total_count) FILTER (WHERE full_date >= DATE '2024-03-31')
        FROM analytics.vw_oee_line_shift WHERE line_code = 'L3'
        """
    )
    first_half, second_half = cursor.fetchone()
    assert second_half < first_half
    cursor.execute(
        """
        SELECT supplier_tagged_event_count
        FROM analytics.vw_oee_loss_decomposition
        WHERE full_date = DATE '2024-03-31' AND loss_reason = 'quality_hold'
        """
    )
    assert sum(row[0] for row in cursor.fetchall()) >= 1
