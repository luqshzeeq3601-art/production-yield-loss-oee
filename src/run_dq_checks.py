"""Execute sql/06_dq_checks.sql and write reports/dq_check_summary.json."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config_loader import load_config
from src.load_db import LoaderError, _resolve_dsn


STAGING_SOURCES = (
    ("staging.mes_production_hourly", ("mes", "production_hourly")),
    ("staging.mes_downtime_events", ("mes", "downtime_events")),
    ("staging.mes_work_orders", ("mes", "work_orders")),
    ("staging.mes_manpower_shifts", ("mes", "manpower_shifts")),
    ("staging.mes_station_operations", ("mes", "station_operations")),
    ("staging.mes_quality_events", ("mes", "quality_events")),
    ("staging.secom_cleaned", ("secom", "cleaned_data")),
    ("staging.metropt3_readings", ("metropt3", "processed_readings")),
    ("staging.metropt3_failure_intervals", ("metropt3", "failure_intervals")),
    ("staging.metropt3_state_periods", ("metropt3", "state_periods")),
)

# Reading-dependent checks are outside the explicitly selected serving profile.
# The default analytical profile always runs every check, unchanged.
POWERBI_EXCLUDED_CHECKS = ("DQ-H03", "DQ-H05", "DQ-H06", "DQ-I04", "DQ-J07", "DQ-S08")


def run(config_path: str | Path | None = None, *, powerbi_only: bool = False) -> dict[str, Any]:
    """Run all DQ checks and return the summary payload."""

    started = time.perf_counter()
    config = load_config(config_path)
    dsn = _resolve_dsn(config)

    import psycopg2

    try:
        conn = psycopg2.connect(dsn)
    except Exception as exc:
        raise LoaderError(f"Cannot connect to PostgreSQL for DQ checks: {exc}") from exc

    checks: list[dict[str, Any]] = []
    try:
        with conn:
            with conn.cursor() as cursor:
                sql = (_repository_root() / "sql" / "06_dq_checks.sql").read_text(
                    encoding="utf-8"
                )
                cursor.execute(sql)
                for row in cursor.fetchall():
                    if powerbi_only and row[0] in POWERBI_EXCLUDED_CHECKS:
                        continue
                    checks.append(
                        {
                            "check_id": row[0],
                            "check_name": row[1],
                            "category": row[2],
                            "severity": row[3],
                            "violation_count": int(row[4]),
                            "status": row[5],
                            "details": row[6],
                        }
                    )
                checks.extend(_source_checks(cursor, config, powerbi_only))
                cursor.execute("SHOW server_version")
                version = cursor.fetchone()[0]
                source_summary = _source_system_summary(cursor)
    finally:
        conn.close()

    failed = [check for check in checks if check["status"] != "PASS"]
    summary = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "postgresql_version": version,
        "total_checks": len(checks),
        "passed_checks": len(checks) - len(failed),
        "failed_checks": len(failed),
        "total_violations": sum(check["violation_count"] for check in checks),
        "failed_check_ids": [check["check_id"] for check in failed],
        "source_system_summary": source_summary,
        "runtime_seconds": round(time.perf_counter() - started, 1),
        "checks": checks,
        "profile": "powerbi" if powerbi_only else "full_analytics",
        "excluded_checks": list(POWERBI_EXCLUDED_CHECKS) if powerbi_only else [],
    }
    summary_path = _reports_path(config) / "dq_check_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    print(
        f"DQ: {summary['passed_checks']}/{summary['total_checks']} passed,"
        f" {summary['failed_checks']} failed in {summary['runtime_seconds']}s"
    )
    for check in failed:
        print(
            f"  FAIL {check['check_id']} {check['check_name']}:"
            f" {check['violation_count']} ({check['details']})"
        )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    """Run DQ checks as a command-line program."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        summary = run(args.config)
    except LoaderError as exc:
        print(f"DQ checks failed: {exc}", file=sys.stderr)
        return 1
    if any(
        check["status"] != "PASS" and check["severity"] == "ERROR"
        for check in summary["checks"]
    ):
        return 1
    return 0


def _source_checks(cursor: Any, config: Mapping[str, Any], powerbi_only: bool = False) -> list[dict[str, Any]]:
    """Compare live staging counts against source CSV row counts."""

    results = []
    for position, (table, (section, key)) in enumerate(STAGING_SOURCES, start=1):
        if powerbi_only and table == "staging.metropt3_readings":
            continue
        path = _resolve_configured_path(config[section]["outputs"][key])
        with path.open("r", encoding="utf-8", newline="") as handle:
            source_rows = sum(1 for _ in handle) - 1
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        staged = int(cursor.fetchone()[0])
        violations = 0 if staged == source_rows else abs(staged - source_rows)
        results.append(
            {
                "check_id": f"DQ-S{position:02d}",
                "check_name": f"source-to-staging {table}",
                "category": "source_reconciliation",
                "severity": "ERROR",
                "violation_count": violations,
                "status": "PASS" if violations == 0 else "FAIL",
                "details": f"source_rows={source_rows} staged={staged}",
            }
        )
    return results


def _source_system_summary(cursor: Any) -> dict[str, Any]:
    cursor.execute(
        "SELECT source_system, COUNT(*) FROM analytics.fact_sensor_reading"
        " GROUP BY source_system"
    )
    sensors = {row[0]: int(row[1]) for row in cursor.fetchall()}
    cursor.execute("SELECT COUNT(*) FROM analytics.fact_quality_lot")
    lots = int(cursor.fetchone()[0])
    cursor.execute("SELECT COUNT(*) FROM analytics.fact_production_hourly")
    hourly = int(cursor.fetchone()[0])
    return {
        "sensor_readings_by_system": sensors,
        "quality_lots": lots,
        "production_hourly_rows": hourly,
    }


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_configured_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _repository_root() / path


def _reports_path(config: Mapping[str, Any]) -> Path:
    return _resolve_configured_path(config["paths"]["reports"])


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
