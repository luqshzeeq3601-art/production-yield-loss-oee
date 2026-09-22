"""Fail-closed chronological evaluation of frozen Phase II SPC alerts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config_loader import load_config

METHODS = ("WE", "EWMA", "T2", "WE+EWMA", "WE+EWMA+T2")
EXCURSION_MAX_GAP_LOTS = 2
FROZEN_PHASE1_LOTS, FROZEN_PHASE2_LOTS = 470, 1097
FROZEN_SELECTED_SENSORS = (
    "sensor_021", "sensor_000", "sensor_064", "sensor_122", "sensor_022",
    "sensor_090", "sensor_076", "sensor_562", "sensor_033", "sensor_125",
)
FROZEN_EWMA_LAMBDA, FROZEN_EWMA_L = 0.2, 3.0
FROZEN_T2_ALPHA, FROZEN_T2_UCL = 0.01, 24.815413111657534
FROZEN_T2_COMPLETE_PHASE2_LOTS = 901
_OUTPUT_KEYS = ("lots", "failures", "methods", "excursions", "summary")
_LOTS_COLUMNS = ("source_row", "timestamp", "target", "we_alert", "ewma_alert", "t2_available", "t2_alert", "we_or_ewma", "all_methods_alert")
_FAILURES_COLUMNS = ("source_row", "timestamp", "method", "method_eligible", "alerted", "alert_timestamp", "manual_detection_timestamp", "manual_latency_hours", "new_latency_hours", "hours_saved", "latency_reduction_pct")
_METHODS_COLUMNS = ("method", "population_lots", "eligible_lots", "unavailable_lots", "TP", "FP", "FN", "TN", "precision", "recall", "specificity", "false_positive_rate", "false_alarms_per_100_lots", "alerts_per_100_lots", "F1", "prevalence", "detected_failures", "median_detection_latency_hours", "p90_detection_latency_hours", "median_hours_saved", "p90_hours_saved", "pct_failures_before_manual", "conditional_median_latency_reduction_pct", "overall_latency_reduction_pct", "eligible_only_TP", "eligible_only_FP", "eligible_only_FN", "eligible_only_TN", "eligible_only_precision", "eligible_only_recall", "eligible_only_F1")
_EXCURSION_COLUMNS = ("excursion_id", "start_row", "end_row", "fail_count", "window_lot_count", "start_timestamp", "method", "first_window_alert_row", "first_window_alert_timestamp", "first_failing_alert_row", "first_failing_alert_timestamp", "manual_detection_timestamp", "window_alert_before_manual", "hours_saved", "caught_before_manual")
NO_TUNING_DECLARATION = "No Phase II labels or alert counts changed frozen WE rules, EWMA lambda/L, T2 alpha/UCL, selected sensors, Phase I boundary, thresholds, or predeclared plain-OR method definitions."
SAME_LOT_ASSUMPTION = "A validated artifact timestamp equal to its cleaned-lot timestamp is treated as available at that same lot timestamp; SECOM does not observe compute, queue, or human-response delay."


def manual_detection_timestamp(failure_ts: pd.Timestamp) -> pd.Timestamp:
    """Return 08:00 next calendar day, including a failure exactly at 08:00."""
    return pd.Timestamp(failure_ts.date()) + pd.Timedelta(days=1, hours=8)


def compute_metrics(tp: int, fp: int, fn: int, tn: int) -> dict[str, Any]:
    """Compute lot-level binary metrics without inventing undefined values."""
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    fpr = fp / (fp + tn) if fp + tn else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "precision": precision, "recall": recall, "specificity": specificity, "false_positive_rate": fpr, "false_alarms_per_100_lots": fp / total * 100 if total else None, "alerts_per_100_lots": (tp + fp) / total * 100 if total else None, "F1": f1, "prevalence": (tp + fn) / total if total else None}


def group_excursions(fail_rows: Sequence[int], max_gap_lots: int = EXCURSION_MAX_GAP_LOTS) -> list[list[int]]:
    """Group failures with no more than the declared number of intervening rows."""
    groups, current = [], []
    for row in sorted(fail_rows):
        if current and row - current[-1] > max_gap_lots + 1:
            groups.append(current)
            current = []
        current.append(row)
    return groups + ([current] if current else [])


def run(config_path: str | Path | None = None) -> dict[str, Path]:
    """Score frozen P3 alerts and write the five configured P3-005 reports."""
    config = load_config(config_path)
    paths = _configured_paths(config)
    frame = pd.read_csv(paths["cleaned"], parse_dates=["timestamp"]).reset_index(drop=True)
    _validate_cleaned(frame)
    evidence = {name: _read_json(paths[name]) for name in ("screening", "spc_summary", "ewma_summary", "t2_summary")}
    boundary = _validate_evidence(config, frame, evidence, paths["limits"])
    artifacts = {name: pd.read_csv(paths[name]) for name in ("we", "ewma", "t2_series", "t2_violations")}
    alert_times, t2_available = _validate_artifacts(frame, boundary, artifacts)
    phase2 = frame.iloc[boundary:].copy()
    phase2["source_row"] = np.arange(boundary, len(frame), dtype=int)
    lots = pd.DataFrame({"source_row": phase2["source_row"], "timestamp": phase2["timestamp"], "target": phase2["target"].astype(int)})
    lots["we_alert"] = lots.source_row.isin(alert_times["WE"])
    lots["ewma_alert"] = lots.source_row.isin(alert_times["EWMA"])
    lots["t2_alert"] = lots.source_row.isin(alert_times["T2"])
    lots["t2_available"] = lots.source_row.isin(t2_available)
    lots["we_or_ewma"] = lots.we_alert | lots.ewma_alert
    lots["all_methods_alert"] = lots.we_or_ewma | lots.t2_alert
    flags = {"WE": lots.we_alert.to_numpy(), "EWMA": lots.ewma_alert.to_numpy(), "T2": lots.t2_alert.to_numpy(), "WE+EWMA": lots.we_or_ewma.to_numpy(), "WE+EWMA+T2": lots.all_methods_alert.to_numpy()}
    eligibility = {method: lots.t2_available.to_numpy() if method == "T2" else np.ones(len(lots), dtype=bool) for method in METHODS}
    method_times = _combined_alert_times(lots, alert_times)
    method_rows, failures = _score(lots, flags, eligibility, method_times)
    excursions = _excursions(lots, method_times)
    for output in paths["outputs"].values():
        output.parent.mkdir(parents=True, exist_ok=True)
    lots.loc[:, _LOTS_COLUMNS].to_csv(paths["outputs"]["lots"], index=False, lineterminator="\n")
    pd.DataFrame(failures, columns=_FAILURES_COLUMNS).to_csv(paths["outputs"]["failures"], index=False, lineterminator="\n")
    pd.DataFrame(method_rows, columns=_METHODS_COLUMNS).to_csv(paths["outputs"]["methods"], index=False, lineterminator="\n")
    pd.DataFrame(excursions, columns=_EXCURSION_COLUMNS).to_csv(paths["outputs"]["excursions"], index=False, lineterminator="\n")
    _write_json(paths["outputs"]["summary"], _summary(lots, method_rows, excursions, config))
    return paths["outputs"]


def _configured_paths(config: Mapping[str, Any]) -> dict[str, Any]:
    spc, backtest = config["spc"], config.get("backtest", {})
    if set(backtest.get("outputs", {})) < set(_OUTPUT_KEYS):
        raise ValueError("backtest.outputs must define all five P3-005 reports.")
    if int(backtest.get("excursion_max_gap_lots", -1)) != EXCURSION_MAX_GAP_LOTS:
        raise ValueError("backtest excursion grouping is frozen at two intervening lots.")
    return {"cleaned": _resolve(config["secom"]["outputs"]["cleaned_data"]), "screening": _resolve(config["screening"]["outputs"]["summary"]), "limits": _resolve(spc["outputs"]["limits"]), "we": _resolve(spc["outputs"]["violations"]), "ewma": _resolve(spc["outputs"]["ewma_violations"]), "spc_summary": _resolve(spc["outputs"]["summary"]), "ewma_summary": _resolve(spc["outputs"]["ewma_summary"]), "t2_series": _resolve(spc["outputs"]["hotelling_t2_series"]), "t2_violations": _resolve(spc["outputs"]["hotelling_t2_violations"]), "t2_summary": _resolve(spc["outputs"]["hotelling_t2_summary"]), "outputs": {key: _resolve(backtest["outputs"][key]) for key in _OUTPUT_KEYS}}


def _validate_cleaned(frame: pd.DataFrame) -> None:
    if not {"timestamp", "target"}.issubset(frame):
        raise ValueError("SECOM cleaned data must contain timestamp and target.")
    if len(frame) != FROZEN_PHASE1_LOTS + FROZEN_PHASE2_LOTS:
        raise ValueError("SECOM cleaned data must contain the frozen 1,567 lots.")
    if frame.timestamp.isna().any() or not frame.timestamp.is_monotonic_increasing:
        raise ValueError("SECOM cleaned timestamps must be present and non-decreasing.")
    if not frame.target.isin([0, 1]).all():
        raise ValueError("SECOM cleaned target must be binary 0/1.")


def _validate_evidence(config: Mapping[str, Any], frame: pd.DataFrame, evidence: Mapping[str, Mapping[str, Any]], limits_path: Path) -> int:
    boundary = int(len(frame) * float(config["spc"]["phase_i_fraction"]))
    if boundary != FROZEN_PHASE1_LOTS or not np.isclose(float(config["screening"]["window_fraction"]), 0.3):
        raise ValueError("P3-005 requires the frozen 30% / 470-lot Phase I boundary.")
    boundary_ts, sensors = str(frame.timestamp.iloc[boundary - 1]), list(FROZEN_SELECTED_SENSORS)
    for name, timestamp_key in (("screening", "window_boundary_timestamp"), ("spc_summary", "phase1_boundary_timestamp"), ("ewma_summary", "phase1_boundary_timestamp"), ("t2_summary", "phase1_boundary_timestamp")):
        if list(evidence[name].get("selected_sensors", [])) != sensors or str(evidence[name].get(timestamp_key)) != boundary_ts:
            raise ValueError(f"{name} selected-sensor or boundary evidence does not match P3-001.")
    if int(evidence["screening"].get("screening_rows", -1)) != boundary or int(evidence["spc_summary"].get("phase1_lots", -1)) != boundary:
        raise ValueError("P3-001/P3-002 Phase I evidence mismatch.")
    if int(evidence["t2_summary"].get("phase1_lots", -1)) != boundary or int(evidence["t2_summary"].get("phase2_lots", -1)) != FROZEN_PHASE2_LOTS:
        raise ValueError("P3-004 Phase I/II evidence mismatch.")
    if not np.isclose(float(config["spc"]["ewma_lambda"]), FROZEN_EWMA_LAMBDA) or not np.isclose(float(config["spc"]["ewma_L"]), FROZEN_EWMA_L) or not np.isclose(float(evidence["ewma_summary"].get("lambda")), FROZEN_EWMA_LAMBDA) or not np.isclose(float(evidence["ewma_summary"].get("L")), FROZEN_EWMA_L):
        raise ValueError("EWMA lambda/L evidence does not match the frozen P3-003 parameters.")
    if not np.isclose(float(config["spc"]["hotelling_t2_alpha"]), FROZEN_T2_ALPHA) or not np.isclose(float(evidence["t2_summary"].get("alpha")), FROZEN_T2_ALPHA) or not np.isclose(float(evidence["t2_summary"].get("ucl")), FROZEN_T2_UCL):
        raise ValueError("T2 alpha/UCL evidence does not match frozen P3-004 parameters.")
    if set(pd.read_csv(limits_path).get("sensor", [])) != set(sensors):
        raise ValueError("P3-002 limits do not cover exactly the frozen P3-001 sensors.")
    return boundary


def _validate_artifacts(frame: pd.DataFrame, boundary: int, artifacts: Mapping[str, pd.DataFrame]) -> tuple[dict[str, dict[int, pd.Timestamp]], set[int]]:
    selected = set(FROZEN_SELECTED_SENSORS)
    we = _validate_violations(artifacts["we"], frame, boundary, "WE", selected, allow_duplicates=True)
    ewma_frame = artifacts["ewma"]
    ewma = _validate_violations(ewma_frame, frame, boundary, "EWMA", selected, allow_duplicates=True)
    if not ewma_frame.empty and (not np.isclose(pd.to_numeric(ewma_frame["lambda"]), FROZEN_EWMA_LAMBDA).all() or not np.isclose(pd.to_numeric(ewma_frame["L"]), FROZEN_EWMA_L).all()):
        raise ValueError("EWMA violation parameters do not match frozen lambda/L.")
    if not artifacts["we"].empty and not set(artifacts["we"]["rule"]).issubset({"WE1", "WE2", "WE3", "WE4"}):
        raise ValueError("WE artifact contains an unknown rule.")
    series = artifacts["t2_series"]
    required = {"source_row", "timestamp", "phase", "complete_case", "ucl", "violation"}
    if not required.issubset(series):
        raise ValueError("T2 series is missing required frozen-artifact columns.")
    rows = _integer_rows(series.source_row, "T2 series")
    if len(set(rows)) != len(rows) or set(rows) != set(range(len(frame))):
        raise ValueError("T2 series must contain every cleaned source_row exactly once.")
    series = series.assign(source_row=rows).sort_values("source_row").reset_index(drop=True)
    if not pd.to_datetime(series.timestamp, errors="coerce").equals(frame.timestamp):
        raise ValueError("T2 series timestamps do not align with cleaned SECOM lots.")
    phases = np.where(np.arange(len(frame)) < boundary, "Phase I", "Phase II")
    if not (series.phase.to_numpy() == phases).all() or not np.isclose(pd.to_numeric(series.ucl, errors="coerce"), FROZEN_T2_UCL).all():
        raise ValueError("T2 series phase or UCL does not match frozen P3-004 evidence.")
    complete = _booleans(series.complete_case, "T2 complete_case")
    violated = _booleans(series.violation, "T2 violation")
    phase2_violated_rows = set(series.loc[(series.source_row >= boundary) & violated, "source_row"].astype(int))
    if bool(((series.source_row < boundary) & violated).any()):
        raise ValueError("T2 series must not contain a Phase I violation row.")
    if bool((violated & ~complete).any()):
        raise ValueError("T2 series violation rows must be complete-case.")
    available = set(series.loc[(series.source_row >= boundary) & complete, "source_row"].astype(int))
    if len(available) != FROZEN_T2_COMPLETE_PHASE2_LOTS:
        raise ValueError("T2 Phase II complete-case coverage must be the frozen 901/196 lots.")
    t2_frame = artifacts["t2_violations"]
    t2 = _validate_violations(t2_frame, frame, boundary, "T2", selected, allow_duplicates=False, require_sensor=False)
    if not t2_frame.empty and not np.isclose(pd.to_numeric(t2_frame.ucl, errors="coerce"), FROZEN_T2_UCL).all():
        raise ValueError("T2 violation UCL does not match frozen P3-004 evidence.")
    by_row = series.set_index("source_row")
    for row in t2:
        if not bool(complete.iloc[by_row.index.get_loc(row)]) or not bool(violated.iloc[by_row.index.get_loc(row)]):
            raise ValueError("T2 violation is not a complete-case T2 series violation.")
    if set(t2) != phase2_violated_rows:
        raise ValueError("T2 violation artifact row set does not exactly match Phase II T2 series violations.")
    return {"WE": we, "EWMA": ewma, "T2": t2}, available


def _validate_violations(artifact: pd.DataFrame, frame: pd.DataFrame, boundary: int, name: str, selected: set[str], allow_duplicates: bool, require_sensor: bool = True) -> dict[int, pd.Timestamp]:
    required = {"source_row", "timestamp", "phase"} | ({"sensor"} if require_sensor else set())
    if not required.issubset(artifact):
        raise ValueError(f"{name} artifact is missing required columns.")
    if artifact.empty:
        return {}
    rows = _integer_rows(artifact.source_row, name)
    if not allow_duplicates and len(set(rows)) != len(rows):
        raise ValueError(f"{name} artifact source_row values must be unique.")
    if min(rows) < boundary or max(rows) >= len(frame):
        raise ValueError(f"{name} artifact contains stale or out-of-range Phase II source_row values.")
    timestamps = pd.to_datetime(artifact.timestamp, errors="coerce")
    if not (artifact.phase == "Phase II").all() or timestamps.isna().any() or not timestamps.reset_index(drop=True).equals(frame.loc[rows, "timestamp"].reset_index(drop=True)):
        raise ValueError(f"{name} artifact timestamps or phase do not align with cleaned Phase II lots.")
    if require_sensor and not set(artifact.sensor).issubset(selected):
        raise ValueError(f"{name} artifact includes a sensor outside the frozen selection.")
    return {row: pd.Timestamp(timestamp) for row, timestamp in zip(rows, timestamps)}


def _integer_rows(values: pd.Series, name: str) -> list[int]:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not np.equal(numeric, np.floor(numeric)).all():
        raise ValueError(f"{name} source_row values must be non-null integers.")
    return numeric.astype(int).tolist()


def _booleans(values: pd.Series, name: str) -> pd.Series:
    parsed = values.map(lambda value: value if isinstance(value, (bool, np.bool_)) else {"true": True, "false": False}.get(str(value).lower()))
    if parsed.isna().any():
        raise ValueError(f"{name} values must be boolean.")
    return parsed.astype(bool)


def _combined_alert_times(lots: pd.DataFrame, source_times: Mapping[str, Mapping[int, pd.Timestamp]]) -> dict[str, dict[int, pd.Timestamp]]:
    result = {name: dict(value) for name, value in source_times.items()}
    for method, components in (("WE+EWMA", ("WE", "EWMA")), ("WE+EWMA+T2", ("WE", "EWMA", "T2"))):
        result[method] = {}
        for row in lots.source_row:
            candidates = [source_times[item][int(row)] for item in components if int(row) in source_times[item]]
            if candidates:
                result[method][int(row)] = min(candidates)
    return result


def _score(lots: pd.DataFrame, flags: Mapping[str, np.ndarray], eligibility: Mapping[str, np.ndarray], alert_times: Mapping[str, Mapping[int, pd.Timestamp]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    targets, failures, method_rows = lots.target.to_numpy(dtype=int), [], []
    source_index = {int(row): index for index, row in enumerate(lots.source_row)}
    for method in METHODS:
        flag, eligible = flags[method], eligibility[method]
        metrics, eligible_metrics = _matrix(flag, targets), _matrix(flag[eligible], targets[eligible])
        new_latencies, saved_hours, reductions, caught = [], [], [], 0
        for lot in lots.loc[lots.target == 1].itertuples(index=False):
            row, failure_ts = int(lot.source_row), pd.Timestamp(lot.timestamp)
            manual_ts = manual_detection_timestamp(failure_ts)
            manual_hours = (manual_ts - failure_ts).total_seconds() / 3600
            alert_ts = alert_times[method].get(row)
            alerted = alert_ts is not None
            if alerted:
                new_latency = (alert_ts - failure_ts).total_seconds() / 3600
                saved, reduction = manual_hours - new_latency, (manual_hours - new_latency) / manual_hours * 100
                new_latencies.append(new_latency); saved_hours.append(saved); reductions.append(reduction); caught += int(alert_ts < manual_ts)
            else:
                new_latency = saved = reduction = None
            failures.append({"source_row": row, "timestamp": str(failure_ts), "method": method, "method_eligible": bool(eligible[source_index[row]]), "alerted": alerted, "alert_timestamp": str(alert_ts) if alerted else None, "manual_detection_timestamp": str(manual_ts), "manual_latency_hours": manual_hours, "new_latency_hours": new_latency, "hours_saved": saved, "latency_reduction_pct": reduction})
        failure_count = int((targets == 1).sum())
        method_rows.append({"method": method, "population_lots": len(lots), "eligible_lots": int(eligible.sum()), "unavailable_lots": int((~eligible).sum()), **metrics, "detected_failures": len(new_latencies), "median_detection_latency_hours": _median(new_latencies), "p90_detection_latency_hours": _p90(new_latencies), "median_hours_saved": _median(saved_hours), "p90_hours_saved": _p90(saved_hours), "pct_failures_before_manual": caught / failure_count * 100 if failure_count else None, "conditional_median_latency_reduction_pct": _median(reductions), "overall_latency_reduction_pct": _median(reductions) if len(new_latencies) == failure_count else None, "eligible_only_TP": eligible_metrics["TP"], "eligible_only_FP": eligible_metrics["FP"], "eligible_only_FN": eligible_metrics["FN"], "eligible_only_TN": eligible_metrics["TN"], "eligible_only_precision": eligible_metrics["precision"], "eligible_only_recall": eligible_metrics["recall"], "eligible_only_F1": eligible_metrics["F1"]})
    return method_rows, failures


def _matrix(flags: np.ndarray, targets: np.ndarray) -> dict[str, Any]:
    return compute_metrics(int(np.sum(flags & (targets == 1))), int(np.sum(flags & (targets == 0))), int(np.sum(~flags & (targets == 1))), int(np.sum(~flags & (targets == 0))))


def _median(values: Sequence[float]) -> float | None:
    return float(np.median(values)) if values else None


def _p90(values: Sequence[float]) -> float | None:
    return float(np.percentile(values, 90)) if values else None


def _excursions(lots: pd.DataFrame, alert_times: Mapping[str, Mapping[int, pd.Timestamp]]) -> list[dict[str, Any]]:
    lookup, results = lots.set_index("source_row"), []
    for excursion_id, members in enumerate(group_excursions(lots.loc[lots.target == 1, "source_row"].tolist()), start=1):
        start, end = members[0], members[-1]
        start_ts, manual_ts = pd.Timestamp(lookup.loc[start, "timestamp"]), manual_detection_timestamp(pd.Timestamp(lookup.loc[start, "timestamp"]))
        for method in METHODS:
            window_candidates = [(row, timestamp) for row, timestamp in alert_times[method].items() if start <= row <= end]
            failing_candidates = [(row, timestamp) for row, timestamp in window_candidates if row in members]
            if window_candidates:
                window_row, window_ts = min(window_candidates, key=lambda item: item[1])
                window_caught = window_ts < manual_ts
            else:
                window_row = window_ts = None; window_caught = False
            if failing_candidates:
                failing_row, failing_ts = min(failing_candidates, key=lambda item: item[1])
                saved, caught = (manual_ts - failing_ts).total_seconds() / 3600, failing_ts < manual_ts
            else:
                failing_row = failing_ts = saved = None; caught = False
            results.append({"excursion_id": excursion_id, "start_row": start, "end_row": end, "fail_count": len(members), "window_lot_count": end - start + 1, "start_timestamp": str(start_ts), "method": method, "first_window_alert_row": window_row, "first_window_alert_timestamp": str(window_ts) if window_ts is not None else None, "first_failing_alert_row": failing_row, "first_failing_alert_timestamp": str(failing_ts) if failing_ts is not None else None, "manual_detection_timestamp": str(manual_ts), "window_alert_before_manual": window_caught, "hours_saved": saved, "caught_before_manual": caught})
    return results


def _summary(lots: pd.DataFrame, method_rows: Sequence[Mapping[str, Any]], excursions: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    methods = {row["method"]: _jsonable(row) for row in method_rows}
    assessment = {}
    for method, row in methods.items():
        precision_met = row["precision"] is not None and row["precision"] >= 0.60
        latency_met = row["conditional_median_latency_reduction_pct"] is not None and row["conditional_median_latency_reduction_pct"] >= 70
        complete = row["detected_failures"] == int((lots.target == 1).sum())
        assessment[method] = {"precision_threshold": 0.60, "precision_met": precision_met, "latency_reduction_threshold_pct": 70.0, "latency_reduction_met_for_detected_failures": latency_met, "latency_reduction_basis": "all Phase II failing lots" if complete else "detected failing lots only; misses remain unscored", "overall_target_status": "achieved" if precision_met and complete and latency_met else "not_achieved"}
    return {"phase1_lots": FROZEN_PHASE1_LOTS, "phase2_lots": int(len(lots)), "phase2_pass": int((lots.target == 0).sum()), "phase2_fail": int((lots.target == 1).sum()), "phase2_prevalence": float((lots.target == 1).mean()), "population_definition": "All 1,097 chronological Phase II SECOM lots; one deduplicated alert decision per lot and method.", "baseline_definition": "Manual detection at 08:00 on the next calendar day after a failing lot, including a failure exactly at 08:00.", "same_lot_alert_availability_assumption": SAME_LOT_ASSUMPTION, "frozen_evidence": {"selected_sensors": list(FROZEN_SELECTED_SENSORS), "phase1_boundary": FROZEN_PHASE1_LOTS, "ewma": {"lambda": FROZEN_EWMA_LAMBDA, "L": FROZEN_EWMA_L}, "t2": {"alpha": FROZEN_T2_ALPHA, "ucl": FROZEN_T2_UCL, "complete_case_lots": FROZEN_T2_COMPLETE_PHASE2_LOTS, "unavailable_lots": FROZEN_PHASE2_LOTS - FROZEN_T2_COMPLETE_PHASE2_LOTS}}, "methods": methods, "target_assessment": assessment, "incremental_method_value": _incremental(lots), "excursion_analysis": {"status": "exploratory", "count": len({row["excursion_id"] for row in excursions}), "max_gap_lots": EXCURSION_MAX_GAP_LOTS, "window_alert_definition": "Any alert inside the post-label source-row span, including intervening passing lots.", "failing_lot_catch_definition": "Only the first alert on a failing excursion member determines caught_before_manual and hours_saved."}, "no_tuning_declaration": NO_TUNING_DECLARATION, "limitations": ["SECOM is a historical benchmark, not a live-factory deployment.", "Lot labels are evaluation outcomes, not causal explanations or evidence of prevented defects.", "T2 eligible-only metrics are supplemental; primary confusion counts retain all 1,097 lots.", "A high alert rate or conditional latency result does not establish operational value."], "configured_output_filenames": {key: Path(value).name for key, value in config["backtest"]["outputs"].items()}}


def _incremental(lots: pd.DataFrame) -> dict[str, Any]:
    target, t2, result = lots.target.to_numpy(dtype=int), lots.t2_alert.to_numpy(), {}
    for name, baseline in (("WE", lots.we_alert.to_numpy()), ("WE+EWMA", lots.we_or_ewma.to_numpy())):
        extra = t2 & ~baseline
        result[f"T2_extra_vs_{name}"] = {"extra_alert_lots": int(extra.sum()), "extra_TP": int(np.sum(extra & (target == 1))), "extra_FP": int(np.sum(extra & (target == 0))), "combined_delta_TP": int(np.sum((baseline | t2) & (target == 1)) - np.sum(baseline & (target == 1))), "combined_delta_FP": int(np.sum((baseline | t2) & (target == 0)) - np.sum(baseline & (target == 0)))}
    return result


def _read_json(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping): return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_jsonable(item) for item in value]
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return float(value)
    return value


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path(__file__).resolve().parents[1] / path


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as destination:
        json.dump(_jsonable(payload), destination, indent=2, sort_keys=True, ensure_ascii=False)
        destination.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        outputs = run(args.config)
    except Exception as exc:  # pragma: no cover
        print(f"SPC backtest failed: {exc}", file=sys.stderr)
        return 1
    for key in _OUTPUT_KEYS:
        print(f"{key}: {outputs[key]}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
