"""Behavioral serving/load/model gates using an isolated real PostgreSQL server."""

import json
import shutil
from pathlib import Path

import pandas as pd
import psycopg2
import pytest
import yaml

from src import load_db, powerbi_serving, run_dq_checks
from src.config_loader import load_config
from test_load_db import _write_fixture_config, _write_fixture_sources

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def serving_db(tmp_path_factory):
    import pgserver

    temp = tmp_path_factory.mktemp("powerbi_serving")
    raw = _write_fixture_sources(temp)
    config_path = _write_fixture_config(temp, raw)
    config = load_config(config_path)
    config["secom"]["outputs"]["cleaned_data"] = str(ROOT / "data/processed/secom_cleaned.csv")
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    (raw / "metropt.csv").unlink()  # Gate must pass without reading-level MetroPT.
    server = pgserver.get_server(str(temp / "pgdata"))
    previous = __import__("os").environ.get("DATABASE_URL")
    __import__("os").environ["DATABASE_URL"] = server.get_uri()
    conn = psycopg2.connect(server.get_uri())
    try:
        loaded = load_db.run(config_path, powerbi_only=True)
        dq = run_dq_checks.run(config_path, powerbi_only=True)
        evidence = powerbi_serving.load_evidence(conn, ROOT / "reports", dq)
        yield conn, config_path, loaded, dq, evidence
    finally:
        conn.close()
        if previous is None:
            __import__("os").environ.pop("DATABASE_URL", None)
        else:
            __import__("os").environ["DATABASE_URL"] = previous
        server.cleanup()


def test_serving_load_and_dq_work_without_metropt_readings(serving_db):
    _, config_path, loaded, dq, _ = serving_db
    assert loaded["excluded_sources"] == ["metropt3_readings"]
    assert loaded["reconciliation"]["secom_lots"] == {"source": 1567, "staging": 1567, "fact": 1567}
    assert loaded["reconciliation"]["mes_production"] == {"source": 2, "staging": 2, "fact": 2}
    assert "metropt3_readings_expected" not in loaded["reconciliation"]
    assert dq["passed_checks"] == dq["total_checks"] == 59
    assert dq["failed_checks"] == dq["total_violations"] == 0
    assert set(dq["excluded_checks"]) == set(run_dq_checks.POWERBI_EXCLUDED_CHECKS)
    with pytest.raises(load_db.LoaderError, match="missing"):
        load_db.run(config_path)  # Default full pipeline still requires the real file.


def test_serving_rerun_preserves_facts_and_diagnostic_snapshot(serving_db):
    conn, config_path, first, dq, evidence = serving_db
    second = load_db.run(config_path, powerbi_only=True)
    for name, count in first["fact_counts"].items():
        if name != "fact_spc_alert":
            assert second["fact_counts"][name] == count
    assert second["fact_counts"]["fact_spc_alert"] == evidence["fact_spc_alert"]
    assert powerbi_serving.load_evidence(conn, ROOT / "reports", dq) == evidence


def test_live_page_dependencies_and_work_order_grain(serving_db):
    conn, config_path, *_ = serving_db
    result = powerbi_serving.validate_live(conn, config_path)
    assert len(result["pages"]) == 7
    assert all(p["status"] == "READY" for p in result["pages"])
    assert result["plant"]["total_count"] == 146
    assert result["work_orders"] == {"complete": 1}
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT work_order_id) FROM analytics.vw_work_orders")
        assert cur.fetchone() == (1, 1)
        cur.execute("SELECT COUNT(*), MAX(full_date)-MIN(full_date)+1 FROM analytics.vw_powerbi_date")
        size, span = cur.fetchone()
        assert size == span
        cur.execute("SELECT COUNT(*) FROM analytics.vw_spc_readings WHERE source_row<470 OR source_system!='SECOM'")
        assert cur.fetchone()[0] == 0


def test_live_gate_rejects_missing_visual_column(serving_db, tmp_path, monkeypatch):
    conn, *_ = serving_db
    shutil.copytree(ROOT / "powerbi", tmp_path / "powerbi")
    path = tmp_path / "powerbi/visual_mapping.json"
    mapping = json.loads(path.read_text())
    mapping["pages"][0]["visuals"][1]["field"] = "dim_line.unsupported_field"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    monkeypatch.setattr(powerbi_serving, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="Unmapped visual column"):
        powerbi_serving.validate_bindings(conn)


def test_spc_gate_rejects_stale_method_precision(tmp_path):
    shutil.copytree(ROOT / "reports", tmp_path / "reports")
    reports = tmp_path / "reports"
    methods = pd.read_csv(reports / "spc_backtest_methods.csv")
    methods.loc[methods.method == "WE", "precision"] = 46 / 1097
    methods.to_csv(reports / "spc_backtest_methods.csv", index=False)
    with pytest.raises(ValueError, match="Stale SPC evidence"):
        powerbi_serving.validate_spc_evidence(reports, ROOT / "data/processed/secom_cleaned.csv")


def test_spc_gate_rejects_changed_phase_two_targets(tmp_path):
    cleaned = pd.read_csv(ROOT / "data/processed/secom_cleaned.csv")
    cleaned.loc[500, "target"] = 1 - cleaned.loc[500, "target"]
    source = tmp_path / "changed.csv"
    cleaned.to_csv(source, index=False)
    with pytest.raises(ValueError, match="do not match"):
        powerbi_serving.validate_spc_evidence(ROOT / "reports", source)


def test_database_environment_overrides_and_quoted_password(monkeypatch):
    from psycopg2.extensions import parse_dsn

    monkeypatch.delenv("DATABASE_URL", raising=False)
    for key, value in {"POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5440",
                       "POSTGRES_DB": "fixture_db", "POSTGRES_USER": "fixture_user",
                       "POSTGRES_PASSWORD": "dummy quoted ' and space"}.items():
        monkeypatch.setenv(key, value)
    resolved = parse_dsn(load_db._resolve_dsn(load_config()))
    assert resolved["host"] == "127.0.0.1" and resolved["port"] == "5440"
    assert resolved["dbname"] == "fixture_db" and resolved["user"] == "fixture_user"
    assert resolved["password"] == "dummy quoted ' and space"


def test_bootstrap_check_runs_through_evidence_transaction(serving_db, tmp_path, monkeypatch):
    from scripts import bootstrap_powerbi_db as bootstrap

    conn, config_path, *_ = serving_db
    # Prior read-only assertions use this shared connection. Release their locks
    # before the helper opens another connection to replace report snapshots.
    conn.rollback()
    config = load_config(config_path)
    shutil.copytree(ROOT / "reports", tmp_path / "reports")
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "LOCAL", tmp_path / ".local")
    monkeypatch.setattr(bootstrap, "load_config", lambda: config)
    monkeypatch.setattr(bootstrap, "load_environment", lambda _: None)
    monkeypatch.setattr(bootstrap.cross_system_reconciliation, "run", lambda: {
        "total_checks": 75, "pass_count": 75, "fail_count": 0,
        "database_live": {"available": True},
    })
    result = bootstrap.prepare("check", tmp_path, tmp_path / ".env", False)
    assert result["status"] == "READY"
    assert result["live_validation"]["plant"]["total_count"] == 146
    assert result["dq"]["passed_checks"] == 59
    assert (tmp_path / "reports/powerbi_readiness.json").is_file()


def test_failed_check_cannot_leave_a_stale_ready_report(tmp_path, monkeypatch):
    from scripts import bootstrap_powerbi_db as bootstrap

    reports = tmp_path / "reports"
    reports.mkdir()
    path = reports / "powerbi_readiness.json"
    path.write_text('{"status":"READY"}', encoding="utf-8")
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    def fail(*_):
        raise ValueError("fixture connection failure")
    monkeypatch.setattr(bootstrap, "prepare", fail)
    assert bootstrap.main(["check"]) == 1
    assert json.loads(path.read_text())["status"] == "BLOCKED"
