"""SPC engine: univariate I-MR/WE/EWMA plus Hotelling T² multivariate monitoring.

Integration points for later phases: compute_imr_limits, evaluate_we_rules,
compute_ewma, and estimate_t2_reference/t2_statistic/t2_ucl are pure functions
over ordered arrays; the Phase II observation frames carry lot identity for
P3-005 backtesting.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import f as f_dist

from src.config_loader import load_config


_OUTPUT_KEYS = ("limits", "violations", "p_chart", "summary", "ewma_violations", "ewma_series", "ewma_summary",
                 "hotelling_t2_series", "hotelling_t2_violations", "hotelling_t2_summary")
_LIMIT_COLUMNS = (
    "sensor",
    "phase1_valid_n",
    "phase1_mean",
    "mrbar",
    "sigma_estimate",
    "i_lcl",
    "i_ucl",
    "mr_lcl",
    "mr_ucl",
    "status",
)
_VIOLATION_COLUMNS = (
    "sensor",
    "source_row",
    "timestamp",
    "value",
    "rule",
    "centerline",
    "sigma",
    "z_score",
    "phase",
    "window_start_row",
    "window_end_row",
)
_PCHART_COLUMNS = (
    "date",
    "total_lots",
    "fail_lots",
    "defect_rate",
    "pbar",
    "lcl",
    "ucl",
    "low_volume",
    "violation",
)
_EWMA_VIOLATION_COLUMNS = (
    "sensor",
    "source_row",
    "timestamp",
    "raw_value",
    "ewma_value",
    "centerline",
    "sigma_reference",
    "lambda",
    "L",
    "ewma_lcl",
    "ewma_ucl",
    "direction",
    "phase",
    "valid_observation_index",
)
_EWMA_SERIES_COLUMNS = (
    "sensor",
    "source_row",
    "timestamp",
    "raw_value",
    "ewma_value",
    "ewma_lcl",
    "ewma_ucl",
    "violation",
)
_T2_SERIES_COLUMNS = (
    "source_row",
    "timestamp",
    "phase",
    "complete_case",
    "t2",
    "ucl",
    "violation",
)
_T2_VIOLATION_COLUMNS = (
    "source_row",
    "timestamp",
    "t2",
    "ucl",
    "exceedance_ratio",
    "phase",
)


class CovarianceError(ValueError):
    """Singular or unsafe Phase I covariance: no silent fallback."""

METHODOLOGY = (
    "Phase I/II split reuses the exact P3-001 chronological 30% boundary"
    " (asserted against the screening summary). Sensor I-MR limits use Phase I"
    " pass-lot valid values only: center = Phase I mean, sigma = MRbar/d2 with"
    " d2 = 1.128 for n = 2, MR UCL = D4*MRbar, MR LCL = D3*MRbar. Western"
    " Electric Rules 1-4 evaluate Phase II valid observations in order; windows"
    " form over consecutive valid observations per sensor (missing values break"
    " no window explicitly but are skipped, preserving lot identity; no"
    " imputation). The p-chart baseline uses ALL Phase I lots with variable"
    " daily limits clipped to [0, 1]; low-volume days are flagged, never removed."
)

LIMITATIONS = (
    "P3-001 found no sensor significant at FDR < 0.05, so the 10 selected"
    " sensors are exploratory candidates, not confirmed root causes. Limits and"
    " rules were not tuned against Phase II fail labels; Phase II stays"
    " out-of-sample. MR-based sigma assumes short-term stability of Phase I."
)


def compute_imr_limits(
    values: np.ndarray,
    min_n: int,
    d2: float,
    d3: float,
    d4: float,
) -> dict[str, Any]:
    """Compute I-MR limits from ordered Phase I values.

    Returns mean, mrbar, sigma, limits, valid n, and a status string:
    'ok', 'insufficient_data', or 'zero_variation'.
    """

    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    if clean.size < min_n:
        return {
            "n": int(clean.size), "mean": np.nan, "mrbar": np.nan,
            "sigma": np.nan, "i_lcl": np.nan, "i_ucl": np.nan,
            "mr_lcl": np.nan, "mr_ucl": np.nan, "status": "insufficient_data",
        }
    mean = float(np.mean(clean))
    mrbar = float(np.mean(np.abs(np.diff(clean)))) if clean.size >= 2 else 0.0
    if not np.isfinite(mrbar) or mrbar <= 0:
        return {
            "n": int(clean.size), "mean": mean, "mrbar": float(mrbar),
            "sigma": 0.0, "i_lcl": mean, "i_ucl": mean,
            "mr_lcl": float(d3) * float(mrbar), "mr_ucl": float(d4) * float(mrbar),
            "status": "zero_variation",
        }
    sigma = mrbar / d2
    return {
        "n": int(clean.size), "mean": mean, "mrbar": mrbar, "sigma": sigma,
        "i_lcl": mean - 3.0 * sigma, "i_ucl": mean + 3.0 * sigma,
        "mr_lcl": d3 * mrbar, "mr_ucl": d4 * mrbar, "status": "ok",
    }


def compute_ewma(
    values: np.ndarray,
    mean: float,
    sigma: float,
    lam: float,
    limit_width: float,
    time_varying: bool = True,
) -> dict[str, np.ndarray]:
    """Run the EWMA recursion over ordered valid observations.

    z_t = lam * x_t + (1 - lam) * z_{t-1} with z_0 = mean. Control limits use
    the time-varying startup variance sigma_z(t); with time_varying=False the
    steady-state width applies from t = 1. Returns ewma, lcl, ucl arrays plus
    a boolean violation mask (z outside [lcl, ucl]).
    """

    if not 0 < lam <= 1:
        raise ValueError("EWMA lambda must be in (0, 1].")
    if not np.isfinite(limit_width) or limit_width <= 0:
        raise ValueError("EWMA limit width L must be positive.")
    values = np.asarray(values, dtype=float)
    count = values.size
    empty = {
        "ewma": np.empty(0), "lcl": np.empty(0), "ucl": np.empty(0),
        "violation": np.empty(0, dtype=bool),
    }
    if count == 0 or not np.isfinite(sigma) or sigma <= 0:
        return empty
    steps = np.arange(1, count + 1)
    if time_varying:
        width = np.sqrt(lam / (2.0 - lam) * (1.0 - (1.0 - lam) ** (2 * steps)))
    else:
        width = np.full(count, np.sqrt(lam / (2.0 - lam)))
    ewma = np.empty(count)
    running = float(mean)
    for position in range(count):
        running = lam * float(values[position]) + (1.0 - lam) * running
        ewma[position] = running
    lcl = mean - limit_width * sigma * width
    ucl = mean + limit_width * sigma * width
    return {
        "ewma": ewma, "lcl": lcl, "ucl": ucl,
        "violation": (ewma > ucl) | (ewma < lcl),
    }


def estimate_t2_reference(
    values: np.ndarray, sensors: Sequence[str]
) -> dict[str, Any]:
    """Estimate the Hotelling T² reference from Phase I pass complete cases.

    Standardizes with Phase I means/stds, uses the conventional sample
    covariance (ddof = 1), and refuses singular covariance instead of
    silently falling back to a pseudoinverse.
    """

    matrix = np.asarray(values, dtype=float)
    count, dim = matrix.shape
    if count <= dim:
        raise CovarianceError(
            f"T² reference needs n > p, got n = {count}, p = {dim}."
        )
    mean = np.mean(matrix, axis=0)
    std = np.std(matrix, axis=0, ddof=1)
    frozen = [name for name, value in zip(sensors, std, strict=True) if value == 0]
    if frozen:
        raise CovarianceError(f"Zero-variance Phase I dimensions: {frozen}.")
    standardized = (matrix - mean) / std
    covariance = np.atleast_2d(np.cov(standardized, rowvar=False))
    rank = int(np.linalg.matrix_rank(covariance))
    if rank < dim:
        raise CovarianceError(
            f"Singular Phase I covariance: rank {rank} < p {dim}; no pseudoinverse fallback."
        )
    return {
        "mean": mean,
        "std": std,
        "ref_mean": np.mean(standardized, axis=0),
        "covariance": covariance,
        "rank": rank,
        "condition_number": float(np.linalg.cond(covariance)),
        "n": count,
        "p": dim,
    }


def t2_statistic(
    values: np.ndarray, reference: Mapping[str, Any]
) -> np.ndarray:
    """Compute Hotelling T² for rows standardized with the Phase I reference."""

    matrix = np.asarray(values, dtype=float)
    deviations = (matrix - reference["mean"]) / reference["std"]
    centered = deviations - reference["ref_mean"]
    solved = np.linalg.solve(reference["covariance"], centered.T).T
    return np.einsum("ij,ij->i", centered, solved)


def t2_ucl(dim: int, count: int, alpha: float) -> float:
    """Finite-sample F-based UCL for one future T² observation."""

    if dim <= 0 or count <= dim:
        raise ValueError("T² UCL needs 0 < p < n.")
    if not 0 < alpha < 1:
        raise ValueError("T² alpha must be in (0, 1).")
    return (
        dim * (count + 1) * (count - 1) / (count * (count - dim))
        * float(f_dist.ppf(1.0 - alpha, dim, count - dim))
    )


def evaluate_we_rules(    values: np.ndarray,
    rows: np.ndarray,
    timestamps: np.ndarray,
    mean: float,
    sigma: float,
    sensor: str,
) -> list[dict[str, Any]]:
    """Evaluate Western Electric Rules 1-4 over ordered valid observations.

    values/rows/timestamps describe consecutive valid observations for one
    sensor (missing values already removed, identities preserved). Returns one
    record per (rule, trigger position); several rules may fire on one point.
    """

    records: list[dict[str, Any]] = []
    values = np.asarray(values, dtype=float)
    count = values.size
    if count == 0 or not np.isfinite(sigma) or sigma <= 0:
        return records
    zscores = (values - mean) / sigma

    def record(position: int, rule: str, start: int) -> None:
        records.append(
            {
                "sensor": sensor,
                "source_row": int(rows[position]),
                "timestamp": str(timestamps[position]),
                "value": float(values[position]),
                "rule": rule,
                "centerline": float(mean),
                "sigma": float(sigma),
                "z_score": float(zscores[position]),
                "phase": "Phase II",
                "window_start_row": int(rows[start]),
                "window_end_row": int(rows[position]),
            }
        )

    for i in range(count):
        if abs(zscores[i]) > 3:
            record(i, "WE1", i)
    for i in range(2, count):
        window = zscores[i - 2 : i + 1]
        if int(np.sum(window > 2)) >= 2:
            record(i, "WE2", i - 2)
        elif int(np.sum(window < -2)) >= 2:
            record(i, "WE2", i - 2)
    for i in range(4, count):
        window = zscores[i - 4 : i + 1]
        if int(np.sum(window > 1)) >= 4:
            record(i, "WE3", i - 4)
        elif int(np.sum(window < -1)) >= 4:
            record(i, "WE3", i - 4)
    for i in range(7, count):
        window = zscores[i - 7 : i + 1]
        if bool(np.all(window > 0)) or bool(np.all(window < 0)):
            record(i, "WE4", i - 7)
    return records


def run(config_path: str | Path | None = None) -> dict[str, Path]:
    """Compute I-MR limits, WE violations, EWMA monitoring, and the p-chart."""

    config = load_config(config_path)
    spc = _spc_config(config)
    screening = config.get("screening", {})
    ranking_path = _resolve_configured_path(screening["outputs"]["ranking"])
    summary_path = _resolve_configured_path(screening["outputs"]["summary"])
    screening_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    ranking = pd.read_csv(ranking_path)
    selected = ranking.loc[ranking["selected"], "sensor"].tolist()
    if not selected:
        raise ValueError("Feature screening selected no sensors.")

    cleaned_path = _resolve_configured_path(config["secom"]["outputs"]["cleaned_data"])
    frame = pd.read_csv(cleaned_path, parse_dates=["timestamp"])
    if (frame["timestamp"].diff().dropna() < pd.Timedelta(0)).any():
        raise ValueError("SECOM cleaned file must be timestamp-ordered.")
    frame = frame.reset_index(drop=True)
    total_rows = len(frame)
    boundary_rows = int(total_rows * float(spc["phase1_fraction"]))
    if boundary_rows != int(screening_summary["screening_rows"]):
        raise ValueError(
            "Phase I boundary does not match P3-001 screening evidence: "
            f"{boundary_rows} != {screening_summary['screening_rows']}."
        )
    boundary_ts = frame["timestamp"].iloc[boundary_rows - 1]
    if str(boundary_ts) != str(screening_summary["window_boundary_timestamp"]):
        raise ValueError("Phase I boundary timestamp does not match P3-001 evidence.")
    phase1 = frame.iloc[:boundary_rows]
    phase2 = frame.iloc[boundary_rows:]
    phase1_pass = phase1[phase1["target"] == 0]

    d2, d3, d4 = float(spc["mr_d2"]), float(spc["mr_d3"]), float(spc["mr_d4"])
    min_n = int(spc["min_phase1_observations"])
    lam = float(spc["ewma_lambda"])
    limit_width = float(spc["ewma_L"])
    time_varying = bool(spc["ewma_use_time_varying_limits"])
    if not 0 < lam <= 1:
        raise ValueError("Configuration spc.ewma_lambda must be in (0, 1].")
    if not np.isfinite(limit_width) or limit_width <= 0:
        raise ValueError("Configuration spc.ewma_L must be positive.")
    limit_rows: list[dict[str, Any]] = []
    violation_rows: list[dict[str, Any]] = []
    ewma_violation_rows: list[dict[str, Any]] = []
    ewma_series_rows: list[dict[str, Any]] = []
    invalid: dict[str, str] = {}
    for sensor in selected:
        valid = pd.to_numeric(phase1_pass[sensor], errors="coerce").dropna().to_numpy(dtype=float)
        limits = compute_imr_limits(valid, min_n, d2, d3, d4)
        limit_rows.append(
            {
                "sensor": sensor,
                "phase1_valid_n": limits["n"],
                "phase1_mean": limits["mean"],
                "mrbar": limits["mrbar"],
                "sigma_estimate": limits["sigma"],
                "i_lcl": limits["i_lcl"],
                "i_ucl": limits["i_ucl"],
                "mr_lcl": limits["mr_lcl"],
                "mr_ucl": limits["mr_ucl"],
                "status": limits["status"],
            }
        )
        if limits["status"] != "ok":
            invalid[sensor] = limits["status"]
            continue
        series = pd.to_numeric(phase2[sensor], errors="coerce")
        mask = series.notna().to_numpy()
        valid_values = series[mask].to_numpy(dtype=float)
        valid_rows = phase2.index[mask].to_numpy()
        valid_ts = phase2["timestamp"][mask].to_numpy()
        violation_rows.extend(
            evaluate_we_rules(
                valid_values,
                valid_rows,
                valid_ts,
                limits["mean"],
                limits["sigma"],
                sensor,
            )
        )
        ewma = compute_ewma(
            valid_values, limits["mean"], limits["sigma"], lam, limit_width,
            time_varying=time_varying,
        )
        for position in range(valid_values.size):
            violated = bool(ewma["violation"][position])
            ewma_series_rows.append(
                {
                    "sensor": sensor,
                    "source_row": int(valid_rows[position]),
                    "timestamp": str(valid_ts[position]),
                    "raw_value": float(valid_values[position]),
                    "ewma_value": float(ewma["ewma"][position]),
                    "ewma_lcl": float(ewma["lcl"][position]),
                    "ewma_ucl": float(ewma["ucl"][position]),
                    "violation": violated,
                }
            )
            if violated:
                ewma_violation_rows.append(
                    {
                        "sensor": sensor,
                        "source_row": int(valid_rows[position]),
                        "timestamp": str(valid_ts[position]),
                        "raw_value": float(valid_values[position]),
                        "ewma_value": float(ewma["ewma"][position]),
                        "centerline": float(limits["mean"]),
                        "sigma_reference": float(limits["sigma"]),
                        "lambda": lam,
                        "L": limit_width,
                        "ewma_lcl": float(ewma["lcl"][position]),
                        "ewma_ucl": float(ewma["ucl"][position]),
                        "direction": "up"
                        if ewma["ewma"][position] > ewma["ucl"][position]
                        else "down",
                        "phase": "Phase II",
                        "valid_observation_index": int(position + 1),
                    }
                )
    limits_frame = pd.DataFrame(limit_rows, columns=_LIMIT_COLUMNS)
    violations = pd.DataFrame(violation_rows, columns=_VIOLATION_COLUMNS)
    if not violations.empty:
        order = {sensor: position for position, sensor in enumerate(selected)}
        violations["sensor_order"] = violations["sensor"].map(order)
        violations = violations.sort_values(
            ["sensor_order", "rule", "timestamp"]
        ).drop(columns=["sensor_order"]).reset_index(drop=True)

    pchart = _p_chart(frame, boundary_rows, int(spc["p_chart_min_daily_n"]))

    ewma_violations = pd.DataFrame(ewma_violation_rows, columns=_EWMA_VIOLATION_COLUMNS)
    ewma_series = pd.DataFrame(ewma_series_rows, columns=_EWMA_SERIES_COLUMNS)
    if not ewma_violations.empty:
        order = {sensor: position for position, sensor in enumerate(selected)}
        ewma_violations["sensor_order"] = ewma_violations["sensor"].map(order)
        ewma_violations = ewma_violations.sort_values(
            ["sensor_order", "timestamp"]
        ).drop(columns=["sensor_order"]).reset_index(drop=True)
    if not ewma_series.empty:
        order = {sensor: position for position, sensor in enumerate(selected)}
        ewma_series["sensor_order"] = ewma_series["sensor"].map(order)
        ewma_series = ewma_series.sort_values(
            ["sensor_order", "timestamp"]
        ).drop(columns=["sensor_order"]).reset_index(drop=True)
    overlap = _we_ewma_overlap(violations, ewma_violations, selected)

    alpha = float(spc["hotelling_t2_alpha"])
    try:
        t2_reference: dict[str, Any] | None = _t2_reference(phase1_pass, selected)
        ucl = t2_ucl(len(selected), int(t2_reference["n"]), alpha)
        t2_series_rows, t2_violation_rows = _monitor_t2(
            frame, boundary_rows, selected, t2_reference, ucl
        )
        t2_reference_error: str | None = None
    except CovarianceError as exc:
        # A frozen or rank-deficient Phase I reference (e.g. a flatlined
        # sensor) must not abort univariate monitoring. T² is refused openly:
        # no scores, no violations, identities retained for coverage.
        t2_reference = None
        ucl = float("nan")
        t2_series_rows = _coverage_series(frame, boundary_rows, selected)
        t2_violation_rows = []
        t2_reference_error = str(exc)
    t2_series = pd.DataFrame(t2_series_rows, columns=_T2_SERIES_COLUMNS)
    t2_violations = pd.DataFrame(t2_violation_rows, columns=_T2_VIOLATION_COLUMNS)
    three_way = _three_way_overlap(violations, ewma_violations, t2_violations)

    output_paths = _configured_output_paths(spc)
    for output_path in output_paths.values():
        output_path.parent.mkdir(parents=True, exist_ok=True)
    limits_frame.to_csv(output_paths["limits"], index=False, lineterminator="\n")
    violations.to_csv(output_paths["violations"], index=False, lineterminator="\n")
    pchart.to_csv(output_paths["p_chart"], index=False, lineterminator="\n")
    ewma_violations.to_csv(output_paths["ewma_violations"], index=False, lineterminator="\n")
    ewma_series.to_csv(output_paths["ewma_series"], index=False, lineterminator="\n")
    t2_series.to_csv(output_paths["hotelling_t2_series"], index=False, lineterminator="\n")
    t2_violations.to_csv(output_paths["hotelling_t2_violations"], index=False, lineterminator="\n")
    summary = _build_summary(
        boundary_ts=boundary_ts,
        phase1=phase1,
        phase2=phase2,
        selected=selected,
        invalid=invalid,
        violations=violations,
        pchart=pchart,
        spc=spc,
        output_paths=output_paths,
    )
    _write_json(output_paths["summary"], summary)
    ewma_summary = _build_ewma_summary(
        boundary_ts=boundary_ts,
        selected=selected,
        ewma_violations=ewma_violations,
        ewma_series=ewma_series,
        lam=lam,
        limit_width=limit_width,
        time_varying=time_varying,
        overlap=overlap,
        output_paths=output_paths,
    )
    _write_json(output_paths["ewma_summary"], ewma_summary)
    t2_summary = _build_t2_summary(
        boundary_ts=boundary_ts,
        selected=selected,
        phase1=phase1,
        phase2=phase2,
        reference=t2_reference,
        reference_error=t2_reference_error,
        alpha=alpha,
        ucl=ucl,
        t2_series=t2_series,
        t2_violations=t2_violations,
        three_way=three_way,
        output_paths=output_paths,
    )
    _write_json(output_paths["hotelling_t2_summary"], t2_summary)
    return output_paths


def _t2_reference(
    phase1_pass: pd.DataFrame, selected: Sequence[str]
) -> dict[str, Any]:
    """Estimate the T² reference from Phase I pass complete cases only."""

    complete = phase1_pass.dropna(subset=list(selected))
    matrix = complete[list(selected)].apply(pd.to_numeric, errors="coerce")
    matrix = matrix.dropna()
    reference = estimate_t2_reference(matrix.to_numpy(dtype=float), list(selected))
    reference["phase1_pass_lots"] = int(len(phase1_pass))
    reference["phase1_complete_n"] = int(len(matrix))
    return reference


def _monitor_t2(
    frame: pd.DataFrame,
    boundary_rows: int,
    selected: Sequence[str],
    reference: Mapping[str, Any],
    ucl: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Score every lot; violations come from Phase II complete cases only."""

    series_rows: list[dict[str, Any]] = []
    violation_rows: list[dict[str, Any]] = []
    for position in range(len(frame)):
        row = frame.iloc[position]
        values = pd.to_numeric(row[list(selected)], errors="coerce").to_numpy(dtype=float)
        complete = bool(np.all(np.isfinite(values)))
        phase = "Phase I" if position < boundary_rows else "Phase II"
        t2_value = float(t2_statistic(values.reshape(1, -1), reference)[0]) if complete else np.nan
        violated = complete and phase == "Phase II" and t2_value > ucl
        series_rows.append(
            {
                "source_row": int(position),
                "timestamp": str(row["timestamp"]),
                "phase": phase,
                "complete_case": complete,
                "t2": t2_value,
                "ucl": float(ucl),
                "violation": bool(violated),
            }
        )
        if violated:
            violation_rows.append(
                {
                    "source_row": int(position),
                    "timestamp": str(row["timestamp"]),
                    "t2": t2_value,
                    "ucl": float(ucl),
                    "exceedance_ratio": float(t2_value / ucl),
                    "phase": phase,
                }
            )
    return series_rows, violation_rows


def _coverage_series(
    frame: pd.DataFrame, boundary_rows: int, selected: Sequence[str]
) -> list[dict[str, Any]]:
    """Coverage-only T² series used when no reference could be estimated."""

    rows = []
    for position in range(len(frame)):
        row = frame.iloc[position]
        values = pd.to_numeric(row[list(selected)], errors="coerce").to_numpy(dtype=float)
        rows.append(
            {
                "source_row": int(position),
                "timestamp": str(row["timestamp"]),
                "phase": "Phase I" if position < boundary_rows else "Phase II",
                "complete_case": bool(np.all(np.isfinite(values))),
                "t2": float("nan"),
                "ucl": float("nan"),
                "violation": False,
            }
        )
    return rows


def _three_way_overlap(
    violations: pd.DataFrame,
    ewma_violations: pd.DataFrame,
    t2_violations: pd.DataFrame,
) -> dict[str, int]:
    """Descriptive lot-level overlap between T², WE, and EWMA alerts.

    Counts only; no precision, recall, latency, or ranking (P3-005).
    """

    we_lots = (
        set(zip(violations["sensor"], violations["source_row"]))
        if not violations.empty
        else set()
    )
    we_lots = {row for (_, row) in we_lots}
    ewma_lots = (
        set(zip(ewma_violations["sensor"], ewma_violations["source_row"]))
        if not ewma_violations.empty
        else set()
    )
    ewma_lots = {row for (_, row) in ewma_lots}
    t2_lots = set(t2_violations["source_row"].tolist()) if not t2_violations.empty else set()
    return {
        "t2_lots": len(t2_lots),
        "overlap_we": len(t2_lots & we_lots),
        "overlap_ewma": len(t2_lots & ewma_lots),
        "overlap_both": len(t2_lots & we_lots & ewma_lots),
        "t2_only_lots": len(t2_lots - we_lots - ewma_lots),
    }


def _build_t2_summary(
    *,
    boundary_ts: Any,
    selected: Sequence[str],
    phase1: pd.DataFrame,
    phase2: pd.DataFrame,
    reference: Mapping[str, Any] | None,
    reference_error: str | None,
    alpha: float,
    ucl: float,
    t2_series: pd.DataFrame,
    t2_violations: pd.DataFrame,
    three_way: Mapping[str, int],
    output_paths: Mapping[str, Path],
) -> dict[str, Any]:
    phase1_complete = int(
        t2_series[(t2_series["phase"] == "Phase I") & (t2_series["complete_case"])].shape[0]
    )
    phase2_complete = int(
        t2_series[(t2_series["phase"] == "Phase II") & (t2_series["complete_case"])].shape[0]
    )
    complete_t2 = t2_series.loc[t2_series["complete_case"], "t2"]
    return {
        "phase1_boundary_timestamp": str(boundary_ts),
        "selected_sensors": list(selected),
        "p": len(selected),
        "phase1_lots": int(len(phase1)),
        "phase1_pass_lots": (
            int(reference["phase1_pass_lots"]) if reference is not None else None
        ),
        "phase1_complete_n": int(reference["n"]) if reference is not None else None,
        "phase2_lots": int(len(phase2)),
        "phase2_complete_n": phase2_complete,
        "phase1_coverage": phase1_complete / max(len(phase1), 1),
        "phase2_coverage": phase2_complete / max(len(phase2), 1),
        "alpha": alpha,
        "f_degrees_of_freedom": (
            [len(selected), int(reference["n"]) - len(selected)]
            if reference is not None
            else None
        ),
        "ucl": float(ucl),
        "covariance_rank": int(reference["rank"]) if reference is not None else None,
        "covariance_condition_number": (
            float(reference["condition_number"]) if reference is not None else None
        ),
        "reference_error": reference_error,
        "violation_count": int(len(t2_violations)),
        "first_violation_timestamp": (
            str(t2_violations["timestamp"].min()) if not t2_violations.empty else None
        ),
        "max_t2": (
            float(complete_t2.dropna().max())
            if not complete_t2.dropna().empty
            else None
        ),
        "contribution_diagnostics": (
            "Omitted: per-variable attribution is ambiguous under correlated"
            " covariance, so no contribution column is invented."
        ),
        "overlap": dict(three_way),
        "methodology": (
            "T²(x) = (x - mu)' S^-1 (x - mu) with mu and the conventional"
            " sample covariance S estimated from Phase I pass complete cases"
            " after per-sensor Phase I standardization; the identical Phase I"
            " transform scores Phase II. Control limit is the finite-sample"
            " F-based UCL for one future observation. Incomplete lots are"
            " excluded without imputation and counted in coverage. Overlap"
            " counts are descriptive lot coincidences, not quality metrics."
        ),
        "limitations": (
            "The 10 sensors remain exploratory candidates (P3-001 found no"
            " q < 0.05 sensor); T² violations are multivariate anomalies, not"
            " confirmed defects. No causal interpretation; nothing tuned on"
            " Phase II labels; sensor selection unchanged."
        ),
        "paths": {key: str(path) for key, path in output_paths.items()},
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run univariate SPC as a command-line program."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        output_paths = run(args.config)
    except Exception as exc:  # pragma: no cover - CLI error boundary
        print(f"SPC engine failed: {exc}", file=sys.stderr)
        return 1
    for key in _OUTPUT_KEYS:
        print(f"{key}: {output_paths[key]}")
    return 0


def _p_chart(frame: pd.DataFrame, boundary_rows: int, min_daily_n: int) -> pd.DataFrame:
    """Build the daily p-chart; baseline uses all Phase I lots."""

    phase1 = frame.iloc[:boundary_rows]
    pbar = float((phase1["target"] == 1).sum() / max(len(phase1), 1))
    daily = (
        frame.assign(date=frame["timestamp"].dt.date)
        .groupby("date")
        .agg(total_lots=("target", "size"), fail_lots=("target", lambda s: (s == 1).sum()))
        .reset_index()
    )
    daily["defect_rate"] = daily["fail_lots"] / daily["total_lots"]
    daily["pbar"] = pbar
    sigma = np.sqrt(pbar * (1.0 - pbar) / daily["total_lots"].to_numpy(dtype=float))
    daily["lcl"] = np.maximum(0.0, pbar - 3.0 * sigma)
    daily["ucl"] = np.minimum(1.0, pbar + 3.0 * sigma)
    daily["low_volume"] = daily["total_lots"] < min_daily_n
    daily["violation"] = (daily["defect_rate"] > daily["ucl"]) | (
        daily["defect_rate"] < daily["lcl"]
    )
    daily["date"] = daily["date"].astype(str)
    return daily[list(_PCHART_COLUMNS)]


def _spc_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    section = config.get("spc")
    if not isinstance(section, Mapping):
        raise ValueError("Configuration must contain a mapping at spc.")
    required = {
        "phase1_fraction",
        "mr_d2",
        "mr_d3",
        "mr_d4",
        "sigma_levels",
        "min_phase1_observations",
        "p_chart_min_daily_n",
        "ewma_lambda",
        "ewma_L",
        "ewma_use_time_varying_limits",
        "hotelling_t2_alpha",
    }
    missing = sorted(required.difference(section))
    if missing:
        raise ValueError(f"Configuration spc section is missing: {missing}.")
    if not 0 < float(section["hotelling_t2_alpha"]) < 1:
        raise ValueError("Configuration spc.hotelling_t2_alpha must be in (0, 1).")
    if not 0 < float(section["ewma_lambda"]) <= 1:
        raise ValueError("Configuration spc.ewma_lambda must be in (0, 1].")
    if not np.isfinite(float(section["ewma_L"])) or float(section["ewma_L"]) <= 0:
        raise ValueError("Configuration spc.ewma_L must be positive.")
    if not isinstance(section["ewma_use_time_varying_limits"], bool):
        raise ValueError("Configuration spc.ewma_use_time_varying_limits must be boolean.")
    if not 0 < float(section["phase1_fraction"]) < 1:
        raise ValueError("Configuration spc.phase1_fraction must be in (0, 1).")
    if abs(float(section["phase1_fraction"]) - 0.30) > 1e-9:
        raise ValueError("Configuration spc.phase1_fraction must reuse the 0.30 P3-001 boundary.")
    for key in ("mr_d2", "mr_d3", "mr_d4"):
        if not np.isfinite(float(section[key])):
            raise ValueError(f"Configuration spc.{key} must be finite.")
    if int(section["min_phase1_observations"]) < 2:
        raise ValueError("Configuration spc.min_phase1_observations must be at least 2.")
    if int(section["p_chart_min_daily_n"]) < 1:
        raise ValueError("Configuration spc.p_chart_min_daily_n must be at least 1.")
    outputs = section.get("outputs")
    if not isinstance(outputs, Mapping) or not set(_OUTPUT_KEYS).issubset(outputs):
        raise ValueError(f"Configuration spc.outputs must define: {', '.join(_OUTPUT_KEYS)}.")
    return section


def _we_ewma_overlap(
    violations: pd.DataFrame,
    ewma_violations: pd.DataFrame,
    selected: Sequence[str],
) -> dict[str, dict[str, int]]:
    """Descriptive WE/EWMA overlap per sensor on (sensor, source_row) pairs.

    Counts only; no precision, recall, latency, or quality judgment (P3-005).
    """

    overlap: dict[str, dict[str, int]] = {}
    we_lots = (
        set(zip(violations["sensor"], violations["source_row"]))
        if not violations.empty
        else set()
    )
    ewma_lots = (
        set(zip(ewma_violations["sensor"], ewma_violations["source_row"]))
        if not ewma_violations.empty
        else set()
    )
    for sensor in selected:
        sensor_we = {row for (s, row) in we_lots if s == sensor}
        sensor_ewma = {row for (s, row) in ewma_lots if s == sensor}
        overlap[sensor] = {
            "we_lots": len(sensor_we),
            "ewma_lots": len(sensor_ewma),
            "both_lots": len(sensor_we & sensor_ewma),
            "ewma_only_lots": len(sensor_ewma - sensor_we),
            "we_only_lots": len(sensor_we - sensor_ewma),
        }
    return overlap


def _build_ewma_summary(
    *,
    boundary_ts: Any,
    selected: Sequence[str],
    ewma_violations: pd.DataFrame,
    ewma_series: pd.DataFrame,
    lam: float,
    limit_width: float,
    time_varying: bool,
    overlap: Mapping[str, Mapping[str, int]],
    output_paths: Mapping[str, Path],
) -> dict[str, Any]:
    by_sensor = (
        ewma_violations["sensor"].value_counts().to_dict()
        if not ewma_violations.empty
        else {}
    )
    directions = (
        ewma_violations["direction"].value_counts().to_dict()
        if not ewma_violations.empty
        else {}
    )
    first_violation = (
        ewma_violations.groupby("sensor")["timestamp"].min().to_dict()
        if not ewma_violations.empty
        else {}
    )
    valid_obs = (
        ewma_series.groupby("sensor").size().to_dict() if not ewma_series.empty else {}
    )
    return {
        "phase1_boundary_timestamp": str(boundary_ts),
        "selected_sensors": list(selected),
        "lambda": lam,
        "L": limit_width,
        "time_varying_limits": time_varying,
        "initialization": "z_0 = Phase I pass-only sensor mean",
        "sigma_source": "Phase I MRbar/d2 sigma estimate from spc_limits",
        "valid_observations_per_sensor": {key: int(value) for key, value in valid_obs.items()},
        "violations_per_sensor": {key: int(value) for key, value in by_sensor.items()},
        "total_violations": int(len(ewma_violations)),
        "first_violation_timestamp_per_sensor": {
            key: str(value) for key, value in first_violation.items()
        },
        "direction_counts": {key: int(value) for key, value in directions.items()},
        "we_ewma_overlap_lots": {
            key: dict(value) for key, value in overlap.items()
        },
        "methodology": (
            "EWMA z_t = lambda*x_t + (1-lambda)*z_{t-1} with z_0 = Phase I"
            " pass-only mean; mu/sigma are Phase I only. Limits use the"
            " time-varying startup variance sigma*sqrt(lambda/(2-lambda)*"
            "(1-(1-lambda)^(2t))) with width L. State advances per valid Phase II"
            " observation only (missing values skipped, identities preserved, no"
            " imputation). Overlap counts are descriptive lot-level coincidences"
            " with WE violations, not quality metrics."
        ),
        "limitations": LIMITATIONS,
        "paths": {key: str(path) for key, path in output_paths.items()},
    }


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_configured_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _repository_root() / path


def _configured_output_paths(spc: Mapping[str, Any]) -> dict[str, Path]:
    outputs = spc["outputs"]
    return {key: _resolve_configured_path(outputs[key]) for key in _OUTPUT_KEYS}


def _build_summary(
    *,
    boundary_ts: Any,
    phase1: pd.DataFrame,
    phase2: pd.DataFrame,
    selected: Sequence[str],
    invalid: Mapping[str, str],
    violations: pd.DataFrame,
    pchart: pd.DataFrame,
    spc: Mapping[str, Any],
    output_paths: Mapping[str, Path],
) -> dict[str, Any]:
    by_rule = violations["rule"].value_counts().to_dict() if not violations.empty else {}
    by_sensor = violations["sensor"].value_counts().to_dict() if not violations.empty else {}
    return {
        "phase1_boundary_timestamp": str(boundary_ts),
        "phase1_lots": int(len(phase1)),
        "phase1_pass_lots": int((phase1["target"] == 0).sum()),
        "phase1_fail_lots": int((phase1["target"] == 1).sum()),
        "phase2_lots": int(len(phase2)),
        "selected_sensors": list(selected),
        "valid_charts": int(len(selected) - len(invalid)),
        "invalid_charts": dict(invalid),
        "violations_by_rule": {key: int(value) for key, value in by_rule.items()},
        "violations_by_sensor": {key: int(value) for key, value in by_sensor.items()},
        "total_violations": int(len(violations)),
        "pbar": float(pchart["pbar"].iloc[0]) if len(pchart) else 0.0,
        "pchart_violation_days": int(pchart["violation"].sum()),
        "pchart_low_volume_days": int(pchart["low_volume"].sum()),
        "mr_constants": {
            "d2": float(spc["mr_d2"]),
            "d3": float(spc["mr_d3"]),
            "d4": float(spc["mr_d4"]),
        },
        "methodology": METHODOLOGY,
        "limitations": LIMITATIONS,
        "paths": {key: str(path) for key, path in output_paths.items()},
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output_file:
        json.dump(payload, output_file, indent=2, sort_keys=True, ensure_ascii=False)
        output_file.write("\n")


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
