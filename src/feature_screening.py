"""Statistical feature screening: rank SECOM sensors by pass/fail association."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from src.config_loader import load_config


_OUTPUT_KEYS = ("ranking", "summary")
_CSV_COLUMNS = (
    "sensor",
    "valid_pass_n",
    "valid_fail_n",
    "missing_rate",
    "point_biserial_r",
    "abs_point_biserial_r",
    "ks_statistic",
    "ks_pvalue",
    "ks_qvalue",
    "mannwhitney_statistic",
    "mannwhitney_pvalue",
    "mannwhitney_qvalue",
    "effect_size",
    "aggregate_rank",
    "redundant_with",
    "selected",
)

METHODOLOGY = (
    "Screening uses the first window_fraction of lots in timestamp order (both"
    " classes); no Phase II lot informs any statistic, rank, or redundancy"
    " decision. Per sensor: point-biserial r, two-sample KS, two-sided"
    " Mann-Whitney U, and Cohen-style d (fail minus pass over pooled SD), all on"
    " pairwise-complete observations. Benjamini-Hochberg FDR is applied"
    " separately to the KS and Mann-Whitney p-value families. Sensors rank by"
    " mean rank across |r|, KS statistic, |d|, and min(q_ks, q_mw) (rankdata"
    " average ties, sensor code breaks order ties). Greedy redundancy: walking"
    " rank order, a sensor is marked redundant with the first already-retained"
    " sensor whose absolute window correlation exceeds the threshold."
    " Selection walks retained sensors in rank order, taking significant"
    " (q < alpha) sensors with |d| >= effect_floor up to max_selected; if fewer"
    " than min_selected qualify, the top retained sensors fill to min_selected"
    " (counted as floor_filled) so downstream SPC has a usable input set."
)


def benjamini_hochberg(pvalues: Sequence[float]) -> list[float]:
    """Return Benjamini-Hochberg FDR adjusted p-values (q-values)."""

    pvals = np.asarray(list(pvalues), dtype=float)
    count = pvals.size
    if count == 0:
        return []
    if np.any(~np.isfinite(pvals)) or np.any((pvals < 0) | (pvals > 1)):
        raise ValueError("BH input must be finite p-values in [0, 1].")
    order = np.argsort(pvals, kind="stable")
    ranked = np.empty(count, dtype=float)
    ranked[order] = pvals[order] * count / (np.arange(count) + 1)
    qvalues = np.minimum.accumulate(ranked[order][::-1])[::-1]
    result = np.empty(count, dtype=float)
    result[order] = np.clip(qvalues, 0.0, 1.0)
    return result.tolist()


def run(config_path: str | Path | None = None) -> dict[str, Path]:
    """Run screening on the configured SECOM window and write evidence."""

    config = load_config(config_path)
    screening = _screening_config(config)
    cleaned_path = _resolve_configured_path(config["secom"]["outputs"]["cleaned_data"])
    if not cleaned_path.is_file():
        raise FileNotFoundError(f"SECOM cleaned file is missing: {cleaned_path}")
    frame = pd.read_csv(cleaned_path, parse_dates=["timestamp"])
    _require_columns(frame, {"timestamp", "target"})
    sensors = sorted(column for column in frame.columns if column.startswith("sensor_"))
    if not sensors:
        raise ValueError("SECOM cleaned file contains no sensor columns.")
    frame = frame.sort_values("timestamp", kind="stable").reset_index(drop=True)

    total_rows = len(frame)
    window_rows = int(total_rows * float(screening["window_fraction"]))
    if window_rows < 10:
        raise ValueError("Screening window is too small for statistical tests.")
    window = frame.iloc[:window_rows]
    boundary = window["timestamp"].max()
    if (frame.iloc[window_rows:]["timestamp"] < boundary).any():
        raise ValueError("Source is not chronologically ordered at the window boundary.")
    target = window["target"].to_numpy()
    if not set(np.unique(target)).issubset({0, 1}):
        raise ValueError("Screening target must be binary 0/1.")

    records = [_sensor_record(window, sensor, int(screening["min_fail_n"])) for sensor in sensors]
    ranking = pd.DataFrame(records, columns=_CSV_COLUMNS)
    eligible = ranking.dropna(subset=["ks_pvalue", "mannwhitney_pvalue"]).index
    ks_q = pd.Series(np.nan, index=ranking.index)
    mw_q = pd.Series(np.nan, index=ranking.index)
    ks_q.loc[eligible] = benjamini_hochberg(ranking.loc[eligible, "ks_pvalue"].tolist())
    mw_q.loc[eligible] = benjamini_hochberg(ranking.loc[eligible, "mannwhitney_pvalue"].tolist())
    ranking["ks_qvalue"] = ks_q
    ranking["mannwhitney_qvalue"] = mw_q

    alpha = float(screening["fdr_alpha"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        rank_pb = pd.Series(stats.rankdata(-ranking["abs_point_biserial_r"].fillna(-1.0)), index=ranking.index)
        rank_ks = pd.Series(stats.rankdata(-ranking["ks_statistic"].fillna(-1.0)), index=ranking.index)
        rank_d = pd.Series(stats.rankdata(-ranking["effect_size"].abs().fillna(-1.0)), index=ranking.index)
        min_q = pd.concat([ranking["ks_qvalue"], ranking["mannwhitney_qvalue"]], axis=1).min(axis=1)
        rank_q = pd.Series(stats.rankdata(min_q.fillna(2.0)), index=ranking.index)
    complete = ranking[["abs_point_biserial_r", "ks_statistic", "effect_size"]].notna().all(axis=1) & min_q.notna()
    aggregate = pd.Series(np.nan, index=ranking.index)
    aggregate.loc[complete] = (rank_pb + rank_ks + rank_d + rank_q)[complete] / 4.0
    ranking["aggregate_rank"] = aggregate
    ranking = ranking.sort_values(
        ["aggregate_rank", "sensor"], na_position="last"
    ).reset_index(drop=True)

    threshold = float(screening["correlation_threshold"])
    corr = window[sensors].corr(numeric_only=True)
    retained: list[str] = []
    redundant_map: dict[str, str] = {}
    for sensor in ranking["sensor"]:
        if pd.isna(ranking.loc[ranking["sensor"] == sensor, "aggregate_rank"].iloc[0]):
            continue
        partner = next(
            (kept for kept in retained if abs(corr.loc[sensor, kept]) > threshold),
            None,
        )
        if partner is None:
            retained.append(sensor)
        else:
            redundant_map[sensor] = partner
    ranking["redundant_with"] = ranking["sensor"].map(redundant_map).fillna("")

    effect_floor = float(screening["effect_floor"])
    max_selected = int(screening["max_selected"])
    min_selected = int(screening["min_selected"])
    significant = ((ranking["ks_qvalue"] < alpha) | (ranking["mannwhitney_qvalue"] < alpha)).fillna(False)
    qualified = ranking[
        ~ranking["sensor"].isin(redundant_map)
        & significant.to_numpy()
        & (ranking["effect_size"].abs() >= effect_floor)
    ]
    selected = qualified["sensor"].head(max_selected).tolist()
    floor_filled = 0
    if len(selected) < min_selected:
        for sensor in ranking["sensor"]:
            if len(selected) >= min_selected:
                break
            if sensor not in redundant_map and sensor not in selected:
                selected.append(sensor)
                floor_filled += 1
    ranking["selected"] = ranking["sensor"].isin(selected)

    output_paths = _configured_output_paths(screening)
    for output_path in output_paths.values():
        output_path.parent.mkdir(parents=True, exist_ok=True)
    ranking.to_csv(output_paths["ranking"], index=False, lineterminator="\n")
    summary = _build_summary(
        ranking=ranking,
        selected=selected,
        total_rows=total_rows,
        window_rows=window_rows,
        window=window,
        boundary=boundary,
        screening=screening,
        output_paths=output_paths,
        floor_filled=floor_filled,
        redundant_map=redundant_map,
    )
    _write_json(output_paths["summary"], summary)
    return output_paths


def main(argv: Sequence[str] | None = None) -> int:
    """Run feature screening as a command-line program."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        output_paths = run(args.config)
    except Exception as exc:  # pragma: no cover - CLI error boundary
        print(f"Feature screening failed: {exc}", file=sys.stderr)
        return 1
    for key in _OUTPUT_KEYS:
        print(f"{key}: {output_paths[key]}")
    return 0


def _sensor_record(window: pd.DataFrame, sensor: str, min_fail_n: int) -> dict[str, Any]:
    values = pd.to_numeric(window[sensor], errors="coerce")
    target = window["target"].to_numpy()
    mask = values.notna().to_numpy()
    pass_vals = values.to_numpy(dtype=float)[mask & (target == 0)]
    fail_vals = values.to_numpy(dtype=float)[mask & (target == 1)]
    record: dict[str, Any] = {
        "sensor": sensor,
        "valid_pass_n": int(pass_vals.size),
        "valid_fail_n": int(fail_vals.size),
        "missing_rate": float(1.0 - mask.mean()),
        "point_biserial_r": np.nan,
        "abs_point_biserial_r": np.nan,
        "ks_statistic": np.nan,
        "ks_pvalue": np.nan,
        "ks_qvalue": np.nan,
        "mannwhitney_statistic": np.nan,
        "mannwhitney_pvalue": np.nan,
        "mannwhitney_qvalue": np.nan,
        "effect_size": np.nan,
        "aggregate_rank": np.nan,
        "redundant_with": "",
        "selected": False,
    }
    if fail_vals.size < min_fail_n or pass_vals.size < 2:
        return record
    if np.unique(pass_vals).size < 2 and np.unique(fail_vals).size < 2:
        return record
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            paired_target = target[mask].astype(float)
            paired_values = values.to_numpy(dtype=float)[mask]
            rvalue = stats.pointbiserialr(paired_target, paired_values)
            ks_result = stats.ks_2samp(pass_vals, fail_vals)
            mw_result = stats.mannwhitneyu(pass_vals, fail_vals, alternative="two-sided")
        except (ValueError, TypeError, ArithmeticError):
            return record
    pooled = _pooled_std(pass_vals, fail_vals)
    record["point_biserial_r"] = float(rvalue.statistic)
    record["abs_point_biserial_r"] = float(abs(rvalue.statistic))
    record["ks_statistic"] = float(ks_result.statistic)
    record["ks_pvalue"] = float(ks_result.pvalue)
    record["mannwhitney_statistic"] = float(mw_result.statistic)
    record["mannwhitney_pvalue"] = float(mw_result.pvalue)
    if pooled and np.isfinite(pooled):
        record["effect_size"] = float((np.mean(fail_vals) - np.mean(pass_vals)) / pooled)
    return record


def _pooled_std(pass_vals: np.ndarray, fail_vals: np.ndarray) -> float:
    denominator = pass_vals.size + fail_vals.size - 2
    if denominator <= 0:
        return float("nan")
    variance = (
        (pass_vals.size - 1) * np.var(pass_vals, ddof=1)
        + (fail_vals.size - 1) * np.var(fail_vals, ddof=1)
    ) / denominator
    return float(np.sqrt(variance))


def _screening_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    section = config.get("screening")
    if not isinstance(section, Mapping):
        raise ValueError("Configuration must contain a mapping at screening.")
    required = {
        "window_fraction",
        "fdr_alpha",
        "correlation_threshold",
        "min_selected",
        "max_selected",
        "min_fail_n",
        "effect_floor",
        "outputs",
    }
    missing = sorted(required.difference(section))
    if missing:
        raise ValueError(f"Configuration screening section is missing: {missing}.")
    if not 0 < float(section["window_fraction"]) < 1:
        raise ValueError("Configuration screening.window_fraction must be in (0, 1).")
    if not 0 < float(section["fdr_alpha"]) < 1:
        raise ValueError("Configuration screening.fdr_alpha must be in (0, 1).")
    if not 0 < float(section["correlation_threshold"]) < 1:
        raise ValueError("Configuration screening.correlation_threshold must be in (0, 1).")
    if int(section["min_selected"]) <= 0 or int(section["max_selected"]) < int(
        section["min_selected"]
    ):
        raise ValueError("Configuration screening selection bounds are inconsistent.")
    outputs = section["outputs"]
    if not isinstance(outputs, Mapping) or not set(_OUTPUT_KEYS).issubset(outputs):
        raise ValueError(
            f"Configuration screening.outputs must define: {', '.join(_OUTPUT_KEYS)}."
        )
    return section


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_configured_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _repository_root() / path


def _configured_output_paths(screening: Mapping[str, Any]) -> dict[str, Path]:
    outputs = screening["outputs"]
    return {key: _resolve_configured_path(outputs[key]) for key in _OUTPUT_KEYS}


def _require_columns(frame: pd.DataFrame, required: set[str]) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"SECOM cleaned data is missing column(s): {missing}.")


def _build_summary(
    *,
    ranking: pd.DataFrame,
    selected: Sequence[str],
    total_rows: int,
    window_rows: int,
    window: pd.DataFrame,
    boundary: Any,
    screening: Mapping[str, Any],
    output_paths: Mapping[str, Path],
    floor_filled: int,
    redundant_map: Mapping[str, str],
) -> dict[str, Any]:
    window_targets = window["target"]
    top = ranking.head(15)[
        ["sensor", "abs_point_biserial_r", "ks_statistic", "effect_size",
         "ks_qvalue", "aggregate_rank", "redundant_with", "selected"]
    ]
    return {
        "source_rows": total_rows,
        "screening_rows": window_rows,
        "window_fraction": float(screening["window_fraction"]),
        "window_boundary_timestamp": str(boundary),
        "window_pass_count": int((window_targets == 0).sum()),
        "window_fail_count": int((window_targets == 1).sum()),
        "candidate_sensor_count": int(ranking["ks_pvalue"].notna().sum()),
        "selected_sensors": list(selected),
        "selected_count": len(selected),
        "floor_filled": floor_filled,
        "fdr_alpha": float(screening["fdr_alpha"]),
        "correlation_threshold": float(screening["correlation_threshold"]),
        "methodology": METHODOLOGY,
        "top_ranked": top.to_dict(orient="records"),
        "redundant_sensors": [
            {"sensor": sensor, "redundant_with": partner}
            for sensor, partner in redundant_map.items()
        ],
        "paths": {key: str(path) for key, path in output_paths.items()},
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output_file:
        json.dump(payload, output_file, indent=2, sort_keys=True, ensure_ascii=False)
        output_file.write("\n")


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
