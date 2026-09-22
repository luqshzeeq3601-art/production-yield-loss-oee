"""Univariate SPC: I-MR limits, Western Electric Rules 1-4, daily p-chart.

Integration points for later phases: compute_imr_limits and
evaluate_we_rules are pure functions over ordered arrays (P3-003 EWMA can
reuse the Phase I/II split and z-score convention); the Phase II valid
observation frames carry lot identity for P3-005 backtesting.
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

from src.config_loader import load_config


_OUTPUT_KEYS = ("limits", "violations", "p_chart", "summary")
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


def evaluate_we_rules(
    values: np.ndarray,
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
    """Compute I-MR limits, WE violations, and the p-chart; write evidence."""

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
    limit_rows: list[dict[str, Any]] = []
    violation_rows: list[dict[str, Any]] = []
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
        violation_rows.extend(
            evaluate_we_rules(
                series[mask].to_numpy(dtype=float),
                phase2.index[mask].to_numpy(),
                phase2["timestamp"][mask].to_numpy(),
                limits["mean"],
                limits["sigma"],
                sensor,
            )
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

    output_paths = _configured_output_paths(spc)
    for output_path in output_paths.values():
        output_path.parent.mkdir(parents=True, exist_ok=True)
    limits_frame.to_csv(output_paths["limits"], index=False, lineterminator="\n")
    violations.to_csv(output_paths["violations"], index=False, lineterminator="\n")
    pchart.to_csv(output_paths["p_chart"], index=False, lineterminator="\n")
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
    return output_paths


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
    }
    missing = sorted(required.difference(section))
    if missing:
        raise ValueError(f"Configuration spc section is missing: {missing}.")
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
