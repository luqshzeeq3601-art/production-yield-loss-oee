"""Verify expected data files exist with valid schema and row counts.

Processed-layer checks always run (exact counts; deterministic generation).
Raw-file checks run only when data/raw/ is present. No database needed.

Usage:
    py -3.11 -m scripts.verify_data
    py -3.11 -m scripts.verify_data --processed-only
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

PROCESSED_EXPECTATIONS: dict[str, dict] = {
    "data/processed/mes_production_hourly.csv": {
        "rows": 17280,
        "columns": ["planned_time_min", "run_time_min", "ideal_cycle_time_s",
                    "total_count", "good_count", "scrap_count"],
    },
    "data/processed/mes_downtime_events.csv": {
        "rows": 24147,
        "columns": ["duration_min", "reason"],
    },
    "data/processed/mes_quality_events.csv": {
        "rows": 4096,
        "columns": ["units_affected", "scrap_cost", "defect_cause"],
    },
    "data/processed/mes_work_orders.csv": {"rows": 720, "columns": []},
    "data/processed/mes_manpower_shifts.csv": {
        "rows": 2160, "columns": ["planned_headcount", "actual_headcount"],
    },
    "data/processed/mes_station_operations.csv": {
        "rows": 10800, "columns": ["processing_time_s", "wait_time_s", "throughput_units"],
    },
    "data/processed/secom_cleaned.csv": {
        "rows": 1567,
        "columns": ["target"],
    },
    "data/processed/metropt3_failure_intervals.csv": {"rows": 4, "columns": []},
    "data/processed/metropt3_state_periods.csv": {"rows": 70620, "columns": []},
}

RAW_EXPECTATIONS: dict[str, dict] = {
    "data/raw/secom.data": {"columns": []},
    "data/raw/secom_labels.data": {"columns": []},
    "data/raw/metropt3/MetroPT3(AirCompressor).csv": {"columns": []},
}


def check_file(rel: str, spec: dict, errors: list[str]) -> None:
    path = ROOT / rel
    if not path.is_file():
        errors.append(f"missing file: {rel}")
        return
    try:
        df = pd.read_csv(path, nrows=5)
    except Exception as exc:
        errors.append(f"unreadable CSV {rel}: {exc}")
        return
    for col in spec.get("columns", []):
        if col not in df.columns:
            errors.append(f"{rel}: missing column '{col}'")
    if "rows" in spec:
        try:
            with path.open(encoding="utf-8") as stream:
                n = sum(1 for _ in stream) - 1
        except Exception as exc:
            errors.append(f"{rel}: could not count rows ({exc})")
            return
        if n != spec["rows"]:
            errors.append(f"{rel}: found {n} rows, expected {spec['rows']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-only", action="store_true",
                        help="skip raw-file checks even when data/raw exists")
    args = parser.parse_args(argv)

    errors: list[str] = []
    for rel, spec in PROCESSED_EXPECTATIONS.items():
        check_file(rel, spec, errors)

    raw_dir = ROOT / "data" / "raw"
    has_raw = raw_dir.is_dir() and any(raw_dir.iterdir())
    if args.processed_only or not has_raw:
        print("raw checks: skipped (no data/raw present or --processed-only)")
    else:
        for rel, spec in RAW_EXPECTATIONS.items():
            check_file(rel, spec, errors)

    if errors:
        print("DATA VERIFICATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"data verification passed ({len(PROCESSED_EXPECTATIONS)} processed files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
