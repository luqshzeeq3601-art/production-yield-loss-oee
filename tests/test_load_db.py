import json
import os
from pathlib import Path

import pandas as pd
import pytest
import yaml

import src.load_db as load_db
from src.load_db import LoaderError, run

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_repo_config_copy(tmp_path):
    config = yaml.safe_load((REPO_ROOT / "src" / "config.yaml").read_text(encoding="utf-8"))
    return config


def _write_fixture_sources(tmp_path):
    raw = tmp_path / "src"
    raw.mkdir()
    with (REPO_ROOT / "data" / "processed" / "secom_cleaned.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        real_sensors = [
            column
            for column in next(__import__("csv").reader(handle))
            if column.startswith("sensor_")
        ]
    values = {
        "timestamp": ["2024-01-01 06:00:00", "2024-01-02 06:00:00"],
        "target_raw": [-1, 1],
        "target": [0, 1],
        "target_label": ["pass", "fail"],
        "sensor_000": [1.5, 2.5],
        "sensor_001": [None, 4.0],
        "sensor_002": [7.0, 8.0],
    }
    for code in real_sensors:
        if code not in values:
            values[code] = 0.0
    pd.DataFrame(values).to_csv(raw / "secom.csv", index=False, lineterminator="\n")
    columns = ["source_index", "timestamp"] + [code for code, _, _ in load_db.METROPT_SIGNALS]
    flags = ["operating_state", "failure_event_id", "in_failure_window", "in_prefailure_window"]
    rows = []
    for i in range(6):
        row = {"source_index": i, "timestamp": f"2020-04-18 00:00:{i:02d}0"}
        for code, sensor_type, _ in load_db.METROPT_SIGNALS:
            row[code] = 1 if sensor_type == "digital" else 0.5 + i
        row.update(
            {
                "operating_state": "load",
                "failure_event_id": 1,
                "in_failure_window": 1,
                "in_prefailure_window": 0,
            }
        )
        rows.append(row)
    pd.DataFrame(rows, columns=columns + flags).rename(
        columns={
            "tp2": "TP2", "tp3": "TP3", "h1": "H1",
            "dv_pressure": "DV_pressure", "reservoirs": "Reservoirs",
            "oil_temperature": "Oil_temperature", "motor_current": "Motor_current",
            "comp": "COMP", "dv_eletric": "DV_eletric", "towers": "Towers",
            "mpg": "MPG", "lps": "LPS", "pressure_switch": "Pressure_switch",
            "oil_level": "Oil_level", "caudal_impulses": "Caudal_impulses",
        }
    ).to_csv(raw / "metropt.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        [
            {
                "event_id": 1,
                "kind": "Air leak",
                "window_start": "2020-04-18 00:00:00",
                "window_end": "2020-04-18 00:01:00",
                "readings_in_window": 6,
                "prefailure_readings": 0,
            }
        ]
    ).to_csv(raw / "intervals.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        [
            {
                "period_id": 1,
                "operating_state": "load",
                "start_timestamp": "2020-04-18 00:00:00",
                "end_timestamp": "2020-04-18 00:01:00",
                "row_count": 6,
                "duration_seconds": 60.0,
            }
        ]
    ).to_csv(raw / "periods.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        [
            {
                "line": "L1", "shift": "A", "date": "2024-01-01", "hour_in_shift": 0,
                "hour_start": "2024-01-01 06:00:00", "product": "P1",
                "planned_time_min": 60.0, "run_time_min": 55.0,
                "ideal_cycle_time_s": 40.0, "actual_cycle_time_s": 42.0,
                "total_count": 78, "good_count": 76, "scrap_count": 2,
                "availability": 0.9167, "performance": 0.9455, "quality": 0.9744, "oee": 0.844,
            },
            {
                "line": "L1", "shift": "A", "date": "2024-01-01", "hour_in_shift": 1,
                "hour_start": "2024-01-01 07:00:00", "product": "P1",
                "planned_time_min": 60.0, "run_time_min": 50.0,
                "ideal_cycle_time_s": 40.0, "actual_cycle_time_s": 44.0,
                "total_count": 68, "good_count": 68, "scrap_count": 0,
                "availability": 0.8333, "performance": 0.9067, "quality": 1.0, "oee": 0.7556,
            },
        ]
    ).to_csv(raw / "hourly.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        [
            {
                "event_id": "EV-000001", "line": "L1", "station": "L1-S3", "shift": "A",
                "date": "2024-01-01", "start_timestamp": "2024-01-01 07:10:00",
                "end_timestamp": "2024-01-01 07:30:00", "duration_min": 20.0,
                "reason": "breakdown", "oee_bucket": "Availability", "planned": 0,
                "supplier_tag": 0,
            }
        ]
    ).to_csv(raw / "downtime.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        [
            {
                "wo_id": "WO-FIX-1", "line": "L1", "product": "P1", "date": "2024-01-01",
                "planned_qty": 140, "produced_qty": 146, "good_qty": 144, "scrap_qty": 2,
                "status": "complete", "due_date": "2024-01-03", "on_time": 1,
            }
        ]
    ).to_csv(raw / "wos.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        [{"line": "L1", "shift": "A", "date": "2024-01-01",
          "planned_headcount": 6, "actual_headcount": 5, "gap": 1}]
    ).to_csv(raw / "manpower.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        [
            {
                "line": "L1", "station": "L1-S1", "station_name": "Loading",
                "shift": "A", "date": "2024-01-01", "is_bottleneck": 0,
                "processing_time_s": 25.0, "wait_time_s": 30.0, "throughput_units": 146,
                "downtime_min": 0.0, "downtime_event_count": 0,
            },
            {
                "line": "L1", "station": "L1-S3", "station_name": "Processing",
                "shift": "A", "date": "2024-01-01", "is_bottleneck": 1,
                "processing_time_s": 65.0, "wait_time_s": 120.0, "throughput_units": 146,
                "downtime_min": 20.0, "downtime_event_count": 1,
            },
        ]
    ).to_csv(raw / "stations.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        [
            {"line": "L1", "date": "2024-01-01", "product": "P1",
             "defect_cause": "dimensional", "units_affected": 2, "scrap_cost": 24.0}
        ]
    ).to_csv(raw / "quality.csv", index=False, lineterminator="\n")
    return raw


def _write_fixture_config(tmp_path, raw):
    config = _write_repo_config_copy(tmp_path)
    config["paths"]["reports"] = str(tmp_path / "reports")
    outputs = {
        "production_hourly": str(raw / "hourly.csv"),
        "downtime_events": str(raw / "downtime.csv"),
        "work_orders": str(raw / "wos.csv"),
        "manpower_shifts": str(raw / "manpower.csv"),
        "station_operations": str(raw / "stations.csv"),
        "quality_events": str(raw / "quality.csv"),
        "simulation_summary": str(tmp_path / "mes_summary.json"),
    }
    config["mes"]["outputs"].update(outputs)
    config["mes"]["products"] = [
        {"id": "P1", "ideal_cycle_time_s": 40.0, "scrap_cost": 12.0,
         "base_defect_rate": 0.025}
    ]
    config["secom"]["outputs"] = {
        "cleaned_data": str(raw / "secom.csv"),
        "missingness_profile": str(raw / "secom_profile.csv"),
        "cleaning_summary": str(raw / "secom_summary.json"),
    }
    config["metropt3"]["outputs"] = {
        "processed_readings": str(raw / "metropt.csv"),
        "failure_intervals": str(raw / "intervals.csv"),
        "state_periods": str(raw / "periods.csv"),
        "ingestion_summary": str(raw / "metropt_summary.json"),
    }
    config["metropt3"]["expected_rows"] = 6
    config["metropt3"]["failure_events"] = [
        {"id": 1, "start": "2020-04-18 00:00:00",
         "end": "2020-04-18 00:01:00", "kind": "Air leak"}
    ]
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        __import__("yaml").safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    return config_path


@pytest.fixture(scope="module")
def live_url(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    import psycopg2

    server = pgserver.get_server(str(tmp_path_factory.mktemp("pgdata")))
    url = server.get_uri()
    conn = psycopg2.connect(url)
    conn.autocommit = True
    conn.cursor().execute("SELECT version()")
    conn.close()
    yield url
    server.cleanup()


@pytest.fixture()
def loaded(live_url, tmp_path):
    raw = _write_fixture_sources(tmp_path)
    config_path = _write_fixture_config(tmp_path, raw)
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = live_url
    try:
        summary = run(config_path)
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
    return summary, live_url, config_path, raw


def _connect(url):
    import psycopg2

    conn = psycopg2.connect(url)
    conn.autocommit = True
    return conn


def test_connection_failure_is_clear(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    config_path = _write_fixture_config(tmp_path, _write_fixture_sources(tmp_path))
    with pytest.raises(LoaderError, match="[Cc]redentials|connect"):
        run(config_path)


def test_sql_files_execute_in_order(loaded):
    summary, _, _, _ = loaded
    assert summary["staging_counts"]["staging.mes_production_hourly"] == 2
    assert summary["fact_counts"]["fact_spc_alert"] == 0


def test_header_normalization_mixed_case(loaded):
    summary, url, _, _ = loaded
    assert summary["staging_counts"]["staging.metropt3_readings"] == 6
    conn = _connect(url)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM analytics.fact_sensor_reading WHERE source_system = 'METROPT3'")
        assert cursor.fetchone()[0] == 6 * len(load_db.METROPT_SIGNALS)
    finally:
        conn.close()


def test_dimension_natural_key_dedup(loaded):
    summary, url, _, _ = loaded
    conn = _connect(url)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), COUNT(DISTINCT line_code) FROM analytics.dim_line")
        total, distinct = cursor.fetchone()
        assert total == distinct == 1
        cursor.execute("SELECT COUNT(*) FROM analytics.dim_sensor WHERE source_system = 'SECOM'")
        assert cursor.fetchone()[0] == 446
        cursor.execute("SELECT COUNT(*) FROM analytics.dim_sensor WHERE source_system = 'METROPT3'")
        assert cursor.fetchone()[0] == len(load_db.METROPT_SIGNALS)
        cursor.execute("SELECT COUNT(*) FROM analytics.dim_date")
        assert cursor.fetchone()[0] == 3
    finally:
        conn.close()


def test_secom_wide_to_long_and_nulls(loaded):
    summary, url, _, raw = loaded
    frame = pd.read_csv(raw / "secom.csv")
    sensors = [c for c in frame.columns if c.startswith("sensor_")]
    expected = int(frame[sensors].notna().sum().sum())
    assert summary["reconciliation"]["secom_readings_non_null_source"] == expected
    assert summary["reconciliation"]["secom_readings_fact"] == expected
    assert summary["reconciliation"]["secom_lots"] == {"source": 2, "staging": 2, "fact": 2}
    conn = _connect(url)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM analytics.fact_sensor_reading"
            " WHERE source_system = 'SECOM' AND reading_value IS NULL"
        )
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


def test_fact_grains_and_fk_resolution(loaded):
    summary, url, _, _ = loaded
    assert summary["reconciliation"]["mes_production"] == {"source": 2, "staging": 2, "fact": 2}
    assert summary["reconciliation"]["mes_downtime"] == {"source": 1, "staging": 1, "fact": 1}
    assert summary["reconciliation"]["mes_manpower"] == {"source": 1, "staging": 1, "fact": 1}
    assert summary["reconciliation"]["mes_station_operations"] == {"source": 2, "staging": 2, "fact": 2}
    assert summary["reconciliation"]["mes_quality_events"] == {"source": 1, "staging": 1, "fact": 1}
    assert summary["unresolved_fk_counts"] == {
        "production_bad_line": 0,
        "downtime_bad_reason": 0,
        "reading_bad_sensor": 0,
    }
    conn = _connect(url)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM analytics.fact_equipment_state_period")
        assert cursor.fetchone()[0] == 3
    finally:
        conn.close()


def test_rerun_is_idempotent(loaded):
    summary, url, config_path, _ = loaded
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        second = run(config_path)
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
    assert second["fact_counts"] == summary["fact_counts"]
    assert second["dimension_counts"] == summary["dimension_counts"]
    assert second["reconciliation"] == summary["reconciliation"]


def test_rollback_on_failure(tmp_path_factory, tmp_path):
    pgserver = pytest.importorskip("pgserver")
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pgdata_rollback")))
    url = server.get_uri()
    try:
        raw = _write_fixture_sources(tmp_path)
        bad = pd.read_csv(raw / "hourly.csv")
        bad.loc[0, "good_count"] = 999
        bad.to_csv(raw / "hourly.csv", index=False, lineterminator="\n")
        config_path = _write_fixture_config(tmp_path, raw)
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        try:
            with pytest.raises(LoaderError):
                run(config_path)
            conn = _connect(url)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.tables"
                    " WHERE table_schema = 'analytics'"
                )
                assert cursor.fetchone()[0] == 0
            finally:
                conn.close()
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
    finally:
        server.cleanup()
