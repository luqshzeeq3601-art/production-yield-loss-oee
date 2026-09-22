"""Deterministic synthetic MES generator with injected manufacturing scenarios."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config_loader import load_config


_OUTPUT_KEYS = (
    "production_hourly",
    "downtime_events",
    "work_orders",
    "manpower_shifts",
    "station_operations",
    "quality_events",
    "simulation_summary",
)
HOURLY_COLUMNS = (
    "line",
    "shift",
    "date",
    "hour_in_shift",
    "hour_start",
    "product",
    "planned_time_min",
    "run_time_min",
    "ideal_cycle_time_s",
    "actual_cycle_time_s",
    "total_count",
    "good_count",
    "scrap_count",
    "availability",
    "performance",
    "quality",
    "oee",
)
DOWNTIME_COLUMNS = (
    "event_id",
    "line",
    "station",
    "shift",
    "date",
    "start_timestamp",
    "end_timestamp",
    "duration_min",
    "reason",
    "oee_bucket",
    "planned",
    "supplier_tag",
)
WORK_ORDER_COLUMNS = (
    "wo_id",
    "line",
    "product",
    "date",
    "planned_qty",
    "produced_qty",
    "good_qty",
    "scrap_qty",
    "status",
    "due_date",
    "on_time",
)
MANPOWER_COLUMNS = (
    "line",
    "shift",
    "date",
    "planned_headcount",
    "actual_headcount",
    "gap",
)
STATION_COLUMNS = (
    "line",
    "station",
    "station_name",
    "shift",
    "date",
    "is_bottleneck",
    "processing_time_s",
    "wait_time_s",
    "throughput_units",
    "downtime_min",
    "downtime_event_count",
)
QUALITY_COLUMNS = (
    "line",
    "date",
    "product",
    "defect_cause",
    "units_affected",
    "scrap_cost",
)
_HOURS_PER_SHIFT = 8
_MINUTES_PER_HOUR = 60


def run(config_path: str | Path | None = None) -> dict[str, Path]:
    """Generate the deterministic MES dataset and write configured outputs."""

    config = load_config(config_path)
    mes_config = _mes_config(config)
    seed = int(config["random_seed"])
    rng = np.random.default_rng(seed)
    frames = simulate(rng, mes_config)

    output_paths = _configured_output_paths(mes_config)
    for output_path in output_paths.values():
        output_path.parent.mkdir(parents=True, exist_ok=True)
    for key in _OUTPUT_KEYS:
        if key == "simulation_summary":
            continue
        frames[key].to_csv(output_paths[key], index=False, lineterminator="\n")
    summary = _build_summary(frames, mes_config, seed, output_paths)
    _write_json(output_paths["simulation_summary"], summary)
    return output_paths


def main(argv: Sequence[str] | None = None) -> int:
    """Run MES simulation as a command-line program."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        output_paths = run(args.config)
    except Exception as exc:  # pragma: no cover - CLI error boundary
        print(f"MES simulation failed: {exc}", file=sys.stderr)
        return 1
    for key in _OUTPUT_KEYS:
        print(f"{key}: {output_paths[key]}")
    return 0


def simulate(rng: np.random.Generator, mes_config: Mapping[str, Any]) -> dict[str, pd.DataFrame]:
    """Generate all MES tables from a seeded generator in fixed call order."""

    days = int(mes_config["days"])
    start = date.fromisoformat(str(mes_config["start_date"]))
    dates = [start + timedelta(days=offset) for offset in range(days)]
    lines = [line["id"] for line in mes_config["lines"]]
    shifts = [(shift["id"], int(shift["start_hour"])) for shift in mes_config["shifts"]]
    products = list(mes_config["products"])
    stations_template = list(mes_config["stations_template"])
    reasons = {item["reason"]: item for item in mes_config["downtime_reasons"]}
    scenarios = mes_config["scenarios"]

    hourly_rows: list[dict[str, Any]] = []
    downtime_rows: list[dict[str, Any]] = []
    work_order_rows: list[dict[str, Any]] = []
    manpower_rows: list[dict[str, Any]] = []
    station_rows: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    event_counter = 0

    station_ids = {
        line: [f"{line}-{item['suffix']}" for item in stations_template]
        for line in lines
    }
    bottleneck_index = next(
        position for position, item in enumerate(stations_template) if item["bottleneck"]
    )
    breakdown_weights = _breakdown_weights(len(stations_template), bottleneck_index, mes_config)

    for line_index, line in enumerate(lines):
        for day_index, day in enumerate(dates):
            product = products[(day_index + line_index) % len(products)]
            wear_rate = _tool_wear_rate(line, day_index, scenarios)
            supplier_active = _supplier_active(product["id"], day_index, scenarios)
            day_totals = {"total": 0, "good": 0, "scrap": 0}
            station_downtime: dict[str, dict[str, float]] = {}

            for shift_id, shift_hour in shifts:
                shift_start = datetime.combine(day, time(shift_hour, 0))
                l2_night = _is_line2_night(line, shift_id, scenarios)
                events, pm_minutes = _draw_shift_events(
                    rng, reasons, mes_config, scenarios, line, shift_id,
                    day_index, day, product["id"], l2_night,
                )
                hourly, event_counter = _build_hour_cells(
                    rng, events, pm_minutes, event_counter, line, shift_id,
                    day, shift_start, product, mes_config, scenarios,
                    day_index, wear_rate, supplier_active, l2_night,
                    station_ids[line], breakdown_weights, station_downtime,
                )
                for row in hourly:
                    hourly_rows.append(row)
                    day_totals["total"] += row["total_count"]
                    day_totals["good"] += row["good_count"]
                    day_totals["scrap"] += row["scrap_count"]
                for event in events:
                    downtime_rows.append(event)
                manpower_rows.append(
                    _manpower_row(rng, mes_config, line, shift_id, day)
                )
                station_rows.extend(
                    _station_rows(
                        rng, mes_config, stations_template, line, shift_id, day,
                        sum(row["total_count"] for row in hourly), station_downtime,
                    )
                )
                station_downtime.clear()

            work_order_rows.append(
                _work_order_row(rng, line, product, day, day_totals)
            )
            quality_rows.extend(
                _quality_rows(
                    rng, mes_config, line, product, day, day_index, days,
                    day_totals["scrap"], wear_rate, supplier_active,
                )
            )

    return {
        "production_hourly": pd.DataFrame(hourly_rows, columns=HOURLY_COLUMNS),
        "downtime_events": pd.DataFrame(downtime_rows, columns=DOWNTIME_COLUMNS),
        "work_orders": pd.DataFrame(work_order_rows, columns=WORK_ORDER_COLUMNS),
        "manpower_shifts": pd.DataFrame(manpower_rows, columns=MANPOWER_COLUMNS),
        "station_operations": pd.DataFrame(station_rows, columns=STATION_COLUMNS),
        "quality_events": pd.DataFrame(quality_rows, columns=QUALITY_COLUMNS),
    }


def _draw_shift_events(
    rng: np.random.Generator,
    reasons: Mapping[str, Mapping[str, Any]],
    mes_config: Mapping[str, Any],
    scenarios: Mapping[str, Any],
    line: str,
    shift_id: str,
    day_index: int,
    day: date,
    product_id: str,
    l2_night: bool,
) -> tuple[list[dict[str, Any]], float]:
    """Draw timestamped downtime events for one line-shift-day."""

    events: list[dict[str, Any]] = []
    shift_minutes = _HOURS_PER_SHIFT * _MINUTES_PER_HOUR

    if rng.random() < float(reasons["breakdown"]["rate_per_shift"]):
        duration = _draw_duration(rng, reasons["breakdown"]["duration"])
        start = float(rng.uniform(0, max(shift_minutes - duration, 0)))
        events.append(
            _event_record(
                line, None, shift_id, day, start, duration,
                reasons["breakdown"], supplier_tag=0,
            )
        )
    for reason_name in ("changeover", "material_shortage", "quality_hold"):
        reason = reasons[reason_name]
        count = int(rng.poisson(float(reason["rate_per_shift"])))
        for _ in range(count):
            duration = _draw_duration(rng, reason["duration"])
            start = float(rng.uniform(0, max(shift_minutes - duration, 0)))
            events.append(
                _event_record(line, None, shift_id, day, start, duration, reason, 0)
            )
    minor_rate = float(reasons["minor_stop"]["rate_per_shift"])
    if l2_night:
        minor_rate *= float(scenarios["line2_night"]["minor_stop_rate_multiplier"])
    minor_count = int(rng.poisson(minor_rate))
    for _ in range(minor_count):
        duration = _draw_duration(rng, reasons["minor_stop"]["duration"])
        start = float(rng.uniform(0, max(shift_minutes - duration, 0)))
        events.append(
            _event_record(
                line, None, shift_id, day, start, duration, reasons["minor_stop"], 0
            )
        )
    supplier = scenarios["supplier_quality_hold"]
    if (
        product_id == supplier["product"]
        and day_index == int(supplier["start_day_offset"])
        and shift_id == "A"
    ):
        duration = float(rng.uniform(30.0, 60.0))
        start = float(rng.uniform(0, shift_minutes - duration))
        events.append(
            _event_record(
                line, None, shift_id, day, start, duration,
                reasons["quality_hold"], supplier_tag=1,
            )
        )
    pm_minutes = 0.0
    if shift_id == "A" and rng.random() < float(reasons["planned_maintenance"]["rate_per_day"]):
        pm_duration = _draw_duration(rng, reasons["planned_maintenance"]["duration"])
        pm_start = float(rng.uniform(0, max(shift_minutes - pm_duration, 0)))
        events.append(
            _event_record(
                line, None, shift_id, day, pm_start, pm_duration,
                reasons["planned_maintenance"], supplier_tag=0,
            )
        )
        pm_minutes = pm_duration
    return events, pm_minutes


def _event_record(
    line: str,
    station: str | None,
    shift_id: str,
    day: date,
    start_minute: float,
    duration: float,
    reason: Mapping[str, Any],
    supplier_tag: int,
) -> dict[str, Any]:
    return {
        "line": line,
        "station": station,
        "shift": shift_id,
        "date": day.isoformat(),
        "start_minute": start_minute,
        "duration_min": duration,
        "reason": reason["reason"],
        "oee_bucket": reason["oee_bucket"],
        "planned": int(bool(reason["planned"])),
        "supplier_tag": supplier_tag,
    }


def _build_hour_cells(
    rng: np.random.Generator,
    events: list[dict[str, Any]],
    pm_minutes: float,
    event_counter: int,
    line: str,
    shift_id: str,
    day: date,
    shift_start: datetime,
    product: Mapping[str, Any],
    mes_config: Mapping[str, Any],
    scenarios: Mapping[str, Any],
    day_index: int,
    wear_rate: float,
    supplier_active: bool,
    l2_night: bool,
    line_stations: Sequence[str],
    breakdown_weights: Sequence[float],
    station_downtime: dict[str, dict[str, float]],
) -> tuple[list[dict[str, Any]], int]:
    """Convert shift-day events into 8 hourly production cells with OEE."""

    unplanned = _hourly_overlaps(
        [e for e in events if e["oee_bucket"] == "Availability" and not e["planned"]]
    )
    minor = _hourly_overlaps([e for e in events if e["oee_bucket"] == "Performance"])
    pm_share = pm_minutes / _HOURS_PER_SHIFT
    ideal = float(product["ideal_cycle_time_s"])
    speed = mes_config["speed"]
    supplier = scenarios["supplier_quality_hold"]
    defect_rate = (
        float(product["base_defect_rate"])
        + wear_rate
        + (float(supplier["added_defect_rate"]) if supplier_active else 0.0)
    )
    defect_rate = min(max(defect_rate, 0.0), 1.0)

    rows: list[dict[str, Any]] = []
    for hour in range(_HOURS_PER_SHIFT):
        planned = _MINUTES_PER_HOUR - pm_share
        run = max(planned - min(unplanned[hour], planned), 0.0)
        minor_booked = min(minor[hour], run)
        effective = run - minor_booked
        factor = float(speed["base_factor"]) + float(rng.normal(0, float(speed["noise_std"])))
        if l2_night:
            factor += float(scenarios["line2_night"]["speed_factor_adder"])
        factor = max(factor, 1.0)
        actual = ideal * factor
        total = int(effective * _MINUTES_PER_HOUR / actual) if effective > 0 else 0
        scrap = int(rng.binomial(total, defect_rate)) if total > 0 else 0
        good = total - scrap
        availability = run / planned if planned > 0 else 0.0
        performance = (ideal * total) / (run * 60.0) if run > 0 else 1.0
        quality = good / total if total > 0 else 1.0
        rows.append(
            {
                "line": line,
                "shift": shift_id,
                "date": day.isoformat(),
                "hour_in_shift": hour,
                "hour_start": (shift_start + timedelta(hours=hour)).isoformat(),
                "product": product["id"],
                "planned_time_min": round(planned, 3),
                "run_time_min": round(run, 3),
                "ideal_cycle_time_s": ideal,
                "actual_cycle_time_s": round(actual, 3),
                "total_count": total,
                "good_count": good,
                "scrap_count": scrap,
                "availability": availability,
                "performance": performance,
                "quality": quality,
                "oee": availability * performance * quality,
            }
        )
    for event in events:
        event_counter += 1
        start_dt = shift_start + timedelta(minutes=event.pop("start_minute"))
        event["event_id"] = f"EV-{event_counter:06d}"
        event["station"] = _assign_station(
            rng, event, line_stations, breakdown_weights, station_downtime
        )
        event["start_timestamp"] = start_dt.isoformat()
        event["end_timestamp"] = (start_dt + timedelta(minutes=event["duration_min"])).isoformat()
        event["duration_min"] = round(float(event["duration_min"]), 3)
    return rows, event_counter


def _assign_station(
    rng: np.random.Generator,
    event: Mapping[str, Any],
    line_stations: Sequence[str],
    breakdown_weights: Sequence[float],
    station_downtime: dict[str, dict[str, float]],
) -> str:
    """Assign breakdowns to weighted stations; other reasons stay line-level."""

    if event["reason"] != "breakdown":
        return "LINE"
    station = str(rng.choice(list(line_stations), p=list(breakdown_weights)))
    record = station_downtime.setdefault(station, {"minutes": 0.0, "events": 0})
    record["minutes"] += float(event["duration_min"])
    record["events"] += 1
    return station


def _hourly_overlaps(events: Sequence[Mapping[str, Any]]) -> np.ndarray:
    """Book event minutes into 8 hour cells of a 480-minute shift."""

    booked = np.zeros(_HOURS_PER_SHIFT)
    if not events:
        return booked
    starts = np.array([float(e["start_minute"]) for e in events])
    ends = starts + np.array([float(e["duration_min"]) for e in events])
    edges = np.arange(0, _HOURS_PER_SHIFT + 1) * _MINUTES_PER_HOUR
    for hour in range(_HOURS_PER_SHIFT):
        overlap = np.clip(
            np.minimum(ends, edges[hour + 1]) - np.maximum(starts, edges[hour]),
            0,
            None,
        ).sum()
        booked[hour] = float(overlap)
    return booked


def _draw_duration(rng: np.random.Generator, spec: Mapping[str, Any]) -> float:
    dist = spec["dist"]
    if dist == "exponential":
        value = float(rng.exponential(float(spec["mean_min"])))
        return min(value, float(spec["max_min"]))
    if dist == "uniform":
        return float(rng.uniform(float(spec["min_min"]), float(spec["max_min"])))
    raise ValueError(f"Unsupported duration distribution: {dist}.")


def _manpower_row(
    rng: np.random.Generator, mes_config: Mapping[str, Any], line: str, shift_id: str, day: date
) -> dict[str, Any]:
    planned = int(mes_config["manpower"]["planned_by_shift"][shift_id])
    absence = float(mes_config["manpower"]["absence_probability"][shift_id])
    actual = planned - int(rng.binomial(planned, absence))
    return {
        "line": line,
        "shift": shift_id,
        "date": day.isoformat(),
        "planned_headcount": planned,
        "actual_headcount": actual,
        "gap": planned - actual,
    }


def _station_rows(
    rng: np.random.Generator,
    mes_config: Mapping[str, Any],
    stations_template: Sequence[Mapping[str, Any]],
    line: str,
    shift_id: str,
    day: date,
    throughput_units: int,
    station_downtime: Mapping[str, Mapping[str, float]],
) -> list[dict[str, Any]]:
    rows = []
    for item in stations_template:
        station = f"{line}-{item['suffix']}"
        processing = float(item["base_seconds"]) * float(rng.normal(1.0, 0.05))
        processing = max(processing, 1.0)
        wait_mean = 180.0 if item["bottleneck"] else 45.0
        wait = max(float(rng.exponential(wait_mean)), 0.0)
        record = station_downtime.get(station, {"minutes": 0.0, "events": 0})
        rows.append(
            {
                "line": line,
                "station": station,
                "station_name": str(item["name"]),
                "shift": shift_id,
                "date": day.isoformat(),
                "is_bottleneck": int(bool(item["bottleneck"])),
                "processing_time_s": round(processing, 3),
                "wait_time_s": round(wait, 3),
                "throughput_units": throughput_units,
                "downtime_min": round(float(record["minutes"]), 3),
                "downtime_event_count": int(record["events"]),
            }
        )
    return rows


def _work_order_row(
    rng: np.random.Generator,
    line: str,
    product: Mapping[str, Any],
    day: date,
    day_totals: Mapping[str, int],
) -> dict[str, Any]:
    produced = day_totals["total"]
    planned = max(int(round(produced * float(rng.uniform(0.92, 1.12)))), 1)
    ratio = produced / planned
    if ratio >= 1.0:
        status = "complete"
    elif ratio >= 0.8:
        status = "partial"
    else:
        status = "backlog"
    on_time = 1 if status == "complete" else int(rng.random() < 0.3)
    return {
        "wo_id": f"WO-{line}-{day.strftime('%Y%m%d')}-{product['id']}",
        "line": line,
        "product": product["id"],
        "date": day.isoformat(),
        "planned_qty": planned,
        "produced_qty": produced,
        "good_qty": day_totals["good"],
        "scrap_qty": day_totals["scrap"],
        "status": status,
        "due_date": (day + timedelta(days=2)).isoformat(),
        "on_time": on_time,
    }


def _quality_rows(
    rng: np.random.Generator,
    mes_config: Mapping[str, Any],
    line: str,
    product: Mapping[str, Any],
    day: date,
    day_index: int,
    days: int,
    scrap: int,
    wear_rate: float,
    supplier_active: bool,
) -> list[dict[str, Any]]:
    if scrap <= 0:
        return []
    causes = list(mes_config["defect_causes"])
    wear_line = mes_config["scenarios"]["line3_tool_wear"]["line"]
    base_rate = float(product["base_defect_rate"])
    if line == wear_line and wear_rate > 0:
        tool_wear_share = 0.05 + 0.5 * (wear_rate / (base_rate + wear_rate))
    else:
        tool_wear_share = 0.05
    weights = {
        "dimensional": 0.25,
        "surface defect": 0.20,
        "contamination": 0.15,
        "tool wear": tool_wear_share,
        "supplier material": 0.50 if supplier_active else 0.02,
        "other": 0.05,
    }
    total_weight = sum(weights[cause] for cause in causes)
    shares = {cause: weights[cause] / total_weight for cause in causes}
    units = {cause: int(scrap * shares[cause]) for cause in causes}
    remainder = scrap - sum(units.values())
    order = sorted(causes, key=lambda cause: shares[cause], reverse=True)
    position = 0
    while remainder > 0:
        units[order[position % len(order)]] += 1
        remainder -= 1
        position += 1
    rows = []
    for cause in causes:
        if units[cause] <= 0:
            continue
        rows.append(
            {
                "line": line,
                "date": day.isoformat(),
                "product": product["id"],
                "defect_cause": cause,
                "units_affected": units[cause],
                "scrap_cost": round(units[cause] * float(product["scrap_cost"]), 2),
            }
        )
    return rows


def _tool_wear_rate(line: str, day_index: int, scenarios: Mapping[str, Any]) -> float:
    wear = scenarios["line3_tool_wear"]
    if line != wear["line"]:
        return 0.0
    return float(wear["daily_added_defect_rate"]) * day_index


def _supplier_active(product_id: str, day_index: int, scenarios: Mapping[str, Any]) -> bool:
    supplier = scenarios["supplier_quality_hold"]
    if product_id != supplier["product"]:
        return False
    start = int(supplier["start_day_offset"])
    return start <= day_index < start + int(supplier["duration_days"])


def _is_line2_night(line: str, shift_id: str, scenarios: Mapping[str, Any]) -> bool:
    scenario = scenarios["line2_night"]
    return line == scenario["line"] and shift_id == scenario["shift"]


def _breakdown_weights(
    station_count: int, bottleneck_index: int, mes_config: Mapping[str, Any]
) -> list[float]:
    heavy = float(mes_config["bottleneck_breakdown_weight"])
    light = (1.0 - heavy) / max(station_count - 1, 1)
    return [heavy if position == bottleneck_index else light for position in range(station_count)]


def _mes_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    section = config.get("mes")
    if not isinstance(section, Mapping):
        raise ValueError("Configuration must contain a mapping at mes.")
    required = {
        "start_date",
        "days",
        "shift_hours",
        "shifts",
        "lines",
        "stations_template",
        "bottleneck_breakdown_weight",
        "products",
        "downtime_reasons",
        "speed",
        "defect_causes",
        "manpower",
        "scenarios",
        "outputs",
    }
    missing = sorted(required.difference(section))
    if missing:
        raise ValueError(f"Configuration mes section is missing: {missing}.")
    if not isinstance(section["days"], int) or section["days"] <= 0:
        raise ValueError("Configuration mes.days must be a positive integer.")
    try:
        date.fromisoformat(str(section["start_date"]))
    except ValueError as exc:
        raise ValueError("Configuration mes.start_date must be an ISO date.") from exc
    if len({line["id"] for line in section["lines"]}) != 4:
        raise ValueError("Configuration mes.lines must define exactly 4 unique lines.")
    if len({shift["id"] for shift in section["shifts"]}) != 3:
        raise ValueError("Configuration mes.shifts must define exactly 3 unique shifts.")
    bottlenecks = [item for item in section["stations_template"] if item["bottleneck"]]
    if len(bottlenecks) != 1:
        raise ValueError("Stations template must designate exactly one bottleneck.")
    outputs = section["outputs"]
    if not isinstance(outputs, Mapping) or not set(_OUTPUT_KEYS).issubset(outputs):
        raise ValueError(f"Configuration mes.outputs must define: {', '.join(_OUTPUT_KEYS)}.")
    return section


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_configured_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _repository_root() / path


def _configured_output_paths(mes_config: Mapping[str, Any]) -> dict[str, Path]:
    outputs = mes_config["outputs"]
    return {key: _resolve_configured_path(outputs[key]) for key in _OUTPUT_KEYS}


def _aggregate_oee(frame: pd.DataFrame) -> dict[str, float]:
    planned = float(frame["planned_time_min"].sum())
    run = float(frame["run_time_min"].sum())
    ideal_units = float((frame["ideal_cycle_time_s"] * frame["total_count"]).sum())
    total = int(frame["total_count"].sum())
    good = int(frame["good_count"].sum())
    availability = run / planned if planned > 0 else 0.0
    performance = ideal_units / (run * 60.0) if run > 0 else 1.0
    quality = good / total if total > 0 else 1.0
    return {
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": availability * performance * quality,
    }


def _build_summary(
    frames: Mapping[str, pd.DataFrame],
    mes_config: Mapping[str, Any],
    seed: int,
    output_paths: Mapping[str, Path],
) -> dict[str, Any]:
    hourly = frames["production_hourly"]
    downtime = frames["downtime_events"]
    work_orders = frames["work_orders"]
    manpower = frames["manpower_shifts"]
    stations = frames["station_operations"]
    quality = frames["quality_events"]
    overall = _aggregate_oee(hourly)
    line_oee = {
        line: _aggregate_oee(group) for line, group in hourly.groupby("line", sort=True)
    }
    shift_oee = {
        shift: _aggregate_oee(group) for shift, group in hourly.groupby("shift", sort=True)
    }
    downtime_minutes = (
        downtime.groupby("oee_bucket")["duration_min"].sum().astype(float).to_dict()
    )
    scenarios = mes_config["scenarios"]
    return {
        "seed": seed,
        "start_date": hourly["date"].min(),
        "end_date": hourly["date"].max(),
        "days": int(hourly["date"].nunique()),
        "lines": sorted(hourly["line"].unique().tolist()),
        "shifts": sorted(hourly["shift"].unique().tolist()),
        "products": sorted(hourly["product"].unique().tolist()),
        "work_order_count": int(len(work_orders)),
        "total_count": int(hourly["total_count"].sum()),
        "good_count": int(hourly["good_count"].sum()),
        "scrap_count": int(hourly["scrap_count"].sum()),
        "scrap_rate": float(hourly["scrap_count"].sum() / max(hourly["total_count"].sum(), 1)),
        "downtime_event_count": int(len(downtime)),
        "downtime_minutes_by_bucket": {k: float(v) for k, v in downtime_minutes.items()},
        "manpower_records": int(len(manpower)),
        "manpower_gap_total": int(manpower["gap"].sum()),
        "station_operation_count": int(len(stations)),
        "overall": overall,
        "line_oee": line_oee,
        "shift_oee": shift_oee,
        "line_oee_min": min(v["oee"] for v in line_oee.values()),
        "line_oee_max": max(v["oee"] for v in line_oee.values()),
        "scenarios": {
            "line2_night": dict(scenarios["line2_night"]),
            "line3_tool_wear": dict(scenarios["line3_tool_wear"]),
            "supplier_quality_hold": dict(scenarios["supplier_quality_hold"]),
        },
        "paths": {key: str(path) for key, path in output_paths.items()},
        "assumptions": {
            "planned_maintenance_note": "Planned maintenance is scheduled downtime excluded from planned production time (shift A only).",
            "overlap_note": "Event minutes overlapping an hour cell are booked to that cell; booked unplanned minutes are capped at planned minutes and minor-stop minutes at run minutes.",
            "breakdown_note": "At most one breakdown per line-shift-day (Bernoulli draw), station-weighted toward the bottleneck; other reasons are line-level.",
            "quality_note": "Scrap drawn per hour cell from a binomial with the cell defect rate; causes split the daily scrap proportionally.",
        },
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output_file:
        json.dump(payload, output_file, indent=2, sort_keys=True, ensure_ascii=False)
        output_file.write("\n")


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
